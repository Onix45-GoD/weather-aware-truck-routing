"""OpenWeatherMap weather-map tiles, fetched so the key never leaves the server.

OpenWeatherMap's raster tiles -- precipitation, clouds, wind, temperature --
are fetched by URL, and that URL carries the API key as a query parameter.
If the browser requested them directly the key would sit in every tile URL,
readable by anyone who opens DevTools. So the browser asks *this* server for
``/api/v1/weather-tiles/<layer>/<z>/<x>/<y>.png``; the server appends the
key, fetches the tile and returns the bytes. The frontend never sees a
credential, which is the same rule the TomTom adapters follow.

This module is the transport only. Validation of what the browser asked for,
caching, and the decision to run at all live in
:mod:`apps.routing.services.weather_tiles`, so this adapter -- like every
other -- has no Django dependency and is usable from a plain script.

What these tiles are -- and are not. They show **current** conditions, not
the forecast at a checkpoint's ETA. The route risk colouring is the forecast;
the overlay is situational awareness. The UI labels it as "now" so the two
are not mistaken for each other.

Deliberately no retry loop: a map requests dozens of tiles per view and
retries missing ones itself on the next pan, so a tile that fails once is
cheaper to drop than to wait on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

import httpx

from .errors import (
    InvalidProviderResponseError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from .http import DEFAULT_TIMEOUT, _parse_retry_after

__all__ = [
    "MAX_TILE_ZOOM",
    "OpenWeatherMapTileProvider",
    "WEATHER_TILE_LAYERS",
    "tile_coordinates_are_valid",
]

PROVIDER_NAME: Final = "openweathermap"

#: The layers the API will proxy, with display labels. An allowlist rather
#: than pass-through: the path segment comes from the browser, and the only
#: thing it should ever be able to select is one of these.
WEATHER_TILE_LAYERS: Final = MappingProxyType(
    {
        "precipitation_new": "Precipitation",
        "clouds_new": "Clouds",
        "wind_new": "Wind speed",
        "temp_new": "Temperature",
    }
)

#: Weather tiles carry no detail beyond this zoom -- the data is on a grid far
#: coarser than a street map -- and the free tier is quota-limited, so there
#: is no reason to let a client fan out to zoom 18.
MAX_TILE_ZOOM: Final = 12


def tile_coordinates_are_valid(z: int, x: int, y: int) -> bool:
    """Standard XYZ bounds: ``0 <= x, y < 2**z`` within the supported zooms."""
    if not 0 <= z <= MAX_TILE_ZOOM:
        return False
    span = 1 << z
    return 0 <= x < span and 0 <= y < span


@dataclass
class OpenWeatherMapTileProvider:
    """Fetch one weather-map tile, never exposing the key."""

    api_key: str
    base_url: str = "https://tile.openweathermap.org/map"
    timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)
    client: httpx.Client | None = None
    _owns_client: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OpenWeatherMap tile provider needs an API key")
        if self.client is None:
            self.client = httpx.Client(timeout=self.timeout, follow_redirects=True)
            self._owns_client = True

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    def __enter__(self) -> OpenWeatherMapTileProvider:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_tile(self, layer: str, z: int, x: int, y: int) -> bytes:
        """Return the PNG bytes for one tile.

        Raises ``ValueError`` for a layer or coordinate outside the allowlist
        -- a caller bug, since the service validates first -- and a typed
        :class:`~apps.routing.providers.errors.ProviderError` for anything
        the upstream did.
        """
        if layer not in WEATHER_TILE_LAYERS:
            raise ValueError(f"unknown weather tile layer {layer!r}")
        if not tile_coordinates_are_valid(z, x, y):
            raise ValueError(f"tile {z}/{x}/{y} is out of range")
        return self._fetch(f"{self.base_url}/{layer}/{z}/{x}/{y}.png")

    def _fetch(self, url: str) -> bytes:
        assert self.client is not None  # set in __post_init__
        try:
            # `appid` is OpenWeatherMap's name for the key. It is in
            # `SECRET_PARAM_NAMES`, so the shared log filter masks it.
            response = self.client.get(url, params={"appid": self.api_key})
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"{PROVIDER_NAME} did not return the tile within the timeout.",
                provider=PROVIDER_NAME,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                f"Could not reach {PROVIDER_NAME}: {type(exc).__name__}.",
                provider=PROVIDER_NAME,
            ) from exc

        status = response.status_code
        if status in (401, 403):
            raise ProviderAuthError(
                f"{PROVIDER_NAME} rejected our credentials (HTTP {status}). "
                "Check the configured API key.",
                provider=PROVIDER_NAME,
            )
        if status == 429:
            raise ProviderRateLimitError(
                f"{PROVIDER_NAME} rate limit reached (HTTP 429).",
                provider=PROVIDER_NAME,
                retry_after_seconds=_parse_retry_after(
                    response.headers.get("Retry-After")
                ),
            )
        if status >= 500:
            raise ProviderUnavailableError(
                f"{PROVIDER_NAME} returned HTTP {status}.", provider=PROVIDER_NAME
            )
        if status >= 400:
            raise InvalidProviderResponseError(
                f"{PROVIDER_NAME} rejected the tile request (HTTP {status}).",
                provider=PROVIDER_NAME,
            )

        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            # An HTML error page with a 200 would otherwise be served to the
            # map as a broken image; better to fail loudly.
            raise InvalidProviderResponseError(
                f"{PROVIDER_NAME} returned {content_type or 'no content type'} "
                "where an image was expected.",
                provider=PROVIDER_NAME,
            )
        return response.content
