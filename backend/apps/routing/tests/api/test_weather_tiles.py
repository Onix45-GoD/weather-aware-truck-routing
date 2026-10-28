"""Contract tests for `GET /api/v1/weather-tiles/<layer>/<z>/<x>/<y>.png`.

The proxy exists for one reason: the OpenWeatherMap key must never reach the
browser. So beyond the happy path, these tests pin down that the key is sent
upstream, is absent from every response, and that nothing outside the layer
allowlist can be requested.

Fully offline -- upstream is mocked with respx.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from django.test import Client

from apps.routing.providers.openweathermap import (
    MAX_TILE_ZOOM,
    WEATHER_TILE_LAYERS,
    tile_coordinates_are_valid,
)

FAKE_KEY = "owm-secret-key-0123456789abcdef"
UPSTREAM = "https://tile.openweathermap.org/map"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def tile_url(layer: str = "precipitation_new", z: int = 5, x: int = 7, y: int = 12) -> str:
    return f"/api/v1/weather-tiles/{layer}/{z}/{x}/{y}.png"


@pytest.fixture
def configured(settings):
    settings.OPENWEATHERMAP_API_KEY = FAKE_KEY


@pytest.fixture
def upstream():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


class TestTileBounds:
    @pytest.mark.parametrize(
        ("z", "x", "y", "valid"),
        [
            (0, 0, 0, True),
            (5, 31, 31, True),
            (5, 32, 0, False),
            (5, 0, 32, False),
            (-1, 0, 0, False),
            (MAX_TILE_ZOOM, 0, 0, True),
            (MAX_TILE_ZOOM + 1, 0, 0, False),
        ],
    )
    def test_xyz_bounds(self, z: int, x: int, y: int, valid: bool) -> None:
        assert tile_coordinates_are_valid(z, x, y) is valid


class TestRequestValidation:
    def test_unknown_layer_is_404(self, configured) -> None:
        response = Client().get(tile_url(layer="radar_new"))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "UNKNOWN_TILE_LAYER"

    def test_layer_allowlist_is_closed(self) -> None:
        """Only the four documented layers; nothing is passed through."""
        assert set(WEATHER_TILE_LAYERS) == {
            "precipitation_new",
            "clouds_new",
            "wind_new",
            "temp_new",
        }

    def test_zoom_beyond_supported_range_is_400(self, configured) -> None:
        response = Client().get(tile_url(z=MAX_TILE_ZOOM + 1, x=0, y=0))
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_TILE"

    def test_coordinate_outside_zoom_grid_is_400(self, configured) -> None:
        response = Client().get(tile_url(z=3, x=8, y=0))
        assert response.status_code == 400


class TestWithoutAKey:
    def test_tiles_are_unavailable_not_broken(self, settings) -> None:
        """No key means 503 with a stable code the UI can act on."""
        settings.OPENWEATHERMAP_API_KEY = ""
        response = Client().get(tile_url())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "WEATHER_TILES_NOT_CONFIGURED"

    def test_health_reports_absence(self, settings) -> None:
        settings.OPENWEATHERMAP_API_KEY = ""
        providers = Client().get("/api/v1/health").json()["providers"]
        assert providers["openweathermap_key_configured"] is False
        assert providers["weather_tiles"] is None


class TestProxy:
    def test_returns_the_upstream_png(self, configured, upstream) -> None:
        route = upstream.get(f"{UPSTREAM}/precipitation_new/5/7/12.png").mock(
            return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
        )

        response = Client().get(tile_url())

        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert response.content == PNG
        assert "max-age=" in response["Cache-Control"]
        assert route.called

    def test_key_is_sent_upstream_but_never_returned(self, configured, upstream) -> None:
        route = upstream.get(f"{UPSTREAM}/clouds_new/2/1/1.png").mock(
            return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
        )

        response = Client().get(tile_url(layer="clouds_new", z=2, x=1, y=1))

        sent = route.calls.last.request
        assert sent.url.params["appid"] == FAKE_KEY
        assert FAKE_KEY.encode() not in response.content
        assert FAKE_KEY not in str(response.headers)

    def test_second_request_is_served_from_cache(self, configured, upstream) -> None:
        route = upstream.get(f"{UPSTREAM}/wind_new/4/3/2.png").mock(
            return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
        )

        first = Client().get(tile_url(layer="wind_new", z=4, x=3, y=2))
        second = Client().get(tile_url(layer="wind_new", z=4, x=3, y=2))

        assert first.content == second.content == PNG
        assert route.call_count == 1

    def test_health_reports_presence_without_the_value(self, configured) -> None:
        response = Client().get("/api/v1/health")
        providers = response.json()["providers"]
        assert providers["openweathermap_key_configured"] is True
        assert providers["weather_tiles"] == "openweathermap"
        assert FAKE_KEY not in response.content.decode()


class TestUpstreamFailures:
    def test_rejected_key_is_502_and_still_secret(self, configured, upstream) -> None:
        upstream.get(f"{UPSTREAM}/temp_new/1/0/0.png").mock(
            return_value=httpx.Response(401, json={"message": "Invalid API key"})
        )

        response = Client().get(tile_url(layer="temp_new", z=1, x=0, y=0))

        assert response.status_code == 502
        body = response.json()["error"]
        assert body["code"] == "PROVIDER_AUTH_FAILED"
        assert FAKE_KEY not in response.content.decode()

    def test_rate_limit_is_forwarded_as_429(self, configured, upstream) -> None:
        upstream.get(f"{UPSTREAM}/temp_new/1/0/0.png").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "7"})
        )

        response = Client().get(tile_url(layer="temp_new", z=1, x=0, y=0))

        assert response.status_code == 429
        assert response["Retry-After"] == "7"

    def test_html_body_with_200_is_not_served_as_an_image(self, configured, upstream) -> None:
        upstream.get(f"{UPSTREAM}/temp_new/1/0/0.png").mock(
            return_value=httpx.Response(200, text="<html>oops</html>", headers={"Content-Type": "text/html"})
        )

        response = Client().get(tile_url(layer="temp_new", z=1, x=0, y=0))

        assert response.status_code == 502
        assert response.json()["error"]["code"] == "PROVIDER_INVALID_RESPONSE"

    def test_timeout_is_504(self, configured, upstream) -> None:
        upstream.get(f"{UPSTREAM}/temp_new/1/0/0.png").mock(
            side_effect=httpx.ReadTimeout("slow")
        )

        response = Client().get(tile_url(layer="temp_new", z=1, x=0, y=0))

        assert response.status_code == 504
