"""Contract tests for `GET /api/v1/checkpoint-weather`.

Offline: OpenWeatherMap is mocked with respx. The fixtures below are shaped
exactly like the documented `data/2.5/weather` and `data/2.5/forecast`
responses, including the units quirks the adapter must handle (imperial
temperature and wind, but millimetre precipitation and metre visibility).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from django.test import Client

from apps.routing.providers.openweathermap import ForecastSlot
from apps.routing.services.checkpoint_weather import nearest_slot

FAKE_KEY = "owm-secret-key-0123456789abcdef"
BASE = "https://api.openweathermap.org/data/2.5"
URL = "/api/v1/checkpoint-weather"

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def current_payload() -> dict:
    return {
        "coord": {"lon": -104.99, "lat": 39.74},
        "weather": [{"id": 801, "main": "Clouds", "description": "few clouds", "icon": "02d"}],
        "main": {"temp": 62.6, "feels_like": 64.4, "pressure": 1021, "humidity": 94},
        "visibility": 10000,
        "wind": {"speed": 2.2, "deg": 112, "gust": 4.5},
        "clouds": {"all": 20},
        "rain": {"1h": 2.54},
        "dt": int(NOW.timestamp()),
        "sys": {"sunrise": int((NOW - timedelta(hours=5)).timestamp()), "sunset": int((NOW + timedelta(hours=6)).timestamp())},
        "name": "Denver",
    }


def forecast_payload(slots: int = 8) -> dict:
    base = NOW.replace(minute=0, second=0, microsecond=0)
    return {
        "list": [
            {
                "dt": int((base + timedelta(hours=3 * i)).timestamp()),
                "main": {"temp": 60 + i, "feels_like": 58 + i, "humidity": 50 + i},
                "weather": [{"main": "Rain" if i == 3 else "Clear", "description": "light rain" if i == 3 else "clear sky", "icon": "10d" if i == 3 else "01d"}],
                "clouds": {"all": 10 * i},
                "wind": {"speed": 5 + i, "deg": 180, "gust": 9 + i},
                "pop": 0.1 * i,
                "rain": {"3h": 5.08} if i == 3 else {},
            }
            for i in range(slots)
        ],
        "city": {"name": "Denver"},
    }


@pytest.fixture
def configured(settings):
    settings.OPENWEATHERMAP_API_KEY = FAKE_KEY


@pytest.fixture
def upstream():
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE}/weather").mock(return_value=httpx.Response(200, json=current_payload()))
        mock.get(f"{BASE}/forecast").mock(return_value=httpx.Response(200, json=forecast_payload()))
        yield mock


def get(**params) -> "object":
    return Client().get(URL, params)


class TestValidation:
    def test_missing_coordinates_are_400(self, configured) -> None:
        response = get()
        assert response.status_code == 400
        body = response.json()["error"]
        assert body["code"] == "INVALID_REQUEST"
        assert set(body["details"]) >= {"lat", "lon"}

    def test_out_of_range_latitude_is_400(self, configured) -> None:
        assert get(lat=95, lon=0).status_code == 400

    def test_naive_eta_is_rejected(self, configured) -> None:
        response = get(lat=39.74, lon=-104.99, at="2026-11-02T18:00:00")
        assert response.status_code == 400
        assert "at" in response.json()["error"]["details"]


class TestWithoutAKey:
    def test_is_503_with_a_stable_code(self, settings) -> None:
        settings.OPENWEATHERMAP_API_KEY = ""
        response = get(lat=39.74, lon=-104.99)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "CHECKPOINT_WEATHER_NOT_CONFIGURED"


class TestHappyPath:
    def test_current_conditions_are_normalised(self, configured, upstream) -> None:
        body = get(lat=39.74, lon=-104.99).json()
        current = body["current"]
        assert body["source"] == "openweathermap"
        assert body["place_name"] == "Denver"
        assert current["condition"] == "Clouds"
        assert current["description"] == "few clouds"
        assert current["icon"] == "02d"
        assert current["temp_f"] == 62.6
        assert current["feels_like_f"] == 64.4
        assert current["humidity_pct"] == 94
        assert current["pressure_hpa"] == 1021
        # Metres -> miles and millimetres -> inches, by exact factors.
        assert current["visibility_miles"] == pytest.approx(6.2, abs=0.05)
        assert current["rain_in_last_hour"] == pytest.approx(0.1, abs=0.001)
        assert current["snow_in_last_hour"] is None
        assert current["observed_at"] == NOW.isoformat()

    def test_forecast_is_ascending_and_complete(self, configured, upstream) -> None:
        forecast = get(lat=39.74, lon=-104.99).json()["forecast"]
        assert len(forecast) == 8
        times = [slot["at"] for slot in forecast]
        assert times == sorted(times)
        rainy = forecast[3]
        assert rainy["condition"] == "Rain"
        assert rainy["precipitation_probability"] == pytest.approx(0.3)
        assert rainy["rain_in_3h"] == pytest.approx(0.2, abs=0.001)

    def test_eta_picks_the_nearest_slot_and_reports_the_gap(self, configured, upstream) -> None:
        eta = (NOW + timedelta(hours=9, minutes=50)).isoformat()
        body = get(lat=39.74, lon=-104.99, at=eta).json()
        assert body["at_eta"] is not None
        assert body["at_eta"]["condition"] == "Rain"  # slot 3 = NOW + 9h
        assert body["eta_gap_minutes"] == -50
        assert body["eta_beyond_horizon"] is False

    def test_eta_past_the_horizon_has_no_eta_slot(self, configured, upstream) -> None:
        eta = (NOW + timedelta(days=6)).isoformat()
        body = get(lat=39.74, lon=-104.99, at=eta).json()
        assert body["at_eta"] is None
        assert body["eta_gap_minutes"] is None
        assert body["eta_beyond_horizon"] is True

    def test_key_goes_upstream_but_never_comes_back(self, configured, upstream) -> None:
        response = get(lat=39.74, lon=-104.99)
        for route in upstream.routes:
            if route.called:
                assert route.calls.last.request.url.params["appid"] == FAKE_KEY
                assert route.calls.last.request.url.params["units"] == "imperial"
        assert FAKE_KEY not in response.content.decode()

    def test_nearby_checkpoints_share_one_lookup(self, configured, upstream) -> None:
        get(lat=39.7401, lon=-104.9902)
        get(lat=39.7398, lon=-104.9897)  # same 2-decimal cell
        for route in upstream.routes:
            assert route.call_count == 1


class TestUpstreamFailures:
    def test_rejected_key_is_502(self, configured) -> None:
        with respx.mock:
            respx.get(f"{BASE}/weather").mock(return_value=httpx.Response(401, json={"cod": 401}))
            response = get(lat=39.74, lon=-104.99)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "PROVIDER_AUTH_FAILED"
        assert FAKE_KEY not in response.content.decode()

    def test_malformed_body_is_502(self, configured) -> None:
        with respx.mock:
            respx.get(f"{BASE}/weather").mock(return_value=httpx.Response(200, json={"cod": 200}))
            response = get(lat=39.74, lon=-104.99)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "PROVIDER_INVALID_RESPONSE"


class TestNearestSlot:
    def slots(self, count: int = 4) -> tuple[ForecastSlot, ...]:
        return tuple(
            ForecastSlot(
                at=NOW + timedelta(hours=3 * i), condition="Clear", description="clear sky",
                icon="01d", temp_f=60.0, feels_like_f=60.0, precipitation_probability=0.0,
                wind_mph=1.0, wind_gust_mph=None, wind_deg=0, humidity_pct=50, cloud_pct=0,
                rain_in_3h=None, snow_in_3h=None,
            )
            for i in range(count)
        )

    def test_exact_match_has_zero_gap(self) -> None:
        slot, gap, beyond = nearest_slot(self.slots(), NOW + timedelta(hours=6))
        assert slot is not None and slot.at == NOW + timedelta(hours=6)
        assert gap == 0 and beyond is False

    def test_within_half_a_step_rounds_to_the_closer_slot(self) -> None:
        slot, gap, _ = nearest_slot(self.slots(), NOW + timedelta(hours=4))
        assert slot is not None and slot.at == NOW + timedelta(hours=3)
        assert gap == -60

    def test_before_the_window_is_not_answered(self) -> None:
        slot, gap, beyond = nearest_slot(self.slots(), NOW - timedelta(hours=5))
        assert slot is None and gap is None and beyond is False

    def test_empty_forecast(self) -> None:
        assert nearest_slot((), NOW) == (None, None, True)
