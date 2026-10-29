"""Per-endpoint rate limits.

The limits are the last line of defence once the service is hosted: an
analysis is several provider calls and a corridor is a two-second one, so an
unthrottled public endpoint is somebody else's quota. These tests lower the
rates and prove the 429 arrives in the project's error envelope.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.routing.tests.api.test_corridor_forecast import payload as corridor_payload


@pytest.fixture
def tight(settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {
            "analysis": "2/min",
            "corridor": "2/min",
            "places": "3/min",
        },
    }


def post(path: str, body: dict):
    return Client().post(path, data=json.dumps(body), content_type="application/json")


class TestLimits:
    def test_places_limit_returns_the_envelope_and_retry_after(self, tight) -> None:
        for _ in range(3):
            assert Client().get("/api/v1/places", {"q": "den"}).status_code == 200
        response = Client().get("/api/v1/places", {"q": "den"})
        assert response.status_code == 429
        body = response.json()["error"]
        assert body["code"] == "RATE_LIMITED"
        assert "Try again" in body["message"]
        assert body["details"]["retry_after_seconds"] >= 1
        assert int(response["Retry-After"]) >= 1

    def test_analysis_limit(self, tight, valid_payload) -> None:
        assert post("/api/v1/route-analysis", valid_payload).status_code == 200
        assert post("/api/v1/route-analysis", valid_payload).status_code == 200
        assert post("/api/v1/route-analysis", valid_payload).status_code == 429

    def test_corridor_limit(self, tight) -> None:
        assert post("/api/v1/corridor-forecast", corridor_payload()).status_code == 200
        assert post("/api/v1/corridor-forecast", corridor_payload()).status_code == 200
        assert post("/api/v1/corridor-forecast", corridor_payload()).status_code == 429

    def test_scopes_are_independent(self, tight) -> None:
        """Exhausting places must not block an analysis."""
        for _ in range(4):
            Client().get("/api/v1/places", {"q": "den"})
        assert Client().get("/api/v1/places", {"q": "den"}).status_code == 429
        assert post("/api/v1/corridor-forecast", corridor_payload()).status_code == 200

    def test_health_is_never_throttled(self, tight) -> None:
        for _ in range(20):
            assert Client().get("/api/v1/health").status_code == 200

    def test_a_rejected_request_does_not_count_against_the_limit(self, tight) -> None:
        """Validation happens inside the view; throttling happens before it.

        DRF counts every call that reaches the view, valid or not, which is
        the conservative choice for a public endpoint. This pins it so a
        future change is deliberate.
        """
        assert post("/api/v1/route-analysis", {}).status_code == 400
        assert post("/api/v1/route-analysis", {}).status_code == 400
        assert post("/api/v1/route-analysis", {}).status_code == 429


class TestDefaults:
    def test_production_rates_are_configured(self) -> None:
        from django.conf import settings

        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        assert set(rates) == {"analysis", "corridor", "places"}
