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

## Open items for later milestones

| Item | Milestone | Note |
|---|---|---|
| Verify `snowfall` unit under an imperial request | 2 | The snow thresholds assume **inches of snow depth**, not liquid equivalent. To be pinned by a provider contract test against a recorded winter fixture, not taken on trust from documentation. |
| Routing provider credentials | 2 | No key is needed for anything in Milestone 1. |
| Fewer than three alternatives returned | 2 | Return what exists with an explicit notice; optionally synthesise a third via an avoid-tolls/avoid-motorways variant, de-duplicated by geometry overlap. |
| Forecast-time matching | 3 | Match each ETA to the **nearest** hour, not the floor — flooring biases forecasts up to 59 minutes early. |
| Checkpoint count ceiling | 3 | A 2,000-mile route at 10-mile spacing is 200 checkpoints × 3 routes. Cap and auto-coarsen with a notice rather than time out. |
