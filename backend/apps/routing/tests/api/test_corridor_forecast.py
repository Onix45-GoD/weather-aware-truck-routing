"""Contract tests for `POST /api/v1/corridor-forecast`.

Offline: the package conftest forces the fixture weather provider. The
request is built the way the frontend builds it -- from a route-analysis
response -- so the two endpoints are proven to fit together.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.test import Client

from apps.routing.domain.models import WeatherSample
from apps.routing.providers.base import HourlyForecast
from apps.routing.providers.errors import ProviderTimeoutError

URL = "/api/v1/corridor-forecast"
REFERENCE = "2026-11-02T13:00:00+00:00"


def post(payload: dict, **extra) -> object:
    return Client().post(URL, data=json.dumps(payload), content_type="application/json", **extra)


def checkpoints(count: int = 5) -> list[dict]:
    return [
        {
            "index": i,
            "latitude": 40.0 + 0.1 * i,
            "longitude": -100.0 + 0.3 * i,
            "distance_from_origin_miles": 25.0 * i,
        }
        for i in range(count)
    ]


def payload(**overrides) -> dict:
    base = {
        "reference_at": REFERENCE,
        "load_weight_lb": 40000,
        "checkpoints": checkpoints(),
        "route_id": "tomtom-0",
        "timezone": "America/Denver",
    }
    base.update(overrides)
    return base


@pytest.fixture
def body() -> dict:
    response = post(payload())
    assert response.status_code == 200, response.content
    return response.json()


class TestContract:
    def test_top_level_shape(self, body) -> None:
        assert set(body) == {
            "route_id", "reference_at", "reference_at_local", "timezone",
            "step_hours", "horizon_hours", "provider", "load_weight_lb",
            "forecast_window", "checkpoints", "frames", "available_hours",
            "warnings", "meta",
        }
        assert body["route_id"] == "tomtom-0"
        assert body["reference_at"] == REFERENCE
        assert body["reference_at_local"] == "2026-11-02T06:00:00-07:00"
        assert body["step_hours"] == 1
        assert body["horizon_hours"] == 48
        assert body["provider"] == "fixtures"

    def test_forty_nine_hourly_frames_with_local_renderings(self, body) -> None:
        frames = body["frames"]
        assert len(frames) == 49
        assert [f["hour"] for f in frames] == list(range(49))
        assert frames[0]["at"] == REFERENCE
        assert frames[12]["at"] == "2026-11-03T01:00:00+00:00"
        assert frames[12]["at_local"] == "2026-11-02T18:00:00-07:00"
        assert frames[48]["at"] == "2026-11-04T13:00:00+00:00"

    def test_frame_checkpoints_use_the_analysis_shapes(self, body) -> None:
        point = body["frames"][3]["checkpoints"][1]
        assert set(point) == {"index", "weather", "risk"}
        assert set(point["weather"]) == {
            "wind_mph", "wind_gust_mph", "rain_in_hr", "snow_in_hr", "forecast_time",
        }
        assert set(point["risk"]) == {
            "level", "driver", "base_level", "wind_level", "rain_level",
            "snow_level", "load_override_applied", "partial_data", "explanation",
        }
        assert point["weather"]["forecast_time"] == "2026-11-02T16:00:00+00:00"

    def test_checkpoints_echo_position_and_segment_miles(self, body) -> None:
        assert [c["index"] for c in body["checkpoints"]] == [0, 1, 2, 3, 4]
        assert [c["segment_miles"] for c in body["checkpoints"]] == [25.0, 25.0, 25.0, 25.0, 0.0]

    def test_frame_summary_is_the_domain_breakdown(self, body) -> None:
        summary = body["frames"][0]["summary"]
        assert set(summary) == {
            "low_miles", "moderate_miles", "high_miles", "severe_miles",
            "no_travel_miles", "unknown_miles", "average_risk", "max_risk",
            "coverage_pct", "blocked",
        }
        miles = sum(summary[key] for key in (
            "low_miles", "moderate_miles", "high_miles", "severe_miles",
            "no_travel_miles", "unknown_miles",
        ))
        assert miles == pytest.approx(100.0)
        assert "duration_seconds" not in summary

    def test_fully_covered_window_has_no_warnings(self, body) -> None:
        assert body["available_hours"] == 49
        assert body["warnings"] == []

    def test_meta_counts(self, body) -> None:
        assert body["meta"]["checkpoints"] == 5
        assert body["meta"]["frames"] == 49
        assert body["meta"]["elapsed_ms"] >= 0

    def test_response_is_gzipped_when_accepted(self) -> None:
        response = post(payload(), HTTP_ACCEPT_ENCODING="gzip")
        assert response.status_code == 200
        assert response["Content-Encoding"] == "gzip"
        inflated = json.loads(gzip.decompress(response.content))
        assert len(inflated["frames"]) == 49


class TestValidation:
    def test_missing_fields(self) -> None:
        response = post({})
        assert response.status_code == 400
        details = response.json()["error"]["details"]
        assert set(details) >= {"reference_at", "load_weight_lb", "checkpoints"}

    def test_naive_reference_time(self) -> None:
        response = post(payload(reference_at="2026-11-02T13:00:00"))
        assert response.status_code == 400
        assert "reference_at" in response.json()["error"]["details"]

    def test_one_checkpoint_is_too_few(self) -> None:
        response = post(payload(checkpoints=checkpoints(1)))
        assert response.status_code == 400

    def test_too_many_checkpoints(self) -> None:
        response = post(payload(checkpoints=checkpoints(301)))
        assert response.status_code == 400

    def test_distances_must_not_decrease(self) -> None:
        points = checkpoints()
        points[2]["distance_from_origin_miles"] = 10.0
        response = post(payload(checkpoints=points))
        assert response.status_code == 400
        assert "checkpoints" in response.json()["error"]["details"]

    def test_duplicate_indexes(self) -> None:
        points = checkpoints()
        points[1]["index"] = 0
        assert post(payload(checkpoints=points)).status_code == 400

    def test_zero_length_route(self) -> None:
        points = [dict(p, distance_from_origin_miles=0.0) for p in checkpoints(2)]
        assert post(payload(checkpoints=points)).status_code == 400

    def test_load_bounds(self) -> None:
        assert post(payload(load_weight_lb=0)).status_code == 400
        assert post(payload(load_weight_lb=300000)).status_code == 400

    def test_unknown_timezone(self) -> None:
        response = post(payload(timezone="Mars/Olympus"))
        assert response.status_code == 400

    def test_timezone_is_optional(self) -> None:
        body = post(payload(timezone=None)).json()
        assert body["timezone"] is None
        assert body["frames"][0]["at_local"] is None

    def test_coordinates_out_of_range(self) -> None:
        points = checkpoints()
        points[0]["latitude"] = 95.0
        assert post(payload(checkpoints=points)).status_code == 400


class TestMissingAndPartial:
    def test_missing_hours_surface_as_unknown_and_a_warning(self, settings) -> None:
        from apps.routing.providers.fixtures import FixtureWeatherProvider

        with patch(
            "apps.routing.services.corridor.get_weather_provider",
            return_value=FixtureWeatherProvider(missing_every=6),
        ):
            body = post(payload()).json()

        unknown_frames = [
            f for f in body["frames"]
            if all(c["risk"]["level"] == "UNKNOWN" for c in f["checkpoints"])
        ]
        assert unknown_frames
        for frame in unknown_frames:
            assert frame["summary"]["coverage_pct"] == 0.0
            assert frame["summary"]["unknown_miles"] == 100.0
            for point in frame["checkpoints"]:
                assert point["weather"]["wind_mph"] is None
                assert point["risk"]["level"] != "LOW"

    def test_hours_beyond_the_provider_series_are_unavailable(self) -> None:
        reference = datetime(2026, 11, 2, 13, tzinfo=UTC)

        class ShortSeries:
            name = "short"

            def hourly(self, coordinates, start, end):
                times = tuple(reference + timedelta(hours=h) for h in range(20))
                return tuple(
                    HourlyForecast(
                        coordinate=c, resolved_coordinate=c, times=times,
                        samples=tuple(
                            WeatherSample(wind_mph=3.0, rain_in_hr=0.0, snow_in_hr=0.0, forecast_time=t)
                            for t in times
                        ),
                        provider="short",
                    )
                    for c in coordinates
                )

        with patch("apps.routing.services.corridor.get_weather_provider", return_value=ShortSeries()):
            body = post(payload()).json()

        assert body["available_hours"] == 20
        assert body["forecast_window"]["end"] == "2026-11-03T08:00:00+00:00"
        late = body["frames"][30]
        assert late["available"] is False
        assert late["unavailable_reason"] == "outside_provider_horizon"
        assert all(c["weather"] is None for c in late["checkpoints"])
        assert all(c["risk"]["level"] == "UNKNOWN" for c in late["checkpoints"])
        assert [w["code"] for w in body["warnings"]] == ["FORECAST_HORIZON"]


class TestUpstreamFailures:
    def test_timeout_is_504(self) -> None:
        class Slow:
            name = "slow"

            def hourly(self, *_a, **_k):
                raise ProviderTimeoutError("slow", provider="open-meteo")

        with patch("apps.routing.services.corridor.get_weather_provider", return_value=Slow()):
            response = post(payload())
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "PROVIDER_TIMEOUT"


class TestDeduplication:
    def test_one_provider_call_per_request(self) -> None:
        calls = []

        class Recording:
            name = "recording"

            def hourly(self, coordinates, start, end):
                calls.append(len(coordinates))
                times = tuple(datetime(2026, 11, 2, 13, tzinfo=UTC) + timedelta(hours=h) for h in range(49))
                return tuple(
                    HourlyForecast(
                        coordinate=c, resolved_coordinate=c, times=times,
                        samples=tuple(
                            WeatherSample(wind_mph=1.0, rain_in_hr=0.0, snow_in_hr=0.0, forecast_time=t)
                            for t in times
                        ),
                        provider="recording",
                    )
                    for c in coordinates
                )

        with patch("apps.routing.services.corridor.get_weather_provider", return_value=Recording()):
            assert post(payload(checkpoints=checkpoints(12))).status_code == 200
        assert calls == [12]


class TestBaselineIsUntouched:
    def test_corridor_requests_do_not_alter_a_route_analysis(self, valid_payload) -> None:
        """The analysis is a pure function of its input; a corridor call in
        between must not change it."""
        before = Client().post(
            "/api/v1/route-analysis", data=json.dumps(valid_payload), content_type="application/json"
        ).json()
        assert post(payload()).status_code == 200
        after = Client().post(
            "/api/v1/route-analysis", data=json.dumps(valid_payload), content_type="application/json"
        ).json()

        for key in ("recommended_route_id", "recommendation_reason", "routes"):
            assert before[key] == after[key]

    def test_frames_built_from_a_real_analysis_response(self, valid_payload) -> None:
        """The frontend builds the corridor request from the analysis; prove it fits."""
        analysis = Client().post(
            "/api/v1/route-analysis", data=json.dumps(valid_payload), content_type="application/json"
        ).json()
        route = analysis["routes"][0]
        request = {
            "reference_at": analysis["request"]["effective_departure_at"],
            "load_weight_lb": analysis["request"]["load_weight_lb"],
            "route_id": route["route_id"],
            "timezone": analysis["request"]["departure_timezone"],
            "checkpoints": [
                {
                    "index": c["index"],
                    "latitude": c["latitude"],
                    "longitude": c["longitude"],
                    "distance_from_origin_miles": c["distance_from_origin_miles"],
                }
                for c in route["checkpoints"]
            ],
        }
        body = post(request).json()
        assert body["route_id"] == route["route_id"]
        assert len(body["checkpoints"]) == len(route["checkpoints"])
        # Frame +0 at the origin is the same instant the analysis used for
        # the origin's ETA, so the two must agree exactly there.
        origin_analysis = route["checkpoints"][0]
        origin_frame = body["frames"][0]["checkpoints"][0]
        assert origin_frame["risk"]["level"] == origin_analysis["risk"]["level"]
        assert origin_frame["weather"] == origin_analysis["weather"]
