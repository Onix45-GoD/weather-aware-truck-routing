"""Detailed weather for one checkpoint: what it is like there now, and at ETA.

The route analysis already carries, per checkpoint, the three numbers the
risk engine needs. A driver who clicks a checkpoint wants more than that --
temperature, sky, humidity, visibility, what the next hours look like. That
comes from OpenWeatherMap through here, on demand, one checkpoint at a time.

Two guarantees worth stating:

* **It never influences the recommendation.** Nothing here reaches the
  domain. Risk levels come from Open-Meteo through the assessment's
  thresholds and are computed before this module is ever called.
* **The key stays on the server.** The browser asks our API with a
  coordinate; this module asks OpenWeatherMap with the key.

Caching keys on a coordinate rounded to two decimals (~1 km), the same
precision the Open-Meteo adapter uses to collapse near-identical
checkpoints. Observed conditions are reused for ten minutes, the forecast
for thirty -- OpenWeatherMap's own refresh cadence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache as django_cache

from apps.routing.domain.models import Coordinate
from apps.routing.providers.factory import get_conditions_provider
from apps.routing.providers.openmeteo import COORDINATE_PRECISION
from apps.routing.providers.openweathermap import (
    FORECAST_STEP_HOURS,
    Conditions,
    ForecastSlot,
)

__all__ = ["CheckpointWeather", "fetch_checkpoint_weather"]

#: Half a forecast step. An ETA further than this from the nearest slot is
#: still answered with that slot, but the gap is reported so the UI can say
#: "nearest forecast is 1h 20m from your ETA" rather than imply precision.
_HALF_STEP = timedelta(hours=FORECAST_STEP_HOURS / 2)


@dataclass(frozen=True, slots=True)
class CheckpointWeather:
    coordinate: Coordinate
    place_name: str | None
    current: Conditions
    forecast: tuple[ForecastSlot, ...]
    #: The checkpoint's ETA, when the caller supplied one.
    eta: datetime | None
    #: The forecast slot nearest the ETA, or None when the ETA is outside the
    #: forecast window. Never a slot from a different day passed off as ETA.
    at_eta: ForecastSlot | None
    #: Signed minutes from ETA to ``at_eta.at`` (positive = slot is later).
    eta_gap_minutes: int | None
    #: True when the ETA lies beyond the last slot the provider offers.
    eta_beyond_horizon: bool


def _ttl(name: str, default: int) -> int:
    return int(getattr(settings, "PROVIDER_CACHE_TTL", {}).get(name, default))


def _cache_key(kind: str, coordinate: Coordinate) -> str:
    lat = round(coordinate.latitude, COORDINATE_PRECISION)
    lon = round(coordinate.longitude, COORDINATE_PRECISION)
    return f"checkpoint-weather:{kind}:{lat:.{COORDINATE_PRECISION}f}:{lon:.{COORDINATE_PRECISION}f}"


def nearest_slot(
    slots: tuple[ForecastSlot, ...], eta: datetime
) -> tuple[ForecastSlot | None, int | None, bool]:
    """The slot closest to ``eta``, how far off it is, and whether ETA is past the end.

    Returns ``(None, None, beyond)`` when no slot is within half a step of the
    ETA, so the caller cannot accidentally present a stale slot as "at ETA".
    """
    if not slots:
        return None, None, True
    beyond = eta > slots[-1].at + _HALF_STEP
    best = min(slots, key=lambda slot: abs(slot.at - eta))
    gap = best.at - eta
    if abs(gap) > _HALF_STEP:
        return None, None, beyond
    return best, int(round(gap.total_seconds() / 60)), beyond


def fetch_checkpoint_weather(
    coordinate: Coordinate, eta: datetime | None = None
) -> CheckpointWeather:
    """Observed conditions and forecast for a point, with the ETA slot picked out.

    Raises :class:`~apps.routing.providers.errors.ProviderConfigurationError`
    when no key is configured and any other
    :class:`~apps.routing.providers.errors.ProviderError` the upstream caused.
    """
    current_key = _cache_key("current", coordinate)
    forecast_key = _cache_key("forecast", coordinate)
    current_ttl = _ttl("conditions", 600)
    forecast_ttl = _ttl("weather", 1800)

    cached_current = django_cache.get(current_key) if current_ttl > 0 else None
    cached_forecast = django_cache.get(forecast_key) if forecast_ttl > 0 else None

    if cached_current is None or cached_forecast is None:
        # The factory raises ProviderConfigurationError without a key; let
        # it propagate so the view can answer 503 with a stable code.
        with get_conditions_provider() as provider:
            if cached_current is None:
                cached_current = provider.current(coordinate)
                if current_ttl > 0:
                    django_cache.set(current_key, cached_current, current_ttl)
            if cached_forecast is None:
                cached_forecast = provider.forecast(coordinate)
                if forecast_ttl > 0:
                    django_cache.set(forecast_key, cached_forecast, forecast_ttl)

    current, place_name = cached_current
    forecast = cached_forecast

    at_eta: ForecastSlot | None = None
    gap: int | None = None
    beyond = False
    if eta is not None:
        at_eta, gap, beyond = nearest_slot(forecast, eta)

    return CheckpointWeather(
        coordinate=coordinate,
        place_name=place_name,
        current=current,
        forecast=forecast,
        eta=eta,
        at_eta=at_eta,
        eta_gap_minutes=gap,
        eta_beyond_horizon=beyond,
    )
