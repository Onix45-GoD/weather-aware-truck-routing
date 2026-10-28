"""End-to-end analysis driven by the genuine captured TomTom responses.

The rest of the API suite uses the synthetic fixture providers, which are
convenient but shaped by our own expectations. This module replays the real
captured bodies (Milestone 2, D26) through the *real* TomTom adapters, so the
orchestration is exercised against geometry and summaries TomTom actually
sent: 10,759-vertex routes, single legs, real distances.

Still offline -- the bodies are replayed through `respx`, and the weather side
uses the deterministic fixture provider.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from django.test import Client

from apps.routing.providers.fixtures import FixtureWeatherProvider
from apps.routing.providers.tomtom import (
    TomTomGeocodingProvider,
    TomTomRoutingProvider,
)

URL = "/api/v1/route-analysis"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tomtom"
REAL_GEOCODE = FIXTURES / "real_geocode_denver.json"
REAL_ROUTE = FIXTURES / "real_route_denver_chicago.json"

FAKE_KEY = "test-key-NEVER-REAL-0123456789"

_SKIP = (
    "No genuine TomTom capture in the repository; run "
    "scripts/capture_tomtom_fixtures.py with TOMTOM_API_KEY set."
)


def _load(path: Path):
    if not path.exists():
        pytest.skip(_SKIP)
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def real_tomtom(monkeypatch):
    """Point the orchestration at real TomTom adapters fed by captures."""
    geocoder = TomTomGeocodingProvider(FAKE_KEY, cache_ttl_seconds=0)
    router = TomTomRoutingProvider(FAKE_KEY, cache_ttl_seconds=0)

    monkeypatch.setattr(
        "apps.routing.services.analysis.get_geocoding_provider", lambda: geocoder
    )
    monkeypatch.setattr(
        "apps.routing.services.analysis.get_routing_provider", lambda: router
    )
    monkeypatch.setattr(
        "apps.routing.services.analysis.get_weather_provider",
        lambda: FixtureWeatherProvider(),
    )


@pytest.fixture
def payload() -> dict:
    return {
        "origin": "Denver, CO",
        "destination": "Chicago, IL",
        "departure_at": "2026-11-02T12:00:00Z",
        "load_weight_lb": 42000,
        "checkpoint_interval_miles": 50,
    }


def analyse(payload: dict):
    return Client().post(
        URL, data=json.dumps(payload), content_type="application/json"
    )


@pytest.fixture
def mocked_tomtom(real_tomtom):
    geocode_body = _load(REAL_GEOCODE)
    route_body = _load(REAL_ROUTE)
    with respx.mock:
        respx.get(url__startswith="https://api.tomtom.com/search/2/geocode/").mock(
            return_value=httpx.Response(200, json=geocode_body)
        )
        respx.get(
            url__startswith="https://api.tomtom.com/routing/1/calculateRoute/"
        ).mock(return_value=httpx.Response(200, json=route_body))
        yield route_body


class TestRealTomTomAnalysis:
    def test_a_full_analysis_succeeds_on_genuine_data(
        self, mocked_tomtom, payload
    ) -> None:
        response = analyse(payload)
        assert response.status_code == 200, response.content

        body = response.json()
        assert len(body["routes"]) == len(mocked_tomtom["routes"])
        assert body["recommendation_reason"]

    def test_genuine_distances_survive_the_whole_pipeline(
        self, mocked_tomtom, payload
    ) -> None:
        body = analyse(payload).json()

        expected = sorted(
            route["summary"]["lengthInMeters"] / 1609.344
            for route in mocked_tomtom["routes"]
        )
        actual = sorted(route["summary"]["distance_miles"] for route in body["routes"])
        assert actual == pytest.approx(expected, abs=0.01)

    def test_checkpoints_cover_a_real_thousand_mile_route(
        self, mocked_tomtom, payload
    ) -> None:
        body = analyse(payload).json()
        route = body["routes"][0]
        points = route["checkpoints"]

        assert points[0]["distance_from_origin_miles"] == 0.0
        assert points[-1]["distance_from_origin_miles"] == pytest.approx(
            route["summary"]["distance_miles"], abs=0.01
        )
        # ~1,000 miles at 50-mile spacing, plus the destination.
        assert len(points) >= 20

    def test_segment_miles_still_reconcile_on_real_geometry(
        self, mocked_tomtom, payload
    ) -> None:
        for route in analyse(payload).json()["routes"]:
            total = sum(point["segment_miles"] for point in route["checkpoints"])
            assert total == pytest.approx(route["summary"]["distance_miles"], abs=0.05)

    def test_real_geometry_is_simplified_for_the_wire(
        self, mocked_tomtom, payload
    ) -> None:
        """~39,000 source vertices would be about a megabyte of JSON."""
        body = analyse(payload).json()

        for route in body["routes"]:
            detail = route["geometry_detail"]
            assert detail["source_points"] > 5_000, "real routes are dense"
            assert detail["simplified"] is True
            assert detail["returned_points"] < detail["source_points"] / 2

    def test_the_payload_stays_a_reasonable_size(
        self, mocked_tomtom, payload
    ) -> None:
        body = analyse(payload).content
        assert len(body) < 1_500_000, "full-resolution geometry would exceed this"

    def test_real_routes_report_the_proportional_eta_fallback(
        self, mocked_tomtom, payload
    ) -> None:
        """Every captured route has one leg, so there are no segment timings.

        Confirms D24 end to end: the fallback is used *and* declared.
        """
        body = analyse(payload).json()
        assert all(
            route["summary"]["eta_source"] == "distance_proportional"
            for route in body["routes"]
        )
        assert any(w["code"] == "ETA_ESTIMATED" for w in body["warnings"])

    def test_three_real_alternatives_raise_no_shortfall_warning(
        self, mocked_tomtom, payload
    ) -> None:
        body = analyse(payload).json()
        if len(mocked_tomtom["routes"]) < 3:
            pytest.skip("capture contains fewer than three routes")
        assert not any(w["code"] == "FEWER_ALTERNATIVES" for w in body["warnings"])

    def test_real_geocode_confidence_reaches_the_response(
        self, mocked_tomtom, payload
    ) -> None:
        """D27: a genuine 0-1 confidence, not the unbounded relevance score."""
        body = analyse(payload).json()
        confidence = body["origin"]["confidence"]
        assert confidence is not None
        assert 0.0 <= confidence <= 1.0

    def test_no_credential_appears_in_the_response(
        self, mocked_tomtom, payload
    ) -> None:
        text = analyse(payload).content.decode()
        assert FAKE_KEY not in text
        assert "key=" not in text
