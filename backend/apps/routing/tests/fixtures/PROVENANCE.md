# Fixture provenance

Every fixture is either a **genuine captured provider response** or **synthetic
data written by hand**. The two are never mixed, and the filename prefix always
says which: `real_*` or `synthetic_*`.

Nothing here is current weather. The `real_*` forecasts are a snapshot of what
the provider said on one day in the past; they are frozen inputs for contract
tests and must never be rendered to a user as live conditions.

---

## `openmeteo/real_*.json` — genuine captured responses

| File | Source |
|---|---|
| `real_snowfall_imperial.json` | `GET https://api.open-meteo.com/v1/forecast` |
| `real_snowfall_metric.json` | same endpoint, default units |
| `real_multi_location.json` | same endpoint, three comma-separated coordinates |

- **Captured:** 2026-10-28T13:54:49Z
- **Captured by:** `backend/scripts/make_fixtures.py` sibling capture (ad-hoc,
  recorded here) using the public endpoint.
- **Credentials:** none. Open-Meteo requires no API key for non-commercial
  use, so there was nothing to redact — these are unmodified responses.
- **Modifications:** none beyond JSON re-indentation.

**Request parameters**

```
real_snowfall_imperial.json
  latitude=64.8  longitude=-147.7          (Fairbanks, AK)
  hourly=wind_speed_10m,wind_gusts_10m,rain,showers,snowfall
  timezone=UTC  forecast_days=3
  wind_speed_unit=mph  precipitation_unit=inch

real_snowfall_metric.json
  ...same, plus `precipitation`, with NO unit parameters (API defaults)

real_multi_location.json
  latitude=39.74,41.88,40.71  longitude=-104.99,-87.63,-74.01
  hourly=wind_speed_10m,wind_gusts_10m,rain,showers,snowfall
  timezone=UTC  forecast_days=2
  wind_speed_unit=mph  precipitation_unit=inch
```

Fairbanks was chosen solely because its forecast contained real snowfall,
which is what makes the unit question answerable from live data.

### What these two files prove

This is the milestone's explicit acceptance criterion, so the evidence is
recorded rather than summarised.

**Returned unit metadata**

| Variable | Default (`real_snowfall_metric`) | With `precipitation_unit=inch` / `wind_speed_unit=mph` |
|---|---|---|
| `wind_speed_10m` | `km/h` | `mp/h` — note the slash, not `mph` |
| `wind_gusts_10m` | `km/h` | `mp/h` |
| `rain`, `showers` | `mm` | `inch` |
| `snowfall` | **`cm`** | **`inch`** |
| `precipitation` | `mm` | `inch` |

**Finding 1 — the inch figure is a depth conversion, not a different quantity.**
For every hour present in both captures, `snowfall_cm / snowfall_inch ≈ 2.54`
(2.500–2.545, the spread being the API's 2–3 significant-figure rounding).
2.54 cm per inch is the plain length conversion, so requesting inches returns
the same physical quantity in different units.

**Finding 2 — `snowfall` is snow DEPTH, not liquid-water equivalent.**
In every snowy hour, `snowfall_cm / precipitation_mm` was **exactly 0.700**:

| Hour (UTC) | `snowfall` cm | `snowfall` inch | `precipitation` mm | cm/inch | cm/mm |
|---|---|---|---|---|---|
| 2026-10-29T11:00 | 0.14 | 0.0550 | 0.2 | 2.545 | 0.700 |
| 2026-10-29T12:00 | 0.49 | 0.1930 | 0.7 | 2.539 | 0.700 |
| 2026-10-29T13:00 | 0.21 | 0.0830 | 0.3 | 2.530 | 0.700 |
| 2026-10-29T15:00 | 0.07 | 0.0280 | 0.1 | 2.500 | 0.700 |
| 2026-10-29T16:00 | 0.07 | 0.0280 | 0.1 | 2.500 | 0.700 |

A constant 0.7 cm of snow per 1 mm of liquid is Open-Meteo's documented fixed
**7:1 snow-to-liquid ratio**. If `snowfall` were a liquid-water equivalent the
ratio would have been 0.1 (1 mm = 0.1 cm). It is not.

**Conclusion.** Requesting `precipitation_unit=inch` returns snowfall as
**inches of snow depth per hour** — exactly the unit the assessment's snow
thresholds (0.5 / 1.0 / 2.0 / 3.0 in/hr) are expressed in. **No conversion is
required on the happy path.**

Conversions are implemented anyway and driven strictly by the `hourly_units`
the response declares, so if the provider ever ignores or changes a unit
parameter the adapter converts correctly instead of misclassifying silently.
An unrecognised unit raises `InvalidProviderResponseError` rather than being
guessed at. Had we assumed liquid equivalent, snow risk would have been
under-reported by a factor of seven.

**Finding 3 — multi-location responses are a JSON array, and coordinates are
snapped to the model grid.** `real_multi_location.json` is a list of three
objects in request order. Requested `39.74,-104.99` came back as
`39.746895,-104.987076`, so forecasts must be associated with checkpoints
**by index**, never by matching coordinates back.

---

## `openmeteo/synthetic_*.json` — hand-written

Not provider output. Written to exercise paths real responses rarely contain.

| File | Purpose |
|---|---|
| `synthetic_boundaries.json` | Wind/rain/snow sitting exactly on every risk threshold |
| `synthetic_boundaries_metric.json` | The *same* conditions in `km/h` / `mm` / `cm`, so the conversion is proved by equivalence rather than asserted |
| `synthetic_missing_values.json` | `null` readings — must become `UNKNOWN`, never `0.0` |
| `synthetic_unknown_units.json` | An unrecognised unit — must raise, never guess |
| `synthetic_malformed.json` | Missing `hourly` / `hourly_units` entirely |
| `synthetic_length_mismatch.json` | A column shorter than `hourly.time` |

---

## `tomtom/synthetic_*.json` — hand-written

**No genuine TomTom response is included: no API key was available for this
milestone.** These are modelled on the documented response schema
(docs.tomtom.com, checked 2026-10-28) and are explicitly *not* presented as
real provider output.

| File | Purpose |
|---|---|
| `synthetic_geocode_success.json` | One result with `position` and `address.freeformAddress` |
| `synthetic_geocode_no_results.json` | Empty `results` — must raise `GeocodingNoResultsError` |
| `synthetic_geocode_malformed.json` | Result with no `position` |
| `synthetic_route_three_alternatives.json` | Three distinct routes, different geometry and durations |
| `synthetic_route_two_alternatives.json` | Fewer than three — must report two, never pad to three |
| `synthetic_route_duplicate_alternatives.json` | Two identical routes plus one distinct — de-duplication |
| `synthetic_route_two_legs.json` | Multi-leg route carrying genuine per-leg timings |
| `synthetic_route_encoded_polyline.json` | `encodedPolyline` representation, decoded via the domain decoder |
| `synthetic_route_empty.json` | No routes — must raise `RoutingNoRoutesError` |
| `synthetic_route_malformed.json` | Non-numeric `lengthInMeters` |

### Consequence of having no real TomTom fixture

The adapter is verified against the documented schema, not against observed
output. Field names, the `results`/`routes` shapes and the `maxAlternatives`
behaviour come from documentation. Before relying on this in production, a
single live call should be recorded with
`TOMTOM_API_KEY=... pytest -m live` and saved here as `real_*.json`. Until
that happens, this limitation stands and is not claimed to be resolved.

---

## Regenerating

Synthetic fixtures: `python scripts/make_fixtures.py` from `backend/`.

The `real_*` files are **not** regenerated by that script. Re-capturing them
would change the data a passing test depends on and would silently move the
evidence this document records.
