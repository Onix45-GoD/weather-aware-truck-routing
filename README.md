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
| **4** | Frontend dashboard: map, routes, checkpoints | ✅ **Complete** |
| 5 | Route comparison polish + onboarding | ✅ **Complete** |
| 6 | Corridor heatmap + 0–48 h forecast slider | ✅ **Complete** |
| 7 | Hardening (failure paths, a11y, performance) | Not started |
| 8 | Deployment + walkthrough | Not started |
| 9 | *Optional:* AI route rationale | Not started |

Milestone 1 delivered the scoring engine the assessment weights most heavily —
risk classification, segment-mile aggregation and route ranking — as a pure,
fully tested Python package with **no external dependencies at all**.

Milestone 2 added the provider layer: TomTom geocoding and truck routing,
Open-Meteo hourly forecasts, and deterministic offline fixture providers.

Milestone 3 added the REST API and the orchestration service that joins them:
`POST /api/v1/route-analysis` runs the whole workflow and returns a ranked,
explainable result.

Milestone 4 adds the React dashboard: an interactive MapLibre map with
risk-coloured routes, route comparison cards, a checkpoint table and detail
panel, and a weather profile — all driven by real analysis results.

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
npm run lint         # oxlint
npm run build        # production build
```

The frontend tests need no API key, database or network connection — the API
client and MapLibre are both mocked.

### Running the whole thing

Two terminals. The backend serves the API; the frontend talks only to it.

```powershell
# Terminal 1
cd backend; .\.venv\Scripts\Activate.ps1; python manage.py runserver
# Terminal 2
cd frontend; npm run dev        # http://localhost:5173
```

With no configuration this uses the offline fixture providers plus Open-Meteo.
For real TomTom routing, put your key in `backend/.env` (gitignored):

```ini
TOMTOM_API_KEY=your-key-here
ROUTING_PROVIDER=tomtom
GEOCODING_PROVIDER=tomtom
```

### Frontend environment variables

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Django API origin |
| `VITE_MAP_STYLE_URL` | CARTO Voyager | Replaces the default **Streets** basemap style |

⚠️ **Never put a provider credential in a `VITE_*` variable.** They are
compiled into the JavaScript bundle and are readable by anyone who opens the
site. TomTom and Open-Meteo are called by the Django server, never by the
browser — a test asserts the frontend request carries no credential.

---

## API

Four endpoints. No authentication, no accounts, no database — the service
is stateless, and two identical requests produce identical output.

### `GET /api/v1/health`

Liveness, plus which providers are configured. Reports whether a credential is
*present*, never any part of its value.

### `GET /api/v1/places?q=`

Type-ahead suggestions for the origin and destination fields, from the
same geocoder the analysis uses (TomTom fuzzy search with `typeahead=true`,
geographies and point addresses; the offline fixture gazetteer otherwise).
Under two characters returns an empty list, not an error; at most six
results, in the provider's order; cached with the geocoding TTL. Free text
still submits — suggestions are an accelerator, never a gate.

### `POST /api/v1/corridor-forecast`

The 0–48 h corridor view, as data. The request is the selected route's
checkpoints sent back exactly as the analysis emitted them — index, position,
distance — plus the analysis's `effective_departure_at` as `reference_at`,
the cargo weight, and (display only) the trip timezone. **Geometry is not
resent**; the corridor is sampled at checkpoints and nothing else.

```jsonc
{
  "reference_at": "2026-11-02T13:00:00+00:00",   // analysis.request.effective_departure_at
  "load_weight_lb": 40000,
  "route_id": "tomtom-0",
  "timezone": "America/Denver",
  "checkpoints": [{ "index": 0, "latitude": 39.74, "longitude": -104.99,
                    "distance_from_origin_miles": 0 }, ...]
}
```

The response is **49 hourly frames**, `hour` 0…48. Frame *h* is the instant
`reference_at + h hours` **at every checkpoint at once** — one moment across
the whole route, which is what scrubbing a forecast means. Each frame holds
every checkpoint's `weather` and `risk` in the same shapes the analysis uses,
plus the domain's risk-mile `summary` for that hour (`low_miles` …
`unknown_miles`, `coverage_pct`, `max_risk`). The measurements are the same
Open-Meteo hourly series the analysis used, through the same adapter and
the same `assess_route` / `summarise_route` — cargo-weight overrides
included. Nothing is interpolated: the step is one hour because the data is.

Honesty fields: `available` is false, and every checkpoint UNKNOWN, for an
hour the provider did not cover (`unavailable_reason`:
`outside_provider_horizon` or `no_measurements`); `forecast_window` says what
the provider actually returned; `warnings` carries `FORECAST_HORIZON` and
`INCOMPLETE_FORECAST`. A frame outside the horizon is still returned so the
slider can show the gap — it is never filled with the nearest hour.

This endpoint is **display only**. It cannot change the departure, the ETAs
or the recommendation; it is a second view of the same forecast, not a
second analysis ([D28](docs/decisions.md), [D31](docs/decisions.md)).
Responses are gzipped (`GZipMiddleware`): ~49 × N checkpoints of repetitive
JSON compresses to tens of KB.

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

**On `forecast_offset_hours`.** An API-only field: the form no longer exposes
it, because a second 0–48 h slider next to the corridor timeline was
confusing. It shifts the *departure*, re-running
routing, ETAs, weather and ranking — it can change the recommendation. It is
**not** the 0–48 h corridor forecast slider, which is a display-only
control over frames fetched once per route — see *Corridor forecast* under
*Map*, and [D28](docs/decisions.md) / [D31](docs/decisions.md).

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

## Frontend

A dark dashboard built with **React 19 · TypeScript · Vite 8 · Tailwind CSS 4
· Material UI 9 · MapLibre GL 6**.

### How Tailwind and MUI coexist

The two are given separate jobs, so they never fight over the same property:

| | Owns |
|---|---|
| **Tailwind** | Layout — grid, flex, spacing, sizing, breakpoints, overflow |
| **MUI** | Appearance — colours, radii, typography, component states |

The glue is CSS cascade layers. `src/styles/index.css` declares the order up
front:

```css
@layer theme, base, mui, vendor, components, utilities;
```

and `StyledEngineProvider enableCssLayer` puts MUI's styles into the `mui`
layer. Because `utilities` is declared after `mui`, a Tailwind class beats a
themed MUI style **without `!important`** — which is the usual, miserable
alternative. Tailwind v4 needs no `tailwind.config.js`: tokens live in
`@theme` in that same stylesheet, and they are the same values the MUI theme
uses.

MapLibre's own stylesheet is imported into the `vendor` layer from
`src/styles/map.css`, never unlayered. Unlayered CSS outranks every layer, so
left as shipped its `.maplibregl-map { position: relative }` would override
the Tailwind `absolute inset-0` that sizes the map container and collapse it
to zero height — silently. The layer is deliberately not named `components`:
Tailwind v4 treats `@layer components` as a v3 compatibility block and drops
any rule whose class never appears in scanned source, which would discard the
entire vendor sheet.

### Responsive behaviour

| Viewport | Layout |
|---|---|
| **≥1280 px** | Three columns: trip form · map · route alternatives |
| **1024–1280 px** | Trip form and map side by side; alternatives drop below |
| **<1024 px** | Single column; trip form moves into a drawer behind a **Trip** button; the map keeps full width |

Grid children use `minmax(0, 1fr)` and `min-w-0` throughout. Without those a
long route label or a wide table forces horizontal overflow on the whole
page — a grid item's default `min-width: auto` refuses to shrink below its
content.

### Map

MapLibre GL with keyless CARTO basemaps (attribution is shown, as their
terms require). **Streets** (Voyager) is the default — a driver needs to
read road numbers and town names, and the risk colours separate better on a
light ground — with **Dark** one click away. Switching calls `setStyle`,
which discards every layer we added, so the route layers are re-created on
each `style.load` rather than only once. The map is **code-split**: it is
~1 MB of the bundle, and making the first paint wait for it would block the
trip form, which is the only thing a user can act on before an analysis
exists.

- Route geometry comes from the API — never reconstructed from checkpoints.
- Routes are drawn as thin dashed lines so the basemap's roads stay
  readable underneath; the selected route carries a dotted risk line on
  top, coloured per-segment by checkpoint risk using forward attribution:
  a checkpoint governs the road *ahead* of it.
- Checkpoints pulse gently (one `requestAnimationFrame` loop driving two
  paint properties; paused with the tab, off under `prefers-reduced-motion`).
- Unselected alternatives recede; ineligible ones are drawn in the No-Travel
  colour so "blocked" reads differently from "not chosen".
- If the basemap fails to load, a banner says so and the rest of the
  dashboard keeps working.
- **Route comparison and detail.** A table lists every route in rank order
  with the cell that decided each row outlined — taken from the backend's
  `separated_from_previous_by`, not recomputed — and the detail panel for
  the selected route says *why* it sits where it does, with both values
  (“ranked 2nd: all three risk criteria tie; longer drive, +1h 49m”), a
  miles-by-level bar, the drive window and the worst checkpoints as jump
  targets.
- **First visit.** A guide explains the three steps, the colours and each
  overlay, with a *Try an example trip* button that runs a real Denver →
  Chicago analysis and fills the form. *Got it* hides it per browser; the
  header's help button brings it back as a dialog. When any provider is the
  offline fixture, a banner says the routes and weather are synthetic.
- **Click a checkpoint** (on the map or in the table) and a popup opens on
  the map at that point: ETA, the three measurements and the level the
  recommendation was computed from, and a clickable 49-cell strip of that
  checkpoint's risk over the next 48 hours. Picking a cell moves the
  timeline, so popup, band and panel never disagree. Closing the popup
  clears the selection.
- The panel under the table shows the same checkpoint in full: ETA
  conditions, the backend's explanation, and an hourly table of the next
  48 hours at that spot (dashes and *No data* for uncovered hours, never
  zeros).

### Corridor forecast (0–48 h)

Under the map, a **Corridor forecast** timeline scrubs the selected route
through the 48 hours after departure. It is a display control: it changes
what the map band, the hour strip and the checkpoint panel show, and
nothing else — the route, ETAs, ranking and recommendation were computed
once by the analysis and are not touched. The caption says so.

- **Time semantics.** Position +*h* is `effective_departure_at + h hours`,
  shown as an absolute timestamp in the trip's timezone (e.g. `Mon 2 Nov,
  6:00 PM MST`). Hour +0 is departure. The step is one hour because
  Open-Meteo's series is hourly; no finer step is offered because it would
  have to be invented.
- **What is drawn.** A wide translucent **band** along the selected route and
  a **halo** on every checkpoint, both coloured by that hour's risk level.
  The band is the route's geometry split at its checkpoints with forward
  attribution (a checkpoint governs the road ahead of it) — the same rule the
  ETA risk line uses. The thin dotted risk line and the checkpoint dots stay
  as they were: they are the **at-ETA** view, and the legend labels both.
- **What it is not.** This is a checkpoint-sampled visualisation, not a
  radar field. Forty-odd samples at 10/25/50-mile spacing are what the
  analysis has; the band shows exactly that resolution and does not pretend
  to more.
- **The hour strip.** One cell per hour, coloured by the worst risk anywhere
  on the route at that hour — a legend-coloured timeline. Hours the provider
  did not cover are hatched, counted (`3 of 49 hours unavailable`) and shown
  as unknown; playback skips them.
- **Playback.** Play steps through *available* hours only, from data already
  in memory — no request per frame, no interpolation. Dragging the slider
  pauses it; it stops at the last available hour; reset returns to +0.
  Under `prefers-reduced-motion` the cadence slows. Timers are cleared on
  unmount.
- **Checkpoint panel and popup.** Selecting a checkpoint shows its ETA block
  (what the recommendation is computed from) and the hourly table of the
  next 48 hours there; the map popup shows the compact version. Moving the
  slider highlights the matching hour without losing the selection.
- **Data flow.** One `POST /api/v1/corridor-forecast` per selected route,
  cached in the hook per analysis, so switching back to a route is free and
  changing the hour never touches the network. A route change aborts an
  in-flight request; a late response can never land on a newer selection.

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

**Backend:** 862 tests, **100% statement coverage of the domain, provider,
service and API packages** (one unreachable branch arc remains, marked and explained in
the code). No test requires an API key, network access or a live service:
every provider interaction is mocked with `respx`, and every payload comes
from `tests/fixtures`.

The API tests force the offline fixture providers, and one of them asserts
that a full analysis makes **zero outbound HTTP requests**. Another asserts
the suite never reads a developer's local `.env`, so results are identical on
a laptop with credentials and on CI without them.

**Frontend:** 162 tests (Vitest + Testing Library), covering form validation
and timezone serialisation, the request lifecycle including stale-response
races, one/two/three alternatives, null recommendations, missing weather,
error mapping, map lifecycle and failure, basemap and overlay switching,
the checkpoint panel and map popup, place autocomplete, and the corridor timeline — slider labels and
timestamps, keyboard control, loading/error/unavailable states, playback
(skipping uncovered hours, pausing on input, timer cleanup), request
caching and abort/stale protection, and that moving the hour never re-runs
the analysis. The API client and MapLibre are mocked; no test touches the
network. Corridor fixtures are synthetic and say so.

```powershell
cd frontend
npm test
```

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
