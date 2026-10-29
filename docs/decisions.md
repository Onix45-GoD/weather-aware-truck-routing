# Decisions and assessment interpretation

The assessment leaves a number of things genuinely ambiguous. This document
records every interpretation, the reasoning behind it, and where it is pinned
down by a test. Nothing here silently changes the stated requirements; where a
rule is added it is additive and sits outside the specified logic rather than
replacing it.

Each decision below is one of:

- **Approved** — confirmed before implementation.
- **Additive** — not specified by the assessment; adopted as the
  safety-conservative reading, and marked as such.

---

## D1. Threshold boundary convention — *Approved*

**The ambiguity.** The table mixes explicit operators (`<25`, `≥55`, `>1.00`)
with bare ranges (`25–34`, `0.10–0.25`). Read literally this leaves two
problems:

- **Gaps.** Wind is Moderate at `25–34` and High at `35–44`. What is 34.6 mph?
- **Shared endpoints.** Rain is Moderate at `0.10–0.25` and High at
  `0.25–0.50`. 0.25 in/hr appears in both columns.

**The convention.** Bands are **lower-bound inclusive**. Each listed lower
bound belongs to its own band, every real value falls in exactly one band, and
a shared interior boundary resolves **upward** — to the more severe band, the
safety-conservative reading.

The topmost cut honours the table's literal operator rather than the general
rule:

| Condition | No Travel when | So the boundary value itself is |
|---|---|---|
| Wind | `>= 55` mph | 55.0 mph → **No Travel** |
| Rain | `> 1.00` in/hr | 1.00 in/hr → **Severe** |
| Snow | `> 3.0` in/hr | 3.0 in/hr → **Severe** |

This reproduces the published table exactly on every value the table states,
and is total over the reals.

**Resulting bands:**

```
Wind  Low [0,25)   Moderate [25,35)   High [35,45)   Severe [45,55)   NT [55,∞)
Rain  Low [0,0.10) Moderate [0.10,0.25) High [0.25,0.50) Severe [0.50,1.00] NT (1.00,∞)
Snow  Low [0,0.5)  Moderate [0.5,1.0) High [1.0,2.0) Severe [2.0,3.0]   NT (3.0,∞)
```

**Tested by** `test_risk.py::TestWindThresholds` /
`TestRainThresholds` / `TestSnowThresholds` — every boundary value, the value
immediately either side, and the gap values a literal reading does not cover.

---

## D2. Sustained wind, not gusts — *Approved*

**The ambiguity.** The table says only "Wind mph". Sustained and gust speeds
routinely differ by 30–50%, so this one choice moves a large fraction of
checkpoints by a full risk level.

**The decision.** Classify on **sustained** wind speed. The 25/35/45/55 ladder
matches the National Weather Service sustained-wind advisory scale, which is
the most likely provenance of these numbers.

Gusts are a real concern for a high-profile trailer, so `WeatherSample` carries
`wind_gust_mph` for display in the UI — but it never affects classification.
`test_gusts_do_not_affect_classification` asserts that a 10 mph sample with
70 mph gusts still classifies as Low.

**Reversible:** swapping the classified field is a one-line change in
`assess_checkpoint`.

---

## D3. Values are not rounded before classification — *Approved*

Rounding before a threshold comparison is a classic source of
off-by-a-category bugs: 24.96 mph rounds to 25 and would jump from Low to
Moderate. Measurements are compared raw; rounding happens only when formatting
explanation strings for display.

Unit conversion is avoided for the same reason. Forecasts are requested from
the provider directly in assessment units (mph, inches/hour), so no arithmetic
sits between the provider's number and the comparison.

**Tested by** `test_classification_uses_unrounded_values`.

---

## D4. Combining wind, rain and snow — *Approved*

**The ambiguity.** The assessment classifies each condition but never says how
to combine them at one checkpoint.

**The decision.** `checkpoint_risk = max(wind_after_override, rain, snow)`.

No additive compounding. The assessment specifies no compounding rule, and
inventing one would produce numbers that are uncalibrated and impossible to
explain to a driver. Three simultaneous Moderates stay Moderate.

The condition that produced the maximum is recorded as the `driver`. When two
conditions tie at the same severity, priority is **wind → rain → snow**, purely
to make the reported driver deterministic.

**Tested by** `TestAssessCheckpoint::test_maximum_severity_wins`,
`test_conditions_are_not_compounded`,
`test_driver_tie_resolves_to_wind_then_rain_then_snow`.

---

## D5. Cargo-weight overrides use strict `>` — *Approved*

Exactly as written in the assessment:

| Wind band | Load | Result |
|---|---|---|
| `>= 55` mph | any | No Travel |
| 45–54 mph | `> 30,000` lb | No Travel |
| 45–54 mph | `<= 30,000` lb | Severe (unchanged) |
| 35–44 mph | `> 40,000` lb | Severe |
| 35–44 mph | `<= 40,000` lb | High (unchanged) |

Overrides apply to **wind only**, and only ever **escalate** — the result is
the more severe of the base level and the override, so a load rule can never
make a route look safer. A rain-driven No Travel survives a wind band that
would otherwise "set" Severe.

The boundary values matter: at exactly 30,000 lb and exactly 40,000 lb the
override does **not** fire, because 30,000 is not `> 30,000`.

**Tested by** `TestCargoWeightOverrides` — each rule at the boundary and
immediately either side, plus `test_override_never_de_escalates`.

---

## D6. Forward segment attribution — *Approved*

**The ambiguity.** The ranking criteria are in **miles**, but checkpoints are
*points*. Converting one to the other is unspecified.

**The decision.** Checkpoint *i* governs `[d_i, d_(i+1))` — every mile is
owned by the conditions measured where the driver *enters* it.

Checkpoints are generated at `0, interval, 2×interval, …` plus the destination
at exactly the route distance, so with *n* checkpoints there are *n−1* segments
summing to exactly the route length. The destination owns zero forward miles
(see D10).

**Rejected alternative:** midpoint/Voronoi attribution, where each checkpoint
owns half the distance on each side. It smears severe weather backwards onto a
clear segment the driver has already passed, and needs special cases at both
ends.

**Tested by** `TestSegmentAttribution` — including explicit first-segment and
final-segment tests, mileage conservation across four different route shapes,
and a no-double-counting test that walks the segments end to end.

---

## D7. Average risk is distance-weighted — *Approved*

Risk levels map to ordinal scores `LOW=0, MODERATE=1, HIGH=2, SEVERE=3,
NO_TRAVEL=4`, and the route average is:

```
average_risk = Σ(score_i × segment_miles_i) / Σ(segment_miles_i)
```

**Not** a mean over checkpoints. With an unweighted mean, a 50-mile stretch
sampled every 10 miles outvotes a 200-mile stretch sampled every 50 miles
purely because of sampling density — so the recommendation could flip based on
which interval the user picked rather than on the weather.

**Tested by** `test_weights_by_miles_not_by_checkpoint_count` (a case where the
weighted and unweighted answers genuinely differ) and
`test_interval_invariance_under_constant_weather`.

> **Note on interval invariance.** The invariance test uses synthetic routes
> with *constant, controlled* weather, so it tests the algorithm. Real
> forecasts legitimately produce different scores at different intervals,
> because finer sampling discovers weather that coarser sampling misses — that
> is a property of the data, not a defect in the aggregation, and it is
> deliberately **not** asserted.

---

## D8. Missing data is UNKNOWN, never LOW — *Approved*

`RiskLevel.UNKNOWN` has **no severity score**. It cannot be compared as a
severity, cannot be averaged, and cannot be combined as if it were Low.
Treating a forecast gap as good weather would make a provider outage look like
clear skies — the most dangerous possible failure mode here.

Consequences, all explicit:

- Unknown miles are tracked in their own bucket and reported.
- They are excluded from **both** the numerator and the denominator of the
  average, so the average describes only the miles actually observed.
- `coverage_pct` reports the share of route miles with a usable forecast.
- A route with no usable data at all has `average_risk = None`.
- When only *some* variables are missing at a checkpoint, the known ones still
  decide the level and `partial_data` is flagged, so the gap is visible rather
  than silent.

**Tested by** `TestUnknownWeatherHandling` and
`test_unknown_never_reads_as_low`.

---

## D9. No Travel safety gate — *Approved*

**The ambiguity.** The four-tier ranking has no slot for "this route cannot
safely be driven". Ranking a No Travel route first because it happened to have
fewer *Severe* miles would be an unsafe output.

**The decision.** A route with any No Travel condition is **blocked**: still
ranked, still returned, still drawn on the map with its blocking checkpoints
highlighted — but never recommended while an eligible route exists. If every
route is blocked, `recommended_route_id` is `null` and the blocked routes are
still ordered least-bad-first so the driver can see their options.

The gate is **prepended** to the assessment's criteria, not substituted for
them. Within the eligible set, ordering is precisely the specified order.

**Tested by** `TestNoTravelSafetyGate` — including
`test_the_gate_outranks_every_assessment_criterion`, where the blocked route
wins all four criteria outright and still loses.

---

## D10. No Travel at the destination blocks the route — *Additive*

Under forward attribution (D6) the destination checkpoint owns **zero** miles.
A mileage-only blocking test would therefore miss a driver arriving into a
60 mph windstorm: `no_travel_miles` would be 0.0 and the route would look
clear.

`RouteMetrics.blocked` is therefore `no_travel_miles > 0 OR
no_travel_checkpoints > 0`. This is a strict superset of the approved rule —
it blocks everything the mileage rule blocks, plus this edge case — and is
flagged here because it goes slightly beyond what was specified.

**Tested by** `test_no_travel_at_the_destination_still_blocks` and
`test_destination_only_no_travel_blocks_the_route`.

---

## D11. Insufficient coverage makes a route ineligible — *Additive*

A route with no forecast data scores **perfectly** on every criterion: zero
Severe miles, zero High miles, and no average risk to compare. Without a gate
it would beat a fully-forecast route carrying a little bad weather — a perfect
scorecard produced entirely by ignorance.

**The policy.** A route is eligible for recommendation only when it is not
blocked **and** `coverage_pct >= MIN_COVERAGE_PCT` (default **95%**). Unknown
mileage is preserved in the metrics and reported either way; it is never
quietly treated as good news. The threshold is a parameter of `rank_routes`,
not a hidden constant.

**Tested by** `TestCoveragePolicy`, especially
`test_ignorance_cannot_win_a_recommendation`, plus the threshold boundary
itself.

---

## D12. Deterministic total order — *Approved*

The full sort key:

```
(blocked_or_ineligible,          # safety gate      — D9, D11
 severe_miles,                   # criterion 1
 high_miles,                     # criterion 2
 average_risk,                   # criterion 3
 duration_seconds,               # criterion 4
 unknown_miles,                  # tie-break: prefer the better-understood route
 provider_index,                 # tie-break: provider's original ordering
 route_id)                       # tie-break: guarantees a total order
```

The three tie-breaks sit **after** all four assessment criteria, so they can
never override the specified logic — they only decide cases the assessment
leaves undetermined. The last two guarantee that identical input always
produces an identical recommendation, with no reliance on dictionary iteration
or sort stability.

Comparisons are quantised (miles to 3 decimal places ≈ 1.6 m, average risk to
6, duration to 3) so floating-point noise a billionth of a mile wide cannot
flip a ranking.

The response reports *which* key position decided each adjacent pair, so the
UI can say "recommended because it has the fewest Severe miles" rather than
asking the driver to trust an opaque score.

**Tested by** `TestCriterionOrder` (each criterion independently),
`TestTieBreaksAndDeterminism` — including a permutation test asserting that all
six input orderings of three routes produce the same ranking, and 25 repeated
runs producing byte-identical output.

---

## D13. ETA estimation — *Approved*

Two strategies, in preference order:

1. **Provider segment durations.** Cumulative time is interpolated within the
   geometry segment containing the target distance, so ETAs follow the real
   speed profile of the road. The profile is rescaled so its final value equals
   the route's headline duration exactly — providers routinely report
   per-segment numbers that do not sum to their own total.
2. **Distance-proportional fallback.** Constant average speed across the route.
   Used when no per-segment timing is available, documented as an
   approximation, and reported in the API response so it is never mistaken for
   the real thing.

Both are monotonic non-decreasing in distance, so checkpoint ETAs can never
travel backwards. The departure time must be timezone-aware; the domain never
reads the clock.

**Known limitation (flagged, not resolved):** no Hours-of-Service rest breaks,
fuel stops or departure-traffic modelling. ETAs are pure driving time, as the
assessment implies. This must be stated in the UI so the output is not mistaken
for a dispatch-grade schedule.

**Tested by** `TestEtaProportionalFallback` and
`TestEtaFromProviderSegmentDurations`.

---

## D14. Checkpoint interval is a user input — *Interpretation*

The assessment PDF reads "Sample weather every 10 / 25 / 50 miles", which could
mean a fixed three-tier sampling scheme or a user-selected spacing. It is
implemented as a **user-selected interval** (`CheckpointInterval` = 10, 25 or
50), which is the more useful reading and the one the brief for this build
specified.

The domain functions accept any positive interval so they can be tested on
arbitrary synthetic spacings; the enum constrains the choice at the API
boundary.

---

## D15. No database — *Decision*

Nothing in the assessment requires persistence. `DATABASES` is empty, and
`django.contrib.auth`, `sessions` and `admin` are not installed.

> Django rewrites an empty `DATABASES` in place, inserting a `default` entry on
> the dummy backend the first time anything touches `connections` — a single
> request is enough. So `test_project_has_no_real_database_configured` asserts
> that no *real* engine is configured rather than that the dict is still
> literally empty.

---

## D16. Cargo weight is never sent to the routing API — *Decision*

**The trap.** The assessment supplies **cargo load weight**. TomTom's
`vehicleWeight` parameter means **gross vehicle weight** — tractor plus
trailer plus cargo. They differ by roughly 30,000 lb for a typical rig.

Passing the cargo figure as `vehicleWeight` would be worse than passing
nothing: the provider would apply weight restrictions calibrated to a vehicle
far lighter than the real one, and could route a loaded truck across a bridge
it is not permitted to cross. Inventing a tare weight to add would be
fabricating vehicle data we were never given.

**The decision.** The adapter sends `travelMode=truck` and **no
vehicle-weight, axle, height, length or width parameter at all**. The
assessment's cargo-weight rules are a *risk-scoring* input and stay in
`apps/routing/domain/risk.py`, which is where they belong.

**The limitation, stated rather than hidden.** Returned routes respect generic
truck restrictions but **not** weight-, height-, length- or axle-specific
ones. Closing that gap requires collecting real vehicle specifications from
the user — a product decision, not something to paper over with a guess.

**Tested by** `test_cargo_weight_is_never_sent_as_a_vehicle_weight`, which
asserts none of those parameters appears in the outgoing request.

---

## D17. Open-Meteo `snowfall` is snow depth — *Verified, not assumed*

This was the milestone's explicit acceptance criterion, so it was answered
with live data rather than documentation.

Two live calls were made on 2026-10-28 for the same location and hours — one
with default units, one with `precipitation_unit=inch` — and saved as
`real_snowfall_metric.json` / `real_snowfall_imperial.json`. Fairbanks, AK was
chosen because its forecast actually contained snow, without which the ratios
below would prove nothing.

| Finding | Evidence |
|---|---|
| Default unit is **cm**; with `precipitation_unit=inch` it is **inch** | `hourly_units.snowfall` in each capture |
| The inch value is the **same quantity**, converted | `snowfall_cm / snowfall_inch` = 2.50–2.545 across all snowy hours (the spread is the API's 2–3 significant-figure rounding) |
| `snowfall` is **depth**, not liquid-water equivalent | `snowfall_cm / precipitation_mm` = **exactly 0.700** in every snowy hour — Open-Meteo's fixed 7:1 snow-to-liquid ratio. Liquid equivalent would give 0.1 |
| The wind unit string is `"mp/h"`, not `"mph"` | `hourly_units.wind_speed_10m` |

**Conclusion.** Requesting `precipitation_unit=inch` returns **inches of snow
depth per hour** — exactly what the assessment's thresholds mean. **No
conversion is needed on the happy path.** Had we assumed liquid equivalent,
snow risk would have been under-reported by a factor of seven.

Conversions are implemented anyway and driven by the `hourly_units` each
response *declares*, not by what we asked for, so a provider that ignores a
unit parameter is still handled correctly. An unrecognised unit raises
`InvalidProviderResponseError` rather than being guessed at.

### D17a. Conversions divide; they never multiply by a reciprocal

Writing the conversion as `value * (1 / 2.54)` gives
`5.08 * (1/2.54) == 1.9999999999999998`, which classifies as **HIGH** instead
of **SEVERE**. Writing it as `value / 2.54` gives exactly `2.0`.

The error is one ULP and it lands precisely on the risk thresholds — the one
place it can change an answer. The unit tables therefore store divisors
(2.54, 25.4, 1.609344, 0.44704, all exact decimal definitions) and the code
divides. This was caught by the test suite during this milestone and is now
guarded by `test_conversion_divides_rather_than_multiplying_a_reciprocal`.

---

## D18. Rain is `rain + showers`, never `precipitation` — *Decision*

Open-Meteo separates `rain` (large-scale) from `showers` (convective), and
`precipitation` is the total *including snow's liquid equivalent*.

- Using `rain` alone under-reports thunderstorms.
- Using `precipitation` as the rain rate double-counts snowy hours, scoring
  the same weather as both snow and rain.

So the adapter requests both components and sums them. Where both are missing
the result is `None` (UNKNOWN); where only one is missing, the known component
is used.

---

## D19. Forecast selection: nearest hour, ties round up — *Decision*

`HourlyForecast.sample_at()` picks the nearest available hour. An exact
half-hour tie resolves to the **later** hour, matching D13's round-half-up
convention. An instant further than 30 minutes from any available hour is
outside the forecast horizon and returns `None`, which classifies as UNKNOWN
rather than silently reusing the last known hour.

Hourly data matched to the nearest hour is still hourly data. Nothing
downstream presents it as minute-accurate.

---

## D20. Forecasts are associated by index, never by coordinate — *Decision*

Open-Meteo snaps requested coordinates to its model grid: asking for
`39.74, -104.99` returns `39.746895, -104.987076`. Matching responses back by
coordinate equality would therefore fail outright, and matching by proximity
could pair the wrong checkpoint with the wrong forecast — a silent,
plausible-looking error.

Multi-location responses are a JSON array in request order, so association is
strictly positional. Both the requested and the resolved coordinate are kept
on `HourlyForecast` so the discrepancy stays visible.

---

## D21. Coordinate cache precision: 2 decimal places — *Decision*

Near-identical checkpoints are collapsed into one forecast lookup, which is
what keeps a three-route analysis down to a couple of outbound calls. The
rounding has to be fine enough that it never merges points the provider would
have answered differently.

Two decimal places is ~1.1 km of latitude (~0.85 km of longitude at 40°N),
**finer than Open-Meteo's finest model grid (~2 km)**. One decimal place would
be ~11 km, which genuinely would merge distinct checkpoints. The value is
pinned and tested rather than tuned for cache-hit rate.

---

## D22. Synchronous HTTP — *Decision*

The project runs under WSGI with ordinary synchronous DRF views. Going async
would mean either an ASGI migration or `async_to_sync` bridging throughout.

The benefit would be small: the Open-Meteo adapter collapses every checkpoint
into one or two bulk calls, so a full analysis is roughly four outbound
requests. Where genuine parallelism helps — the two independent geocode calls
— `run_bounded()` provides it with a small thread pool. That is a far smaller
change, and it keeps `respx` mocking and stack traces simple.

---

## D23. Route de-duplication is deliberately strict — *Decision*

Two routes are merged only when their vertex sets overlap by ≥98% **and**
their distance and duration agree to within 1%. Requiring both prevents a
genuinely different alternative that happens to share most of its length — a
50-mile detour off a 900-mile interstate run — from being discarded.

Losing a real option is worse than showing the driver two similar ones. The
earlier route always survives, so the provider's ordering and the
`provider_index` tie-break stay stable.

**Route counts are never padded.** If the provider returns two distinct
routes, two are returned, with a notice saying so. A third is never invented.

---

## D24. Single-leg routes report no provider timings — *Decision*

`calculateRoute` with no intermediate waypoints returns a **single leg**,
whose only timing is the route total. Spreading that total across the geometry
would reproduce the domain's own distance-proportional fallback exactly, while
labelling it as provider data.

So the adapter returns `segment_durations=None` for single-leg routes and lets
the domain apply — and report — its documented fallback honestly. With two or
more legs, the per-leg times are real extra information and are distributed
across each leg's own segments by distance.

---

## D25. Credentials are scrubbed from third-party logs — *Decision*

The API key travels as a query parameter, so it appears in any log line
containing the URL. Our own logging redacts it. **httpx's does not**: it logs
every request at INFO as `HTTP Request: GET https://...?key=SECRET "200 OK"`,
which would publish the key to any log aggregator the moment INFO is enabled.

`RedactingFilter` is attached to the `httpx` and `httpcore` loggers on import
of the provider HTTP module — there is no opt-in step to forget. It scrubs
both the format string and the arguments, including non-string arguments such
as `httpx.URL`.

Credentials are also excluded from cache keys entirely — dropped, not hashed —
so a key cannot be recovered from cache storage even in principle, and
rotating a key does not invalidate the cache.

This was found by a test written to assert the opposite, which is the only
reason it was found at all.

---

## D26. No real TomTom fixture — *Closed 2026-10-28*

Milestone 2 was initially written without a TomTom key, so every TomTom
fixture was synthetic and the adapter was verified against documented schema
rather than observed output.

**Genuine responses were captured on 2026-10-28T16:03:21Z** with
`backend/scripts/capture_tomtom_fixtures.py`, and the limitation is closed.

What the capture established:

- TomTom returned **3 distinct truck routes** for Denver to Chicago
  (1,004 / 1,142 / 1,315 mi). The count was not padded, and nothing was
  de-duplicated.
- **Every route has exactly one leg**, confirming D24 from observed data
  rather than inference: ETAs correctly fall back to the documented
  distance-proportional model.
- The `score` field is not a confidence. See **D27** — a genuine defect that
  synthetic data could not have surfaced.

The capture script drives the real adapter and records the response through an
httpx event hook, so a fixture is by construction exactly what the production
path receives. Only response bodies are stored, never request URLs (which
carry the key as a query parameter), and each body is scanned for the key
before being written. With no key set it explains what to do and exits
non-zero; it never invents data.

`test_tomtom_real_fixtures.py` replays the captures through `respx`, so the
contract tests stay offline and keyless.

**What this does and does not prove.** The adapter now parses what TomTom
actually sends on the happy path. It does **not** make the integration
production-ready: there is no load testing, no observed behaviour at quota
limits, no long-term schema-drift monitoring, and a single capture is one
point in time. The `-m live` tests remain the drift check, and they are
non-deterministic by nature.

## D27. TomTom's `score` is not a confidence — *Defect found and fixed*

Found by the genuine capture, and invisible to every synthetic test before it.

TomTom's published documentation describes the geocoding result's top-level
`score` as *"Relevance score (0–1 scale, where 1 is perfect match)"*. The real
API disagrees. An exact match for "Denver, CO" returns:

```json
{ "score": 4.7333083153, "matchConfidence": { "score": 1 } }
```

`score` is an **unbounded relevance ranking**, useful only for ordering
several results against each other. `matchConfidence.score` is the real 0–1
confidence.

**Why it mattered.** The adapter exposed `score` as `GeocodeResult.confidence`
— a field whose name promises a 0–1 value. Any later threshold such as
`confidence > 0.8` would therefore pass for *every* result, including bad
geocodes, silently defeating a check written to catch exactly those.

**The fix.** `_match_confidence()` reads `matchConfidence.score`, and returns
`None` when it is absent or outside 0–1 rather than substituting a number that
means something else. The unbounded `score` is deliberately not exposed; we
only ever request one result, so a relative ranking has no use.

**How it hid for a whole milestone.** The synthetic fixture faithfully encoded
the documented value (`0.9947`), so every test agreed with every other test
and all of them were wrong together. This is the precise failure mode that
makes synthetic-only verification insufficient, and the reason D26 was tracked
as a real limitation rather than waved through. The synthetic fixture now
carries the observed shape.

**Tested by** `TestConfidenceSemantics` (synthetic, including rejection of
out-of-range and non-numeric values) and
`test_the_genuine_score_is_not_a_zero_to_one_confidence`, which fails if a
future capture ever makes the documented claim true — a signal to revisit the
workaround rather than leave it in place forever.

---

## D28. `forecast_offset_hours` is a departure shift, not the heatmap slider — *Decision*

These are two different features that both involve "0–48 hours", and
conflating them would produce a control that looks like it works and does
not.

| | Corridor slider (Milestone 6) | `forecast_offset_hours` (this milestone) |
|---|---|---|
| What it is | A display control | A trip input |
| What it changes | Which hourly frame the heatmap paints | The departure instant |
| Re-runs the analysis | No — frames are prefetched | **Yes** — routing, ETAs, weather, ranking |
| Can change the recommendation | **No** | **Yes** |
| Network cost of moving it | None | One full analysis |

The architecture document and the frontend placeholder both describe the
slider as a client-side scrubber over prefetched frames, and that is
preserved unchanged. The request field is the other thing: "what if I leave
six hours later?" It recomputes everything from
`departure_at + forecast_offset_hours`, so the answer is a real answer and
not a recolour.

**Tested by** `TestForecastOffset` in both the service and API suites,
including `test_offset_can_change_the_recommendation`, which constructs a
storm that moves between the two options.

A UI must not wire the heatmap slider straight to this field unless it
intends to re-run the analysis on every drag.

---

## D29. Geocoding confidence policy — *Decision*

Routing from the wrong "Springfield" produces a complete, plausible and
entirely wrong analysis. Nothing downstream would look suspicious, which
makes it worse than an error.

Two cases, deliberately treated differently:

| Provider says | Action | Why |
|---|---|---|
| Confidence **below** `MIN_GEOCODE_CONFIDENCE` (default 0.5) | **Reject** with `LOCATION_AMBIGUOUS` (HTTP 400), naming the field | The provider told us it is unsure; proceeding would bury that |
| **No** confidence reported | Proceed, with a `GEOCODE_CONFIDENCE_UNKNOWN` warning | Absent evidence is not strong evidence (the D27 lesson), but rejecting would break every provider that does not report one |

The floor is a setting, not a constant, so it can be tuned without a code
change.

---

## D30. Departure time accepts a named timezone — *Decision*

A driver thinks "I leave at six", not "I leave at 13:00Z". Requiring the
client to send a UTC offset pushes the daylight-saving problem onto the
client, which is exactly where it goes wrong.

`America/Denver` is **-06:00 on 2026-11-01 and -07:00 on 2026-11-02** — DST
ends between them. A client computing "my offset" from today's date is an
hour out for any trip across that boundary, and so is every checkpoint
forecast and potentially the recommendation.

**The contract** — three shapes, one of them rejected:

| Input | Result |
|---|---|
| `departure_at` with an offset | That is the instant. `departure_timezone` is then display-only |
| naive `departure_at` + `departure_timezone` | Read as local wall-clock time in that zone |
| naive `departure_at` alone | **400.** Guessing a zone would move the trip by hours |

DRF would otherwise have done the guessing itself: with `USE_TZ = True` it
*localises* a naive timestamp into the server's zone rather than rejecting
it. `TripDateTimeField` parses the raw value and preserves naivety so
`validate()` can decide, rather than inheriting a silent default.

### The two daylight-saving edges

Twice a year a wall-clock time is either ambiguous or impossible, and
`zoneinfo` resolves both silently.

* **Ambiguous** (clocks go back): `2026-11-01 01:30` happens twice in Denver.
  The **earlier** occurrence is used — the safer reading for a departure —
  and an `AMBIGUOUS_LOCAL_TIME` warning says so.
* **Nonexistent** (clocks go forward): `2026-03-08 02:30` never happens.
  The time shifts to `03:30` local with a `NONEXISTENT_LOCAL_TIME` warning.

**Order matters in the implementation.** PEP 495's `fold` yields two
different offsets for *both* transitions, so comparing folds cannot tell them
apart — an early version mislabelled the spring-forward gap as ambiguous. The
round-trip test distinguishes them: a wall time that exists survives
`local -> UTC -> local`, and one that does not gets moved.

### What stays in UTC

Every timestamp on the wire is UTC. The response adds
`departure_timezone`, `departure_at_local`, `effective_departure_at_local`
and per-route `arrival_at_local` as *echoes*, so a driver can confirm their
input was read correctly. Checkpoint ETAs are **not** duplicated in local
form — that would roughly double the payload for something a client
reconstructs from the UTC value plus the zone name.

Browsers can populate a picker from `Intl.supportedValuesOf('timeZone')`, so
no endpoint lists zones.

**Tested by** `test_timezones.py` (24 tests), including six zones end to end,
both DST edges, and `test_the_same_instant_expressed_two_ways_analyses_identically`
— a timezone labels an instant, so it must never change a result.

---

## D31. The corridor slider is reference-time frames over the same forecast — *Decision*

The assessment asks for a weather heatmap along the corridor with a 0–48 h
slider. Three readings were possible; one was chosen and the other two are
recorded so nobody re-derives them.

| Reading | What hour +*h* would mean | Why not |
|---|---|---|
| **Reference-time frame** (chosen) | `effective_departure_at + h` at **every** checkpoint | — |
| ETA-shifted | each checkpoint at its *own* ETA + *h* | That is `forecast_offset_hours` — a departure shift that changes the answer (D28), not a display control |
| Wall-clock from now | `now + h` | The analysis is anchored to departure, not to when the page is open; the two drift apart by the minute |

**Source and step.** The frames are Open-Meteo's hourly series — the same
provider, adapter, unit normalisation, de-duplication, chunking and cache the
analysis uses — classified by the same `assess_route` and summarised by the
same `summarise_route`. The step is one hour because the data is hourly. No
interpolation, no synthetic hours. OpenWeatherMap was briefly integrated for
supplementary conditions and map rasters and then removed (D32): once the
corridor frames carry every hour, a second provider with a different model
and a coarser step added a key, two panels and a contradiction to explain.

**Horizon.** `HourlyForecast.sample_at` (D19) decides whether an hour exists.
An hour outside what the provider returned is `available: false` and every
checkpoint is UNKNOWN (D8); the frame is still returned so the slider shows
the gap rather than silently reusing the nearest hour. `forecast_window`
reports what the provider actually covered.

**Resolution.** The band is drawn at checkpoint resolution with forward
attribution (D6), the same convention as the ETA risk line. It is a sampled
visualisation and the documentation says so; it is not a radar field and
does not claim spatial precision the data lacks.

**Isolation.** The endpoint is read-only over the analysis's inputs. It
cannot change the departure, the ETAs or the recommendation; the App's
baseline metrics are never overwritten by a frame. Tested by
`TestBaselineIsUntouched` (API) and `never re-runs the analysis` (frontend).

**Tested by** `tests/services/test_corridor.py` (49 frames, exact hour and
checkpoint association, beginning/middle/end, missing and partial data,
horizon edges, provider failures, cargo-weight override via the domain as
oracle), `tests/api/test_corridor_forecast.py` (contract, validation, gzip,
de-duplication, a request built from a real analysis response) and the
frontend `features/corridor` suites.

---

## D32. One weather provider — *Decision*

OpenWeatherMap was added in Milestone 4b for a checkpoint conditions panel
and precipitation/cloud/wind/temperature map rasters, and removed in
Milestone 6. Reasons, in order of weight:

1. **Redundancy.** The corridor forecast (D31) carries Open-Meteo's hourly
   series for every checkpoint across 48 hours. The OWM panel showed the
   same question answered by a different model at a 3-hour step, and the
   two could disagree on screen with no way to say which mattered.
2. **Simplicity.** One provider, one key fewer, one less panel, no °F/°C
   toggle, no overlay toggle, no health probe to gate them.
3. **Semantics.** The rasters showed *current* conditions under a
   *forecast*-driven recommendation — a correspondence that does not exist,
   which the legend had to keep disclaiming.

What replaced it: clicking a checkpoint opens a map popup with the ETA
conditions and that checkpoint's 48-hour risk strip, and the panel shows
the full hourly table — all from the corridor frames already in memory.

Also removed in the same pass, with the user's agreement: the
`forecast_offset_hours` form slider (the API field stays; a second 0–48 h
slider beside the corridor timeline invited exactly the confusion D28
warns about), the SVG weather-profile chart (the table and the hour strip
carry it), and the icon sidebar (three sections that were never separate
views). The departure timezone now defaults to `America/Denver` — the
default origin's zone — rather than the browser's: this is a US trucking
tool, and a dispatcher abroad still plans in the truck's zone.

---

## Open items for later milestones

### Closed in Milestone 2

| Item | Outcome |
|---|---|
| Real TomTom fixture | ✅ **Resolved — D26.** Captured 2026-10-28; 3 distinct routes, single leg each. Surfaced a real defect (D27). |
| Verify `snowfall` unit under an imperial request | ✅ **Resolved — D17.** Verified against live responses, not documentation: `snowfall` is snow depth, and `precipitation_unit=inch` returns inches of depth. No conversion needed on the happy path. |
| Fewer than three alternatives returned | ✅ **Resolved — D23.** What exists is returned with an explicit notice; counts are never padded. A synthesised avoid-tolls variant remains a possible future enhancement, not a requirement. |
| Forecast-time matching | ✅ **Resolved — D19.** Nearest hour, ties round up, out-of-horizon returns UNKNOWN. |

### Still open

| Item | Milestone | Note |
|---|---|---|
| Provider schema drift | ongoing | A single capture is one point in time. `pytest -m live` is the drift check, and it is non-deterministic by nature. |
| Checkpoint count ceiling | 3 | A 2,000-mile route at 10-mile spacing is 200 checkpoints × 3 routes. Cap and auto-coarsen with a notice rather than time out. |
| Provider attribution in the UI | 6 | Partly done: the map credits CARTO/OpenStreetMap and OpenWeatherMap, the timeline and checkpoint panel name Open-Meteo. A footer credit for TomTom is still to add. |
| Fixture-mode labelling in the UI | 6 | When the offline providers are active the interface must say so, so synthetic weather is never mistaken for a forecast. |
