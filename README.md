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
| 2 | Provider adapters (routing, geocoding, weather) | Not started |
| 3 | Orchestration + `/api/v1/analyze` endpoint | Not started |
| 4 | Frontend shell + interactive map | Not started |
| 5 | Route comparison panel + recommendation UX | Not started |
| 6 | Corridor heatmap + 0–48 h forecast slider | Not started |
| 7 | Hardening (failure paths, a11y, performance) | Not started |
| 8 | Deployment + walkthrough | Not started |
| 9 | *Optional:* AI route rationale | Not started |

Milestone 1 delivers the scoring engine the assessment weights most heavily —
risk classification, segment-mile aggregation and route ranking — as a pure,
fully tested Python package with **no external dependencies at all**. No API
key is required to run or test anything in this repository today.

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

# Development server (health probe only in Milestone 1)
python manage.py runserver
# -> http://127.0.0.1:8000/api/v1/health
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
│     ├─ api/               DRF serializers and views      (Milestone 3)
│     ├─ providers/         routing / geocoding / weather  (Milestone 2)
│     ├─ services/          orchestration                  (Milestone 3)
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

263 tests, **100% statement and branch coverage of the domain package**. Every
test uses synthetic inputs: none requires an API key, network access or a live
external service.

Coverage is measured over `apps/routing/domain` only — the part that holds the
logic worth proving. Measuring the Django scaffolding alongside it would
inflate the number without adding confidence.

---

## Licence and credits

Built as a take-home assessment. Routing, geocoding and weather providers are
integrated in Milestone 2; provider terms and attribution requirements are
recorded in [docs/decisions.md](docs/decisions.md).
