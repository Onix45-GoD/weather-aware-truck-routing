"""Contract tests for `POST /api/v1/route-analysis`.

These are the tests a frontend developer should be able to read as the API
documentation: what a valid request looks like, what comes back, and what
every failure mode looks like on the wire.

Fully offline -- the package conftest forces fixture providers.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
import respx
from django.test import Client

from apps.routing.domain.models import RiskLevel
from apps.routing.providers.errors import (
    GeocodingNoResultsError,
    InvalidProviderResponseError,
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RoutingNoRoutesError,
)
from apps.routing.services.errors import AmbiguousLocationError

URL = "/api/v1/route-analysis"


def post(payload: dict) -> object:
    return Client().post(URL, data=json.dumps(payload), content_type="application/json")


@pytest.fixture
def analysis(valid_payload) -> dict:
    response = post(valid_payload)
    assert response.status_code == 200, response.content
    return response.json()


class TestSuccessfulAnalysis:
    def test_returns_200_with_the_full_contract(self, analysis) -> None:
        assert set(analysis) == {
            "request",
            "origin",
            "destination",
            "recommended_route_id",
            "recommendation_reason",
            "routes",
            "warnings",
            "meta",
        }

    def test_echoes_normalised_inputs(self, analysis) -> None:
        request = analysis["request"]
        assert request["origin"] == "Denver"
        assert request["destination"] == "Chicago"
        assert request["departure_at"] == "2026-11-02T12:00:00+00:00"
        assert request["effective_departure_at"] == "2026-11-02T12:00:00+00:00"
        assert request["forecast_offset_hours"] == 0
        assert request["checkpoint_interval_miles"] == 50

    def test_resolves_both_endpoints(self, analysis) -> None:
        for key in ("origin", "destination"):
            place = analysis[key]
            assert place["label"]
            assert -90 <= place["latitude"] <= 90
            assert -180 <= place["longitude"] <= 180
            assert "confidence" in place  # explicit, may be null

    def test_returns_ranked_routes(self, analysis) -> None:
        routes = analysis["routes"]
        assert routes
        assert [route["rank"] for route in routes] == list(
            range(1, len(routes) + 1)
        )

    def test_each_route_carries_what_the_ui_needs(self, analysis) -> None:
        route = analysis["routes"][0]
        assert set(route) == {
            "route_id",
            "label",
            "rank",
            "is_recommended",
            "eligible",
            "ineligibility_reasons",
            "separated_from_previous_by",
            "summary",
            "metrics",
            "geometry",
            "geometry_detail",
            "checkpoints",
        }

    def test_route_summary_fields(self, analysis) -> None:
        summary = analysis["routes"][0]["summary"]
        assert summary["distance_miles"] > 0
        assert summary["duration_seconds"] > 0
        assert summary["departure_at"].endswith("+00:00")
        assert summary["arrival_at"].endswith("+00:00")
        assert summary["eta_source"] in {
            "provider_segments",
            "distance_proportional",
        }

    def test_route_metrics_expose_every_ranking_input(self, analysis) -> None:
        metrics = analysis["routes"][0]["metrics"]
        for key in (
            "severe_miles",
            "high_miles",
            "moderate_miles",
            "low_miles",
            "no_travel_miles",
            "unknown_miles",
            "average_risk",
            "coverage_pct",
            "max_risk",
            "blocked",
        ):
            assert key in metrics

    def test_geometry_is_usable_and_honest_about_simplification(
        self, analysis
    ) -> None:
        route = analysis["routes"][0]
        geometry = route["geometry"]
        detail = route["geometry_detail"]

        assert len(geometry) >= 2
        assert all(len(point) == 2 for point in geometry)
        assert detail["returned_points"] == len(geometry)
        assert detail["source_points"] >= detail["returned_points"]

    def test_checkpoints_carry_position_time_weather_and_risk(
        self, analysis
    ) -> None:
        checkpoint = analysis["routes"][0]["checkpoints"][0]
        assert set(checkpoint) == {
            "index",
            "latitude",
            "longitude",
            "distance_from_origin_miles",
            "segment_miles",
            "eta",
            "is_origin",
            "is_destination",
            "weather",
            "risk",
        }
        assert checkpoint["is_origin"] is True
        assert checkpoint["eta"].endswith("+00:00")

    def test_checkpoint_risk_is_explainable(self, analysis) -> None:
        risk = analysis["routes"][0]["checkpoints"][0]["risk"]
        assert risk["level"] in {level.value for level in RiskLevel}
        assert risk["explanation"]
        assert "load_override_applied" in risk
        assert "partial_data" in risk

    def test_first_and_last_checkpoints_are_the_endpoints(self, analysis) -> None:
        points = analysis["routes"][0]["checkpoints"]
        assert points[0]["is_origin"] is True
        assert points[-1]["is_destination"] is True
        assert points[0]["distance_from_origin_miles"] == 0.0

    def test_meta_reports_provider_and_route_counts(self, analysis) -> None:
        meta = analysis["meta"]
        assert meta["routes_analysed"] == len(analysis["routes"])
        assert meta["routes_returned_by_provider"] >= meta["routes_analysed"]
        assert set(meta["providers"]) == {"geocoding", "routing", "weather"}
        assert meta["elapsed_ms"] >= 0

    def test_exactly_one_route_is_flagged_recommended(self, analysis) -> None:
        flagged = [r["route_id"] for r in analysis["routes"] if r["is_recommended"]]
        if analysis["recommended_route_id"] is None:
            assert flagged == []
        else:
            assert flagged == [analysis["recommended_route_id"]]


class TestResponseIsJsonSafe:
    def test_the_whole_payload_round_trips_through_json(self, analysis) -> None:
        """No NaN, no Infinity, no datetime objects -- a strict parser must cope."""
        text = json.dumps(analysis, allow_nan=False)
        assert json.loads(text) == analysis

    def test_every_timestamp_carries_an_offset(self, analysis) -> None:
        stamps = [analysis["request"]["departure_at"]]
        for route in analysis["routes"]:
            stamps.append(route["summary"]["arrival_at"])
            stamps.extend(point["eta"] for point in route["checkpoints"])
        assert all(stamp.endswith("+00:00") for stamp in stamps)

    def test_risk_levels_are_from_the_published_enum(self, analysis) -> None:
        allowed = set(analysis["meta"]["risk_levels"])
        assert allowed == {level.value for level in RiskLevel}
        for route in analysis["routes"]:
            assert route["metrics"]["max_risk"] in allowed
            for point in route["checkpoints"]:
                assert point["risk"]["level"] in allowed


class TestValidation:
    def test_missing_body_is_rejected(self) -> None:
        response = post({})
        assert response.status_code == 400
        body = response.json()["error"]
        assert body["code"] == "INVALID_REQUEST"
        assert set(body["details"]) >= {
            "origin",
            "destination",
            "departure_at",
            "load_weight_lb",
            "checkpoint_interval_miles",
        }

    @pytest.mark.parametrize("field", ["origin", "destination"])
    def test_blank_locations_are_rejected(self, valid_payload, field) -> None:
        response = post({**valid_payload, field: "   "})
        assert response.status_code == 400
        assert field in response.json()["error"]["details"]

    def test_a_naive_timestamp_without_a_timezone_is_rejected(
        self, valid_payload
    ) -> None:
        """Ambiguous by up to a day; guessing would shift every forecast.

        The error names `departure_timezone`, because supplying one is the
        fix -- see `test_timezones.py` for the full contract.
        """
        response = post({**valid_payload, "departure_at": "2026-11-02T12:00:00"})
        assert response.status_code == 400
        assert "departure_timezone" in response.json()["error"]["details"]

    def test_a_naive_timestamp_with_a_timezone_is_accepted(
        self, valid_payload
    ) -> None:
        response = post(
            {
                **valid_payload,
                "departure_at": "2026-11-02T06:00:00",
                "departure_timezone": "America/Denver",
            }
        )
        assert response.status_code == 200
        assert response.json()["request"]["departure_at"] == "2026-11-02T13:00:00+00:00"

    @pytest.mark.parametrize(
        "stamp",
        ["2026-11-02T12:00:00Z", "2026-11-02T06:00:00-06:00", "2026-11-02T13:00:00+01:00"],
    )
    def test_offset_bearing_timestamps_are_accepted_and_normalised(
        self, valid_payload, stamp
    ) -> None:
        response = post({**valid_payload, "departure_at": stamp})
        assert response.status_code == 200
        assert response.json()["request"]["departure_at"] == "2026-11-02T12:00:00+00:00"

    def test_a_malformed_timestamp_is_rejected(self, valid_payload) -> None:
        response = post({**valid_payload, "departure_at": "next tuesday"})
        assert response.status_code == 400

    @pytest.mark.parametrize("interval", [0, 5, 15, 30, 100, "fifty"])
    def test_unsupported_intervals_are_rejected(self, valid_payload, interval) -> None:
        response = post({**valid_payload, "checkpoint_interval_miles": interval})
        assert response.status_code == 400
        assert "checkpoint_interval_miles" in response.json()["error"]["details"]

    @pytest.mark.parametrize("interval", [10, 25, 50])
    def test_supported_intervals_are_accepted(self, valid_payload, interval) -> None:
        response = post({**valid_payload, "checkpoint_interval_miles": interval})
        assert response.status_code == 200
        assert response.json()["request"]["checkpoint_interval_miles"] == interval

    @pytest.mark.parametrize("weight", [0, -1, -42000])
    def test_non_positive_weights_are_rejected(self, valid_payload, weight) -> None:
        response = post({**valid_payload, "load_weight_lb": weight})
        assert response.status_code == 400
        assert "load_weight_lb" in response.json()["error"]["details"]

    def test_an_absurd_weight_is_rejected(self, valid_payload) -> None:
        """Catches a transcription error like an extra zero."""
        response = post({**valid_payload, "load_weight_lb": 999_999_999})
        assert response.status_code == 400

    @pytest.mark.parametrize("offset", [-1, 49, 500])
    def test_out_of_range_offsets_are_rejected(self, valid_payload, offset) -> None:
        response = post({**valid_payload, "forecast_offset_hours": offset})
        assert response.status_code == 400
        assert "forecast_offset_hours" in response.json()["error"]["details"]

    def test_offset_defaults_to_zero_when_omitted(self, analysis) -> None:
        assert analysis["request"]["forecast_offset_hours"] == 0

    def test_validation_happens_before_any_provider_call(self, valid_payload) -> None:
        """A typo must not burn API quota."""
        with patch("apps.routing.api.views.analyse_trip") as orchestrator:
            response = post({**valid_payload, "load_weight_lb": -5})
        assert response.status_code == 400
        orchestrator.assert_not_called()


class TestForecastOffset:
    def test_offset_shifts_the_effective_departure(self, valid_payload) -> None:
        response = post({**valid_payload, "forecast_offset_hours": 6})
        request = response.json()["request"]

        assert request["departure_at"] == "2026-11-02T12:00:00+00:00"
        assert request["effective_departure_at"] == "2026-11-02T18:00:00+00:00"

    def test_offset_shifts_every_eta(self, valid_payload) -> None:
        """Not a recolour: the analysis itself moves."""
        base = post(valid_payload).json()
        later = post({**valid_payload, "forecast_offset_hours": 12}).json()

        def first_eta(payload: dict) -> datetime:
            return datetime.fromisoformat(
                payload["routes"][0]["checkpoints"][0]["eta"]
            )

        assert first_eta(later) - first_eta(base) == timedelta(hours=12)


class TestErrorContract:
    """Every failure uses one envelope, so a client needs one error model."""

    def test_unresolved_location_is_a_400(self, valid_payload) -> None:
        response = post({**valid_payload, "origin": "Atlantis"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "GEOCODING_NO_RESULTS"

    @pytest.mark.parametrize(
        ("error", "expected_status", "expected_code"),
        [
            (RoutingNoRoutesError("none", provider="p"), 422, "ROUTING_NO_ROUTES"),
            (ProviderTimeoutError("slow", provider="p"), 504, "PROVIDER_TIMEOUT"),
            (ProviderRateLimitError("429", provider="p"), 429, "PROVIDER_RATE_LIMITED"),
            (ProviderUnavailableError("502", provider="p"), 502, "PROVIDER_UNAVAILABLE"),
            (
                InvalidProviderResponseError("garbage", provider="p"),
                502,
                "PROVIDER_INVALID_RESPONSE",
            ),
            (ProviderAuthError("401", provider="p"), 502, "PROVIDER_AUTH_FAILED"),
            (
                ProviderConfigurationError("no key", provider="p"),
                500,
                "PROVIDER_MISCONFIGURED",
            ),
            (
                GeocodingNoResultsError("nope", provider="p"),
                400,
                "GEOCODING_NO_RESULTS",
            ),
            (
                AmbiguousLocationError("unsure", field="origin"),
                400,
                "LOCATION_AMBIGUOUS",
            ),
        ],
    )
    def test_each_failure_maps_to_its_status_and_code(
        self, valid_payload, error, expected_status, expected_code
    ) -> None:
        with patch(
            "apps.routing.api.views.analyse_trip", side_effect=error
        ):
            response = post(valid_payload)

        assert response.status_code == expected_status
        assert response.json()["error"]["code"] == expected_code

    def test_every_error_uses_the_same_envelope(self, valid_payload) -> None:
        with patch(
            "apps.routing.api.views.analyse_trip",
            side_effect=ProviderTimeoutError("slow", provider="p"),
        ):
            body = post(valid_payload).json()

        assert set(body) == {"error"}
        assert set(body["error"]) == {"code", "message", "field", "details"}

    def test_an_ambiguous_location_names_the_field(self, valid_payload) -> None:
        with patch(
            "apps.routing.api.views.analyse_trip",
            side_effect=AmbiguousLocationError("unsure", field="destination"),
        ):
            body = post(valid_payload).json()
        assert body["error"]["field"] == "destination"

    def test_rate_limits_forward_retry_after(self, valid_payload) -> None:
        with patch(
            "apps.routing.api.views.analyse_trip",
            side_effect=ProviderRateLimitError(
                "429", provider="p", retry_after_seconds=30
            ),
        ):
            response = post(valid_payload)
        assert response["Retry-After"] == "30"

    def test_an_unexpected_exception_becomes_a_safe_500(self, valid_payload) -> None:
        """No stack trace, no internals, no upstream detail."""
        with patch(
            "apps.routing.api.views.analyse_trip",
            side_effect=RuntimeError(
                "psycopg connection string host=10.0.0.1 password=hunter2"
            ),
        ):
            response = post(valid_payload)

        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        assert "hunter2" not in response.content.decode()
        assert "Traceback" not in response.content.decode()
        assert "10.0.0.1" not in response.content.decode()

    def test_no_error_response_leaks_a_credential(self, valid_payload) -> None:
        with patch(
            "apps.routing.api.views.analyse_trip",
            side_effect=ProviderAuthError(
                "rejected our credentials (HTTP 401)", provider="tomtom"
            ),
        ):
            text = post(valid_payload).content.decode()
        assert "key=" not in text


class TestNoSafeRouteIsNotAnError:
    def test_all_routes_blocked_is_a_200_with_a_null_recommendation(
        self, valid_payload
    ) -> None:
        """A valid analysis saying "do not drive" is the answer, not a failure.

        Returning 5xx here would make an outage and a blizzard look the same
        to the client.
        """
        from apps.routing.domain.models import WeatherSample
        from apps.routing.providers.fixtures import FixtureWeatherProvider

        class Blizzard(FixtureWeatherProvider):
            def _sample(self, coordinate, moment, index):  # type: ignore[override]
                return WeatherSample(
                    wind_mph=70.0, rain_in_hr=0.0, snow_in_hr=0.0,
                    forecast_time=moment,
                )

        with patch(
            "apps.routing.services.analysis.get_weather_provider",
            return_value=Blizzard(),
        ):
            response = post(valid_payload)

        assert response.status_code == 200
        body = response.json()
        assert body["recommended_route_id"] is None
        assert body["recommendation_reason"]
        assert body["routes"], "blocked routes are still returned, with reasons"
        assert all(route["metrics"]["blocked"] for route in body["routes"])
        assert any(w["code"] == "NO_ELIGIBLE_ROUTE" for w in body["warnings"])

    def test_blocked_routes_explain_themselves(self, valid_payload) -> None:
        from apps.routing.domain.models import WeatherSample
        from apps.routing.providers.fixtures import FixtureWeatherProvider

        class Blizzard(FixtureWeatherProvider):
            def _sample(self, coordinate, moment, index):  # type: ignore[override]
                return WeatherSample(
                    wind_mph=70.0, rain_in_hr=0.0, snow_in_hr=0.0,
                    forecast_time=moment,
                )

        with patch(
            "apps.routing.services.analysis.get_weather_provider",
            return_value=Blizzard(),
        ):
            body = post(valid_payload).json()

        route = body["routes"][0]
        assert route["eligible"] is False
        assert route["ineligibility_reasons"]


class TestOfflineGuarantee:
    @respx.mock
    def test_a_full_analysis_makes_no_outbound_http_request(
        self, valid_payload
    ) -> None:
        """respx raises on any unmocked request, so this fails if one happens."""
        response = post(valid_payload)
        assert response.status_code == 200
        assert len(respx.calls) == 0

    def test_no_api_key_is_needed(self, settings, valid_payload) -> None:
        settings.TOMTOM_API_KEY = ""
        assert post(valid_payload).status_code == 200


class TestHttpSemantics:
    def test_get_is_not_allowed(self) -> None:
        assert Client().get(URL).status_code == 405

    def test_malformed_json_is_a_400(self) -> None:
        response = Client().post(
            URL, data="{not json", content_type="application/json"
        )
        assert response.status_code == 400

    def test_the_endpoint_is_stateless(self, valid_payload) -> None:
        """Two identical requests produce identical analyses."""
        first = post(valid_payload).json()
        second = post(valid_payload).json()

        for payload in (first, second):
            payload["meta"].pop("elapsed_ms")
        assert first == second
