"""Capture genuine TomTom responses as test fixtures.

Run from `backend/` with a key in the environment:

    # PowerShell
    $env:TOMTOM_API_KEY = "..."; python scripts/capture_tomtom_fixtures.py

    # bash
    TOMTOM_API_KEY=... python scripts/capture_tomtom_fixtures.py

Why this exists
---------------
Milestone 2 shipped without a TomTom key, so every TomTom fixture is
synthetic and the adapter is verified against documented schema rather than
observed output (docs/decisions.md D26). This script closes that gap in one
command whenever a key becomes available.

How it captures
---------------
It drives the **real adapter** and records what came back, using an httpx
response event hook. The adapter builds the request, so the captured body is
by construction exactly what the production code path receives -- there is no
second copy of the URL or parameter construction here that could drift away
from the adapter and produce a fixture the adapter never actually sees.

Safety
------
* The API key is read from the environment and never printed, never written to
  a fixture, and never written to the provenance record.
* Only **response bodies** are stored. Request URLs are not, because the key
  travels as a query parameter.
* Every serialised body is scanned for the key before it is written. If the
  key appears anywhere in the output, the script aborts without writing.
* Nothing about the vehicle is sent. The adapter's cargo-weight rule (D16)
  applies here unchanged, because this *is* the adapter.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import UTC, datetime, timedelta

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import django  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
django.setup()

from apps.routing.domain.models import Coordinate  # noqa: E402
from apps.routing.providers.http import ProviderHttpClient, redact  # noqa: E402
from apps.routing.providers.tomtom import (  # noqa: E402
    TomTomGeocodingProvider,
    TomTomRoutingProvider,
)

FIXTURES = (
    pathlib.Path(__file__).resolve().parent.parent
    / "apps/routing/tests/fixtures/tomtom"
)

DENVER = Coordinate(latitude=39.7392, longitude=-104.9903)
CHICAGO = Coordinate(latitude=41.8781, longitude=-87.6298)


class _Recorder:
    """Records response bodies as the adapter receives them."""

    def __init__(self) -> None:
        self.bodies: list[object] = []
        self.urls: list[str] = []

    def __call__(self, response: httpx.Response) -> None:
        response.read()
        self.urls.append(redact(str(response.request.url)))
        try:
            self.bodies.append(response.json())
        except ValueError:  # pragma: no cover - dev script
            self.bodies.append(None)

    def client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0),
            event_hooks={"response": [self]},
            headers={"Accept": "application/json"},
        )


def _write(name: str, payload: object, api_key: str) -> pathlib.Path:
    """Write a fixture, refusing if the credential appears anywhere in it."""
    text = json.dumps(payload, indent=2) + "\n"
    if api_key and api_key in text:
        raise SystemExit(
            f"ABORT: the API key appears inside {name}. Nothing was written."
        )
    path = FIXTURES / name
    path.write_text(text, encoding="utf-8")
    print(f"  wrote {path.name:<44} {path.stat().st_size:>8,} bytes")
    return path


def main() -> int:
    api_key = os.environ.get("TOMTOM_API_KEY", "").strip()
    if not api_key:
        print(
            "TOMTOM_API_KEY is not set.\n"
            "\n"
            "No fixtures were captured, and none were invented. Set the key and\n"
            "re-run to replace the synthetic TomTom fixtures with genuine ones:\n"
            "\n"
            '    $env:TOMTOM_API_KEY = "..."    # PowerShell\n'
            "    python scripts/capture_tomtom_fixtures.py\n"
        )
        return 1

    captured_at = datetime.now(UTC)
    departure = (captured_at + timedelta(hours=2)).replace(
        minute=0, second=0, microsecond=0
    )

    print("Capturing genuine TomTom responses (key read from environment, never shown)")
    print()

    # --- Geocoding --------------------------------------------------------
    recorder = _Recorder()
    geocoder = TomTomGeocodingProvider(
        api_key,
        client=ProviderHttpClient(
            provider="tomtom", client=recorder.client(), cache_ttl_seconds=0
        ),
    )
    result = geocoder.geocode("Denver, CO")
    print(f"  geocoded -> {result.label}")
    _write("real_geocode_denver.json", recorder.bodies[0], api_key)
    geocode_urls = list(recorder.urls)

    # --- Truck routing ----------------------------------------------------
    recorder = _Recorder()
    router = TomTomRoutingProvider(
        api_key,
        client=ProviderHttpClient(
            provider="tomtom", client=recorder.client(), cache_ttl_seconds=0
        ),
    )
    routes = router.routes(DENVER, CHICAGO, departure, max_alternatives=2)
    print(
        f"  routed   -> {len(routes.routes)} distinct route(s) "
        f"of {routes.returned_count} returned"
    )
    for route in routes.routes:
        print(
            f"               {route.id}  {route.distance_miles:7.1f} mi  "
            f"{route.duration_seconds / 3600:5.2f} h  {len(route.geometry):>5} pts"
        )
    for notice in routes.notices:
        print(f"               note: {notice}")
    _write("real_route_denver_chicago.json", recorder.bodies[0], api_key)

    # --- Provenance -------------------------------------------------------
    record = {
        "captured_at_utc": captured_at.isoformat(timespec="seconds"),
        "captured_by": "backend/scripts/capture_tomtom_fixtures.py",
        "credentials_in_fixtures": "none (response bodies only; key never stored)",
        "requests": {
            "real_geocode_denver.json": {
                "endpoint": "GET https://api.tomtom.com/search/2/geocode/{query}.json",
                "query": "Denver, CO",
                "url_redacted": geocode_urls[0] if geocode_urls else None,
                "purpose": "successful geocoding response",
            },
            "real_route_denver_chicago.json": {
                "endpoint": (
                    "GET https://api.tomtom.com/routing/1/calculateRoute/"
                    "{locations}/json"
                ),
                "origin": "39.7392,-104.9903 (Denver, CO)",
                "destination": "41.8781,-87.6298 (Chicago, IL)",
                "travelMode": "truck",
                "maxAlternatives": 2,
                "departAt": departure.isoformat(timespec="seconds"),
                "url_redacted": recorder.urls[0] if recorder.urls else None,
                "purpose": "truck routing with alternatives",
                "vehicle_parameters_sent": (
                    "none - cargo weight is never sent as vehicleWeight (D16)"
                ),
                "distinct_routes_returned": len(routes.routes),
                "routes_before_deduplication": routes.returned_count,
            },
        },
    }
    _write("real_capture_provenance.json", record, api_key)

    print()
    print("Done. Next steps:")
    print("  1. Review the fixtures for anything unexpected.")
    print("  2. Update tests/fixtures/PROVENANCE.md from")
    print("     real_capture_provenance.json.")
    print("  3. Run: pytest -k real_tomtom   (the real-fixture contract tests)")
    if len(routes.routes) < 3:
        print()
        print(
            f"  NOTE: TomTom returned {len(routes.routes)} distinct route(s), not 3.\n"
            "        That is the real answer for this pair and is recorded as such.\n"
            "        No third route was invented."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
