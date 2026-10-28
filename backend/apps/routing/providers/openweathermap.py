"""OpenWeatherMap adapters: map tiles and point conditions, key kept server-side.

Two things come from OpenWeatherMap, and both go through this server so the
browser never holds the key:

* **Raster tiles** (precipitation, clouds, wind, temperature) for the map
  overlay. The tile URL carries the key as a query parameter, so a tile URL
  the browser can read would be a key the browser can read.
* **Point conditions** for a selected checkpoint: what it is like there
  *right now* plus the 5-day / 3-hourly forecast, so a driver clicking a
  checkpoint sees real weather -- temperature, sky, humidity, visibility --
  not just the three numbers the risk engine consumes.

What these are -- and are not. The risk colouring along the route is the
Open-Meteo *hourly* forecast at each checkpoint's ETA, through the
assessment's thresholds. OpenWeatherMap here is descriptive context. It is
never fed into the risk engine, so the recommendation cannot change by
switching this key on or off. The UI labels current conditions "now" and
the forecast slot "at ETA" so the two are not mistaken for each other.

This module is transport only. Validation, caching and the decision to run
at all live in the services layer, so this adapter -- like every other --
has no Django dependency and is usable from a plain script.

Tiles deliberately have no retry loop: a map requests dozens per view and
retries missing ones itself on the next pan, so a tile that fails once is
cheaper to drop than to wait on.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Final

import httpx

from apps.routing.domain.models import Coordinate

from .errors import (
    InvalidProviderResponseError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from .http import DEFAULT_TIMEOUT, ProviderHttpClient, _parse_retry_after

__all__ = [
    "Conditions",
    "ForecastSlot",
    "MAX_TILE_ZOOM",
    "OpenWeatherMapConditionsProvider",
    "OpenWeatherMapTileProvider",
    "PointWeather",
    "WEATHER_TILE_LAYERS",
    "tile_coordinates_are_valid",
]

PROVIDER_NAME: Final = "openweathermap"

# --- Tiles ------------------------------------------------------------------

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


# --- Point conditions -------------------------------------------------------

CONDITIONS_BASE_URL: Final = "https://api.openweathermap.org/data/2.5"

#: Imperial is requested so temperature and wind arrive in the units the rest
#: of the dashboard uses (°F, mph). Precipitation is *always* millimetres
#: from this API regardless of the units parameter, and visibility is always
#: metres; both are converted below, by exact factors.
MM_PER_INCH: Final = 25.4
METRES_PER_MILE: Final = 1609.344

#: The free forecast product is 3-hourly over five days. Documented, and the
#: only forecast horizon the key-gated UI should promise.
FORECAST_STEP_HOURS: Final = 3


@dataclass(frozen=True, slots=True)
class Conditions:
    """Observed conditions at one point, as of ``observed_at``."""

    observed_at: datetime
    condition: str
    description: str
    icon: str
    temp_f: float | None
    feels_like_f: float | None
    wind_mph: float | None
    wind_gust_mph: float | None
    wind_deg: int | None
    humidity_pct: int | None
    pressure_hpa: int | None
    visibility_miles: float | None
    cloud_pct: int | None
    rain_in_last_hour: float | None
    snow_in_last_hour: float | None
    sunrise: datetime | None
    sunset: datetime | None


@dataclass(frozen=True, slots=True)
class ForecastSlot:
    """One 3-hour forecast step."""

    at: datetime
    condition: str
    description: str
    icon: str
    temp_f: float | None
    feels_like_f: float | None
    precipitation_probability: float | None
    wind_mph: float | None
    wind_gust_mph: float | None
    wind_deg: int | None
    humidity_pct: int | None
    cloud_pct: int | None
    rain_in_3h: float | None
    snow_in_3h: float | None


@dataclass(frozen=True, slots=True)
class PointWeather:
    coordinate: Coordinate
    place_name: str | None
    current: Conditions
    forecast: tuple[ForecastSlot, ...]


def _number(value: Any) -> float | None:
    """A float or None -- never a guess. Strings are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(round(number))


def _instant(value: Any) -> datetime | None:
    number = _number(value)
    return None if number is None else datetime.fromtimestamp(number, tz=UTC)


def _inches(mm: Any) -> float | None:
    number = _number(mm)
    return None if number is None else number / MM_PER_INCH


def _miles(metres: Any) -> float | None:
    number = _number(metres)
    return None if number is None else number / METRES_PER_MILE


def _sky(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    """``(condition, description, icon)`` from a ``weather`` list entry."""
    weather = entry.get("weather")
    first = weather[0] if isinstance(weather, list) and weather else {}
    if not isinstance(first, Mapping):
        first = {}
    return (
        str(first.get("main") or "Unknown"),
        str(first.get("description") or "unknown"),
        str(first.get("icon") or ""),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_conditions(payload: Mapping[str, Any]) -> Conditions:
    observed_at = _instant(payload.get("dt"))
    if observed_at is None:
        raise InvalidProviderResponseError(
            f"{PROVIDER_NAME} current-weather response has no observation time.",
            provider=PROVIDER_NAME,
        )
    main = _mapping(payload.get("main"))
    wind = _mapping(payload.get("wind"))
    sys_ = _mapping(payload.get("sys"))
    condition, description, icon = _sky(payload)
    return Conditions(
        observed_at=observed_at,
        condition=condition,
        description=description,
        icon=icon,
        temp_f=_number(main.get("temp")),
        feels_like_f=_number(main.get("feels_like")),
        wind_mph=_number(wind.get("speed")),
        wind_gust_mph=_number(wind.get("gust")),
        wind_deg=_integer(wind.get("deg")),
        humidity_pct=_integer(main.get("humidity")),
        pressure_hpa=_integer(main.get("pressure")),
        visibility_miles=_miles(payload.get("visibility")),
        cloud_pct=_integer(_mapping(payload.get("clouds")).get("all")),
        rain_in_last_hour=_inches(_mapping(payload.get("rain")).get("1h")),
        snow_in_last_hour=_inches(_mapping(payload.get("snow")).get("1h")),
        sunrise=_instant(sys_.get("sunrise")),
        sunset=_instant(sys_.get("sunset")),
    )


def _parse_slot(entry: Mapping[str, Any]) -> ForecastSlot | None:
    at = _instant(entry.get("dt"))
    if at is None:
        return None
    main = _mapping(entry.get("main"))
    wind = _mapping(entry.get("wind"))
    condition, description, icon = _sky(entry)
    return ForecastSlot(
        at=at,
        condition=condition,
        description=description,
        icon=icon,
        temp_f=_number(main.get("temp")),
        feels_like_f=_number(main.get("feels_like")),
        precipitation_probability=_number(entry.get("pop")),
        wind_mph=_number(wind.get("speed")),
        wind_gust_mph=_number(wind.get("gust")),
        wind_deg=_integer(wind.get("deg")),
        humidity_pct=_integer(main.get("humidity")),
        cloud_pct=_integer(_mapping(entry.get("clouds")).get("all")),
        rain_in_3h=_inches(_mapping(entry.get("rain")).get("3h")),
        snow_in_3h=_inches(_mapping(entry.get("snow")).get("3h")),
    )


@dataclass
class OpenWeatherMapConditionsProvider:
    """Current conditions and the 5-day / 3-hourly forecast for one point."""

    api_key: str
    base_url: str = CONDITIONS_BASE_URL
    http: ProviderHttpClient | None = None

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("OpenWeatherMap conditions provider needs an API key")
        if self.http is None:
            # Caching is the service's job: it keys on a rounded coordinate so
            # two nearby checkpoints share one lookup, which the transport
            # cannot know to do.
            self.http = ProviderHttpClient(provider=PROVIDER_NAME, cache_ttl_seconds=0)

    def close(self) -> None:
        if self.http is not None:
            self.http.close()

    def __enter__(self) -> OpenWeatherMapConditionsProvider:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _params(self, coordinate: Coordinate) -> dict[str, Any]:
        return {
            "lat": f"{coordinate.latitude:.4f}",
            "lon": f"{coordinate.longitude:.4f}",
            "units": "imperial",
            "appid": self.api_key,
        }

    def current(self, coordinate: Coordinate) -> tuple[Conditions, str | None]:
        """Observed conditions plus the provider's nearest place name."""
        assert self.http is not None
        payload = self.http.get_json(f"{self.base_url}/weather", self._params(coordinate))
        if not isinstance(payload, Mapping):
            raise InvalidProviderResponseError(
                f"{PROVIDER_NAME} current-weather response is not an object.",
                provider=PROVIDER_NAME,
            )
        name = payload.get("name")
        return _parse_conditions(payload), (str(name) if name else None)

    def forecast(self, coordinate: Coordinate) -> tuple[ForecastSlot, ...]:
        """Ascending 3-hourly slots covering roughly the next five days."""
        assert self.http is not None
        payload = self.http.get_json(f"{self.base_url}/forecast", self._params(coordinate))
        entries = payload.get("list") if isinstance(payload, Mapping) else None
        if not isinstance(entries, list):
            raise InvalidProviderResponseError(
                f"{PROVIDER_NAME} forecast response has no `list`.",
                provider=PROVIDER_NAME,
            )
        slots = [
            slot
            for entry in entries
            if isinstance(entry, Mapping)
            if (slot := _parse_slot(entry)) is not None
        ]
        slots.sort(key=lambda slot: slot.at)
        return tuple(slots)
