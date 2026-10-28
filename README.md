# Weather-Aware Truck Routing

Helps a truck driver choose the safest route by combining **weather**, **cargo
load weight** and **travel time**. The user enters an origin, a destination, a
departure time, a load weight and a checkpoint interval; the app generates
route alternatives, samples the forecast at the truck's *estimated arrival
time* at each checkpoint, classifies the risk, and recommends the safest
option.

**Stack:** React + TypeScript (Vite) · Django REST Framework (Python 3.14)

---

## Status

| Milestone | Scope | State |
|---|---|---|
| **1** | Repository foundation + deterministic domain core | ✅ **Complete** |
| **2** | Provider adapters (routing, geocoding, weather) | ✅ **Complete** |
| **3** | Orchestration + `/api/v1/route-analysis` endpoint | ✅ **Complete** |
| 4 | Frontend shell + interactive map | Not started |
| 5 | Route comparison panel + recommendation UX | Not started |
| 6 | Corridor heatmap + 0–48 h forecast slider | Not started |
| 7 | Hardening (failure paths, a11y, performance) | Not started |
| 8 | Deployment + walkthrough | Not started |
| 9 | *Optional:* AI route rationale | Not started |

Milestone 1 delivered the scoring engine the assessment weights most heavily —
risk classification, segment-mile aggregation and route ranking — as a pure,
fully tested Python package with **no external dependencies at all**.

Milestone 2 added the provider layer: TomTom geocoding and truck routing,
Open-Meteo hourly forecasts, and deterministic offline fixture providers.

Milestone 3 adds the REST API and the orchestration service that joins them:
`POST /api/v1/route-analysis` runs the whole workflow and returns a ranked,
explainable result.

**No API key is required to run or test anything in this repository.** The
defaults are the offline fixture providers plus Open-Meteo (which needs no
key), and the entire test suite runs with no network access.

---

## Quick start

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# Run the test suite with the domain coverage report
pytest --cov --cov-report=term-missing

# Django system checks
python manage.py check

# Development server
python manage.py runserver
# -> http://127.0.0.1:8000/api/v1/health
```

Try the endpoint (PowerShell):

```powershell
$body = @{
  origin = "Denver, CO"; destination = "Chicago, IL"
  departure_at = "2026-11-02T06:00:00"; departure_timezone = "America/Denver"
  load_weight_lb = 42000; checkpoint_interval_miles = 50
} | ConvertTo-Json

Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/route-analysis `
  -Method Post -Body $body -ContentType "application/json"
```

This works with **no credentials**: the defaults are the offline fixture
providers for geocoding and routing, plus Open-Meteo for weather (no key).
To use real TomTom routing, set `TOMTOM_API_KEY` and switch the providers —
see [.env.example](.env.example):

```powershell
$env:TOMTOM_API_KEY  = "..."
$env:ROUTING_PROVIDER = "tomtom"
$env:GEOCODING_PROVIDER = "tomtom"
python manage.py runserver
```

### Frontend

```powershell
cd frontend
npm install

npm run dev          # development server on http://localhost:5173
npm test             # Vitest, single run
npm run test:watch   # Vitest, watch mode
npm run typecheck    # TypeScript, no emit
npm run build        # production build
```

Neither command needs an API key, a database or a network connection.

---

## API

Two endpoints. No authentication, no accounts, no database — the service is
stateless, and two identical requests produce identical output.

### `GET /api/v1/health`

Liveness, plus which providers are configured. Reports whether a credential is
*present*, never any part of its value.

### `POST /api/v1/route-analysis`

```jsonc
{
  "origin": "Denver, CO",
  "destination": "Chicago, IL",

  // Either an explicit offset...
  "departure_at": "2026-11-02T06:00:00-07:00",

  // ...or local wall-clock time plus an IANA zone (preferred: it carries
  // the daylight-saving rules, which a fixed offset cannot).
  // "departure_at": "2026-11-02T06:00:00",
  // "departure_timezone": "America/Denver",

  "load_weight_lb": 42000,           // cargo weight, NOT gross vehicle weight
  "checkpoint_interval_miles": 50,   // 10 | 25 | 50
  "forecast_offset_hours": 0         // optional, 0–48: leave this much later
}
```

**On timezones.** A naive `departure_at` without `departure_timezone` is
rejected rather than guessed — see [D30](docs/decisions.md). Denver is
`-06:00` on 2026‑11‑01 and `-07:00` on 2026‑11‑02, so a client-computed
offset is an hour out across that boundary and every forecast with it. Send
the zone name and let the server resolve it. Ambiguous and nonexistent local
times (the two DST edges) are resolved to a documented choice and flagged in
`warnings`.

**On `forecast_offset_hours`.** This shifts the *departure*, re-running
routing, ETAs, weather and ranking — it can change the recommendation. It is
**not** the 0–48 h corridor heatmap slider, which is a client-side display
control arriving in Milestone 6. See [D28](docs/decisions.md).

#### Response shape

```jsonc
{
  "request":   { /* normalised inputs + effective_departure_at (+ _local echoes) */ },
  "origin":    { "label": "...", "latitude": 39.7, "longitude": -105.0, "confidence": 1.0 },
  "destination": { /* same */ },

  "recommended_route_id": "tomtom-0",   // null when no route is eligible
  "recommendation_reason": "…has the fewest Severe miles.",

  "routes": [                            // ranked; ineligible ones included
    {
      "route_id": "tomtom-0",
      "rank": 1,
      "is_recommended": true,
      "eligible": true,
      "ineligibility_reasons": [],
      "summary": { "distance_miles": 1004.2, "duration_seconds": 50066,
                   "arrival_at": "…", "eta_source": "distance_proportional" },
      "metrics": { "severe_miles": 0.0, "high_miles": 12.5, "average_risk": 0.61,
                   "no_travel_miles": 0.0, "unknown_miles": 0.0,
                   "coverage_pct": 100.0, "blocked": false },
      "geometry": [[39.74, -104.99], …],       // simplified for display
      "geometry_detail": { "returned_points": 1425, "source_points": 10759 },
      "checkpoints": [ { "eta": "…", "weather": {…}, "risk": {…} } ]
    }
  ],
  "warnings": [ { "code": "ETA_ESTIMATED", "message": "…", "route_id": "…" } ],
  "meta": { "providers": {…}, "risk_levels": [...], "elapsed_ms": 412.0 }
}
```

Every timestamp is UTC with an explicit offset. Risk levels are a fixed enum
(`LOW` · `MODERATE` · `HIGH` · `SEVERE` · `NO_TRAVEL` · `UNKNOWN`), echoed in
`meta.risk_levels`.

**Geometry is simplified for the wire.** Three real TomTom routes carry
~39,000 vertices (~1 MB of JSON); Ramer–Douglas–Peucker at an ~8 m tolerance
reduces that to ~5,400 points (138 KB) with 0.015% length error.
`geometry_detail` reports both counts. **Analysis always runs on the full
geometry** — only the payload is reduced.

#### Errors

One envelope for every failure:

```jsonc
{ "error": { "code": "LOCATION_AMBIGUOUS", "message": "…",
             "field": "origin", "details": null } }
```

| Situation | Status | Code |
|---|---|---|
| Invalid request body | 400 | `INVALID_REQUEST` (+ per-field `details`) |
| Address matched nothing | 400 | `GEOCODING_NO_RESULTS` |
| Address matched, but not confidently | 400 | `LOCATION_AMBIGUOUS` |
| No route exists between the points | 422 | `ROUTING_NO_ROUTES` |
| Provider rate-limited us | 429 | `PROVIDER_RATE_LIMITED` (+ `Retry-After`) |
| Provider timed out | 504 | `PROVIDER_TIMEOUT` |
| Provider down / bad response | 502 | `PROVIDER_UNAVAILABLE`, `PROVIDER_INVALID_RESPONSE` |
| Anything unexpected | 500 | `INTERNAL_ERROR` (no internals leaked) |

**A trip with no safe route is HTTP 200**, not an error: `recommended_route_id`
is `null`, `recommendation_reason` explains why, and every blocked route is
still returned with its `ineligibility_reasons`. Returning 5xx would make a
blizzard indistinguishable from an outage.

---

## How the analysis works

```
geocode → route alternatives → checkpoints → weather → risk → rank
```

1. **Geocode** both endpoints in parallel, then apply the confidence policy (D29).
2. **Route**: one truck-mode call for up to three alternatives. Cargo weight is
   never sent as a vehicle weight (D16).
3. **Checkpoints** at the requested interval, placed by cumulative distance.
   A route long enough to exceed 300 checkpoints has its interval coarsened,
   with a warning, rather than timing out.
4. **Weather**: one batched request covering every checkpoint on every route.
   Near-identical coordinates collapse into a single lookup, so overlapping
   alternatives cost one call, not three. Each checkpoint takes the forecast
   nearest its own ETA (D19).
5. **Risk and ranking** are computed entirely by the domain package. The
   orchestration layer contains no threshold and no ranking rule; architecture
   tests fail the build if that changes.

### Known limitations — stated plainly

- **ETAs are driving time only.** No hours-of-service breaks, no fuel or rest
  stops, no dispatch scheduling. Where the provider gives no per-segment
  timings (every single-leg route — i.e. all of them today), ETAs assume a
  constant average speed and say so via `eta_source` and an `ETA_ESTIMATED`
  warning.
- **Traffic is requested from the routing provider but not modelled by us.**
  Departure-time traffic is whatever the provider returned at analysis time.
- **Forecasts are hourly.** Matching an ETA to the nearest hour does not make
  it minute-accurate, and nothing here presents it as such.
- **Missing weather is never treated as good weather.** It becomes `UNKNOWN`,
  is tracked as `unknown_miles`, excluded from the risk average, and reported
  as `coverage_pct`. A route whose coverage falls below the threshold is
  **ineligible** — ignorance cannot win a recommendation.
- **No Travel conditions block a route entirely.** It is still returned and
  drawn, with reasons, but never recommended while an eligible route exists.
  If every route is blocked, the recommendation is `null`.

---

## Repository layout

```
.
├─ backend/
│  ├─ config/               Django project: settings, URLs, WSGI/ASGI
│  └─ apps/routing/
│     ├─ domain/            ← PURE. stdlib only. no Django, no I/O, no clock
│     │  ├─ models.py          value objects: Coordinate, Checkpoint, ...
│     │  ├─ geo.py             haversine, cumulative measure, interpolation
│     │  ├─ checkpoints.py     distance-based sampling + ETA assignment
│     │  ├─ risk.py            thresholds, cargo overrides, combination
│     │  ├─ aggregation.py     segment attribution, risk miles, coverage
│     │  └─ ranking.py         deterministic comparator + No Travel policy
│     ├─ providers/         ← ALL external I/O
│     │  ├─ base.py            protocols + typed results
│     │  ├─ errors.py          typed provider errors
│     │  ├─ http.py            timeouts, retries, caching, redaction
│     │  ├─ tomtom.py          geocoding + truck routing
│     │  ├─ openmeteo.py       hourly forecasts
│     │  ├─ fixtures.py        deterministic offline providers
│     │  └─ factory.py         selection from settings
│     ├─ services/          analysis.py · errors.py
│     ├─ api/               serializers · views · errors · urls
│     └─ tests/             pytest suite (domain + api)
├─ frontend/
│  └─ src/
│     ├─ features/          trip-form · routes-panel · map · heatmap
│     ├─ components/        shared presentational components
│     ├─ api/  hooks/  lib/  types/
│     └─ test/              Vitest setup
└─ docs/
   ├─ architecture.md       components, data flow, boundaries
   └─ decisions.md          every interpretation and why
```

### The one architectural rule

**`backend/apps/routing/domain/` imports nothing but the Python standard
library.** No Django, no HTTP client, no environment variables, no
`datetime.now()`, no randomness. Everything in it is a pure transformation of
value objects.

That is what makes the scoring logic provable in isolation, fast to test
(263 tests in ~1.3 s), and completely independent of which routing or weather
provider sits behind it. Two tests in
[`test_pipeline.py`](backend/apps/routing/tests/domain/test_pipeline.py) parse
the domain package's own AST to enforce the boundary, so it cannot rot
silently.

---

## Assessment interpretation

The assessment leaves several things genuinely ambiguous. Each was resolved
explicitly rather than silently, and each is documented with its rationale in
**[docs/decisions.md](docs/decisions.md)**. In summary:

| Question the spec leaves open | Decision |
|---|---|
| Sustained wind or gusts? | **Sustained.** The 25/35/45/55 ladder matches the NWS sustained-wind advisory scale. Gusts are carried for display and never classified. |
| Shared boundaries (0.25 in/hr is in two columns) | Resolve **upward**, to the more severe band. Bands are lower-bound inclusive. |
| Top of the scale | Honour the literal operators: wind `>= 55` is No Travel; rain is No Travel only `> 1.00`; snow only `> 3.0`. So rain of exactly 1.00 is Severe. |
| Gap values (34.5 mph) | Covered by the lower-bound-inclusive convention — 34.5 is Moderate. |
| Combining wind + rain + snow | **Maximum severity**, after the cargo override. No additive compounding. |
| Points → "Severe miles" | **Forward attribution**: each checkpoint governs the stretch ahead of it. Segment miles sum to exactly the route distance. |
| "Lowest average risk" | **Distance-weighted**, not a mean over checkpoints — otherwise the checkpoint interval could flip the recommendation. |
| Missing forecast data | `UNKNOWN`, never `LOW`. Tracked as unknown miles, excluded from the average, reported as a coverage percentage. |
| Routes containing No Travel | **Blocked**: displayed in full, never recommended while an eligible route exists. If every route is blocked, the recommendation is `null`. |
| Ties after all four criteria | Fewest unknown miles → provider order → route id. Guarantees a **total order**. |

---

## Testing

```powershell
cd backend
pytest --cov --cov-report=term-missing
```

789 tests, **100% statement coverage of the domain, provider, service and
API packages** (one unreachable branch arc remains, marked and explained in
the code). No test requires an API key, network access or a live service:
every provider interaction is mocked with `respx`, and every payload comes
from `tests/fixtures`.

The API tests force the offline fixture providers, and one of them asserts
that a full analysis makes **zero outbound HTTP requests**.

### Live provider checks — opt-in, off by default

```powershell
cd backend
pytest -m live                                 # Open-Meteo only; no key needed
$env:TOMTOM_API_KEY = "..."; pytest -m live    # adds the TomTom checks
```

These are the only tests that touch the network. `pyproject.toml` sets
`-m "not live"` by default, so an ordinary `pytest` run can never fire them
accidentally. Their job is to catch provider drift — a renamed field, a
changed unit — that mocked tests cannot see by construction.

### Fixture provenance

[`backend/apps/routing/tests/fixtures/PROVENANCE.md`](backend/apps/routing/tests/fixtures/PROVENANCE.md)
records, for every fixture, whether it is a **genuine captured provider
response** or **synthetic data**, how it was captured, and what it
demonstrates. Synthetic data is never presented as real provider output, and
captured forecasts are never presented as current weather.

---

## Providers

| Concern | Provider | Credentials |
|---|---|---|
| Geocoding | TomTom Search v2, or offline fixtures | `TOMTOM_API_KEY` (optional) |
| Truck routing | TomTom Routing v1, or offline fixtures | `TOMTOM_API_KEY` (optional) |
| Weather | Open-Meteo hourly forecast | **None required** |

Selected via `ROUTING_PROVIDER`, `GEOCODING_PROVIDER` and `WEATHER_PROVIDER`
(see [.env.example](.env.example)). All three default to a configuration that
needs no credentials.

Two provider behaviours are worth knowing about before reading the code; both
are explained in full in [docs/decisions.md](docs/decisions.md):

- **Cargo weight is never sent to the routing API.** The assessment supplies
  *cargo load weight*; TomTom's `vehicleWeight` means *gross vehicle weight*.
  They are not the same number, and conflating them could route a heavy truck
  over a bridge it must not cross. The limitation this leaves is documented
  rather than guessed around (D16).
- **Open-Meteo's `snowfall` is snow depth, not liquid equivalent** — verified
  against live responses, not assumed (D17).

---

## Licence and credits

Built as a take-home assessment. Provider terms and attribution requirements
are recorded in [docs/decisions.md](docs/decisions.md). Weather data by
[Open-Meteo](https://open-meteo.com/), used under CC-BY 4.0.
