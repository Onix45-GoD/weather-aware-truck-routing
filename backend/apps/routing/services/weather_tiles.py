"""Weather-map tile delivery: validate, cache, fetch.

The view asks this module for a tile and gets bytes back. Everything between
-- the layer allowlist, XYZ bounds, the cache, building and closing the
provider -- lives here so the view stays a thin HTTP shell and the provider
stays a Django-free transport.

The allowlist and bounds check are re-exported from the provider module so
the view can validate *before* calling, and answer 404/400 with a useful
message rather than a generic failure.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache as django_cache

from apps.routing.providers.factory import get_weather_tile_provider
from apps.routing.providers.openweathermap import (
    WEATHER_TILE_LAYERS,
    tile_coordinates_are_valid,
)

__all__ = [
    "WEATHER_TILE_LAYERS",
    "WeatherTile",
    "fetch_weather_tile",
    "tile_coordinates_are_valid",
]


@dataclass(frozen=True, slots=True)
class WeatherTile:
    png: bytes
    #: How long the browser may reuse this tile. Mirrors the server cache so
    #: the two never disagree about freshness.
    max_age_seconds: int


def _ttl_seconds() -> int:
    return int(getattr(settings, "PROVIDER_CACHE_TTL", {}).get("weather_tiles", 600))


def fetch_weather_tile(layer: str, z: int, x: int, y: int) -> WeatherTile:
    """Return one tile, from cache when possible.

    Raises ``ValueError`` for an unknown layer or out-of-range coordinate,
    :class:`~apps.routing.providers.errors.ProviderConfigurationError` when
    no key is configured, and any other
    :class:`~apps.routing.providers.errors.ProviderError` the upstream caused.
    """
    if layer not in WEATHER_TILE_LAYERS:
        raise ValueError(f"unknown weather tile layer {layer!r}")
    if not tile_coordinates_are_valid(z, x, y):
        raise ValueError(f"tile {z}/{x}/{y} is out of range")

    ttl = _ttl_seconds()
    # Built from public coordinates only; the credential is not part of it
    # and so can never be recovered from cache storage.
    key = f"weather-tile:{layer}:{z}:{x}:{y}"

    if ttl > 0:
        cached = django_cache.get(key)
        if cached is not None:
            return WeatherTile(png=cached, max_age_seconds=ttl)

    with get_weather_tile_provider() as provider:
        png = provider.fetch_tile(layer, z, x, y)

    if ttl > 0:
        django_cache.set(key, png, ttl)
    return WeatherTile(png=png, max_age_seconds=ttl)
