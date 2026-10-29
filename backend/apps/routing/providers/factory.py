"""Provider selection from Django settings.

A single place that turns configuration into concrete adapters, so the
orchestration service in Milestone 3 asks for "the routing provider" rather
than knowing which vendor is configured.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from .base import GeocodingProvider, RoutingProvider, WeatherProvider
from .errors import ProviderConfigurationError
from .fixtures import (
    FixtureGeocodingProvider,
    FixtureRoutingProvider,
    FixtureWeatherProvider,
)
from .openmeteo import OpenMeteoWeatherProvider
from .tomtom import TomTomGeocodingProvider, TomTomRoutingProvider

__all__ = [
    "get_geocoding_provider",
    "get_routing_provider",
    "get_weather_provider",
    "provider_status",
]


def _ttl(name: str, default: int) -> int:
    return int(getattr(settings, "PROVIDER_CACHE_TTL", {}).get(name, default))


def _tomtom_key() -> str:
    key = getattr(settings, "TOMTOM_API_KEY", "") or ""
    if not key.strip():
        raise ProviderConfigurationError(
            "TOMTOM_API_KEY is not set. Set it in the environment, or select "
            "the `fixtures` provider to run without credentials.",
            provider="tomtom",
        )
    return key


def get_geocoding_provider(name: str | None = None) -> GeocodingProvider:
    """Build the configured geocoding provider."""
    choice = (name or getattr(settings, "GEOCODING_PROVIDER", "fixtures")).lower()
    if choice == "fixtures":
        return FixtureGeocodingProvider()
    if choice == "tomtom":
        return TomTomGeocodingProvider(
            _tomtom_key(), cache_ttl_seconds=_ttl("geocoding", 60 * 60 * 24 * 30)
        )
    raise ProviderConfigurationError(
        f"Unknown geocoding provider {choice!r}. Expected 'tomtom' or 'fixtures'."
    )


def get_routing_provider(name: str | None = None) -> RoutingProvider:
    """Build the configured routing provider."""
    choice = (name or getattr(settings, "ROUTING_PROVIDER", "fixtures")).lower()
    if choice == "fixtures":
        return FixtureRoutingProvider()
    if choice == "tomtom":
        return TomTomRoutingProvider(
            _tomtom_key(), cache_ttl_seconds=_ttl("routing", 600)
        )
    raise ProviderConfigurationError(
        f"Unknown routing provider {choice!r}. Expected 'tomtom' or 'fixtures'."
    )


def get_weather_provider(name: str | None = None) -> WeatherProvider:
    """Build the configured weather provider."""
    choice = (name or getattr(settings, "WEATHER_PROVIDER", "open-meteo")).lower()
    if choice in {"open-meteo", "openmeteo"}:
        return OpenMeteoWeatherProvider(cache_ttl_seconds=_ttl("weather", 1800))
    if choice == "fixtures":
        return FixtureWeatherProvider()
    raise ProviderConfigurationError(
        f"Unknown weather provider {choice!r}. Expected 'open-meteo' or 'fixtures'."
    )


def provider_status() -> dict[str, Any]:
    """Report which providers are selected and whether credentials exist.

    Reports only the *presence* of a key, never any part of its value, so this
    is safe to expose on a health endpoint and safe to log.
    """
    key = getattr(settings, "TOMTOM_API_KEY", "") or ""
    return {
        "geocoding": getattr(settings, "GEOCODING_PROVIDER", "fixtures"),
        "routing": getattr(settings, "ROUTING_PROVIDER", "fixtures"),
        "weather": getattr(settings, "WEATHER_PROVIDER", "open-meteo"),
        "tomtom_key_configured": bool(key.strip()),
        "open_meteo_requires_key": False,
    }
