# Architecture

## Goals that shaped the design

1. **The scoring logic must be provable.** Risk classification, mileage
   aggregation and route ranking carry the most assessment weight and are the
   easiest things to get subtly wrong. They are isolated in a pure package
   with no dependencies, so they can be tested exhaustively in milliseconds.
2. **Provider choices must be reversible.** Routing and weather vendors differ
   in quota, availability and terms. Every integration sits behind a protocol
   so swapping one is a settings change, not a refactor.
3. **Failure must be visible, never silent.** A missing forecast must never
   read as good weather. This single principle drives the `UNKNOWN` risk level,
   the unknown-mile accounting, the coverage percentage and the eligibility
   gate.

## Component map

```
┌──────────────────────── Browser (React + TypeScript, Vite) ───────────────┐
│  TripForm ──POST /api/v1/analyze──┐                                       │
│                                   │       ┌─ RouteMap (MapLibre GL)       │
│  TanStack Query cache ◄───────────┘       │   ├ route polylines           │
│      │                                    │   ├ checkpoint markers        │
│      ├─ schema-validated response ────────┤   └ GPU heatmap layer         │
│      └─ corridor frames [hour][point] ────┘                               │
│  RoutesPanel · RiskLegend · TimeSlider (0–48 h)                           │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ typed JSON, validated at both ends
┌──────────────────────────────▼────────────────────────────────────────────┐
│ Django 6 + DRF                                                            │
│                                                                           │
│  api/           AnalyzeView ──► services/analyze.py (orchestration only)  │
│                                        │                                  │
│         ┌──────────────────────────────┼─────────────────────┐            │
│         ▼                              ▼                     ▼            │
│  providers/  (all I/O)           domain/  (PURE)      services/corridor   │
│   GeocodingProvider               geo.py                                  │
│   RoutingProvider                 checkpoints.py   ← no Django            │
│   WeatherProvider                 risk.py            no network           │
│   FixtureProvider                 aggregation.py     no clock             │
│         │                         ranking.py         no randomness        │
│         ▼                                                                 │
│  http.py: timeout · retry+jitter · bounded concurrency · response cache   │
└─────────┬─────────────────────────┬──────────────────────┬────────────────┘
          ▼                         ▼                      ▼
    Geocoding API             Routing API              Weather API
                          (truck + alternatives)    (hourly forecast)
```

**Legend:** `domain/` (Milestone 1) and `providers/` (Milestone 2) exist today.
`services/` and `api/` beyond the health probe arrive in Milestone 3; the
frontend features in Milestones 4–6.

## Provider modules

| Module | Responsibility |
|---|---|
| `base.py` | Protocols (`GeocodingProvider`, `RoutingProvider`, `WeatherProvider`) and the typed results they return. `HourlyForecast.sample_at()` holds the documented nearest-hour selection policy. |
| `errors.py` | Typed error hierarchy, each with a stable `code`. Catching `ProviderError` degrades gracefully without enumerating vendor internals. |
| `http.py` | One shared transport: explicit connect/read timeouts, a bounded retry policy, response caching, and credential redaction — including a logging filter that scrubs httpx's own INFO lines. |
| `tomtom.py` | Geocoding (Search v2) and truck routing (Routing v1), with route de-duplication. |
| `openmeteo.py` | Bulk hourly forecasts, unit normalisation driven by the response's own metadata, coordinate de-duplication and chunking. |
| `fixtures.py` | Deterministic offline providers, so the app runs and the suite passes with no key and no network. |
| `factory.py` | Turns settings into concrete adapters; reports credential *presence* without exposing values. |

### Rules the provider layer follows

- **Adapters translate, they do not decide.** No risk classification, no
  mileage aggregation, no ranking — that logic lives in `domain/` and two
  copies would drift. Enforced by an AST test.
- **Failures are typed.** No bare `httpx` exception escapes; every failure
  mode maps to a `ProviderError` subclass the API layer can render.
- **Transient vs permanent is explicit.** 429 and 5xx are retried with capped
  exponential backoff honouring `Retry-After`; 400/401/403 are not, because
  retrying them only burns quota.
- **Credentials never appear** in a log line, an exception, a `repr`, or a
  cache key.
- **Counts are never padded.** Two routes are reported as two, with a notice.
- **Missing data is never zero.** A `None` reading classifies as UNKNOWN.

## The dependency rule

```
api  ──►  services  ──►  domain
                 │
                 └──►  providers  ──►  (external HTTP)
```

Dependencies point inwards only. `domain/` knows nothing about anything else;
`providers/` know nothing about `domain/`; `services/` is the only layer that
knows both, and its entire job is to translate between them.

Two tests in `tests/domain/test_pipeline.py` parse the domain package's own
AST and fail the build if any module imports `django`, `rest_framework`,
`httpx`, `requests`, `urllib`, `socket`, `os`, `random` or `time`, or if it
calls `datetime.now()` / `utcnow()`. The boundary is enforced, not merely
documented.

## Request flow (Milestone 3 onward)

1. **Validate** — DRF serializer normalises origin, destination, departure
   time, load weight and checkpoint interval.
2. **Geocode** — origin and destination (cached ~30 days by normalised query).
3. **Route** — one truck-routing call requesting alternatives, with the load
   weight passed as a vehicle constraint. Up to three candidates come back with
   geometry and per-leg durations.
4. **Checkpoint** — pure. Walk each route's cumulative distance, emit
   coordinates at every interval multiple plus the destination, assign ETAs.
5. **Weather** — collect every checkpoint across every route, quantise
   `(lat, lon, hour)` to collapse near-duplicates, batch the survivors into
   bulk forecast calls.
6. **Classify and aggregate** — pure. Per-checkpoint risk → cargo override →
   forward segment attribution → per-route metrics.
7. **Rank** — pure, deterministic, total order. Produces the recommendation.
8. **Corridor grid** — sample points along the recommended route, fetch 49
   hourly frames in one bulk call.
9. **Serialise** — typed JSON. The client validates against the schema so any
   drift fails loudly in development rather than rendering `undefined`.

Steps 4, 6 and 7 are the whole of Milestone 1 and run without touching the
network.

## Domain modules

| Module | Responsibility |
|---|---|
| `models.py` | Frozen, slotted value objects and the `RiskLevel` enum. `UNKNOWN` has no severity score, so it cannot be compared or averaged as if it were `LOW`. |
| `geo.py` | Haversine distance, cumulative route measure, coordinate interpolation, segment lookup, encoded-polyline decoding. |
| `checkpoints.py` | Distance-based checkpoint placement and ETA assignment, with the provider-timing strategy and its distance-proportional fallback. |
| `risk.py` | Thresholds, per-condition classification, cargo-weight overrides, severity combination, human-readable explanations. |
| `aggregation.py` | Forward segment attribution, risk-mile totals, distance-weighted average risk, coverage accounting. |
| `ranking.py` | The safety gate, the four assessment criteria, deterministic tie-breaks, recommendation selection and its justification. |

## Key mechanisms

### Checkpoints follow distance, not geometry indices

Provider polylines have wildly uneven vertex spacing — dense through
interchanges, sparse across open highway. Sampling by array index would cluster
checkpoints around intersections and leave long stretches unsampled.
`cumulative_distances` builds the along-route measure once; every checkpoint is
then located by binary search into it and interpolated between the two
surrounding vertices.

`test_placement_follows_distance_not_vertex_index` pins this down with a
geometry whose vertices are deliberately clustered: the midpoint checkpoint
must land at latitude 40.5, where index-based sampling would have put it at
40.04.

### Two distance scales, reconciled

The haversine sum over a polyline never exactly equals the provider's
road-following distance. Checkpoints are therefore positioned in the
*provider's* scale — so reported distances run from 0 to exactly
`route.distance_miles` and segment miles sum with no residual — while
coordinates are looked up by converting into the geometry's own measure.

### ETAs prefer real road timing

When the provider supplies per-segment durations, cumulative time is
interpolated within the containing segment, so a checkpoint halfway through a
mountain pass gets the ETA the terrain implies rather than a flat average. The
profile is rescaled so its final value equals the route's headline duration
exactly, reconciling the drift providers routinely have between their own
per-segment numbers and their total. Without segment timings, ETAs fall back to
constant average speed — documented, and reported in the API response so it is
never mistaken for the real thing.

### Forward attribution turns points into miles

Checkpoint *i* governs `[d_i, d_(i+1))`: every mile is owned by the conditions
at the point where the driver *enters* it. Segment lengths therefore sum to
exactly the route distance, with no gaps and no double-counting, and the
attribution is causal. The destination owns zero forward miles but is still
classified and displayed — and a No Travel condition there still blocks the
route, which a mileage-only test would miss.

### Distance weighting makes the score interval-independent

Average risk is `Σ(score × miles) / Σ(miles)`, not a mean over checkpoints.
With an unweighted mean, a densely sampled short stretch outvotes a sparsely
sampled long one, so the recommendation could flip based on which interval the
user happened to pick. Weighting removes that coupling.

### Unknown is not Low

A checkpoint with no forecast is `UNKNOWN`. Its miles are tracked separately,
excluded from both sides of the average, and reported as a coverage
percentage. Because an unforecast route would otherwise score a *perfect*
scorecard — zero Severe miles, zero High miles, no average risk — routes below
the coverage threshold are ineligible for recommendation. Ignorance cannot win.

## Technology choices

| Concern | Choice | Reason |
|---|---|---|
| API framework | Django 6.0 + DRF 3.18 | Required stack; DRF serialisers give validation and schema in one place |
| Database | **None** | Nothing is persisted. `django.contrib.auth`, `sessions` and `admin` are not installed either |
| Domain dependencies | **None** (stdlib) | Makes the scoring logic provable and provider-independent |
| Frontend build | Vite 8 + React 19 + TypeScript 7 | Fast builds, strict typing |
| Frontend tests | Vitest 5 + Testing Library 16 | Vite-native, no separate transform pipeline |
| Map (Milestone 4) | MapLibre GL | Native GPU heatmap layer; no access token. Canvas heatmaps stutter when scrubbing a 49-frame slider |

## What is deliberately absent

No authentication, no user accounts, no database schema, no message queue, no
microservices, no Docker requirement. None of them is implied by the
assessment, and each would be surface area to maintain and explain without
improving a single graded outcome.
