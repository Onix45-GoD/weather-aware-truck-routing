"""Open-Meteo hourly forecast adapter.

Units -- verified empirically, not assumed
------------------------------------------
Live calls made 2026-10-28 (see ``tests/fixtures/openmeteo/PROVENANCE.md``)
established the following, which the whole snow risk column depends on:

* ``snowfall`` defaults to **centimetres** and, with
  ``precipitation_unit=inch``, is returned in **inches**. The ratio between
  the two responses for identical hours was 2.54, i.e. a pure *depth* unit
  conversion.
* ``snowfall`` is **snow depth**, not liquid-water equivalent. In every snowy
  hour sampled, ``snowfall_cm / precipitation_mm`` was exactly 0.700 --
  Open-Meteo's documented fixed 7:1 snow-to-liquid ratio. Liquid equivalent
  would have given 0.1. This matters enormously: the assessment's snow
  thresholds (0.5/1.0/2.0/3.0 in/hr) are depth rates, and reading a liquid
  equivalent as depth would under-report snow risk by a factor of seven.
* The wind unit string is ``"mp/h"``, **not** ``"mph"``.

So requesting ``precipitation_unit=inch`` yields exactly the units the risk
engine wants and **no conversion is needed on the happy path**. Conversions
are implemented anyway and applied strictly from the unit metadata the
response declares, so if the provider ever ignores or changes a unit
parameter we convert correctly instead of silently misclassifying every
checkpoint. An unrecognised unit is a hard error, never a guess.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from apps.routing.domain.models import Coordinate, WeatherSample

from .base import HourlyForecast
from .errors import InvalidProviderResponseError
from .http import DEFAULT_RETRY_POLICY, ProviderHttpClient, RetryPolicy

__all__ = [
    "COORDINATE_PRECISION",
    "MAX_FORECAST_DAYS",
    "OpenMeteoWeatherProvider",
    "quantize",
]

PROVIDER_NAME: Final = "open-meteo"
FORECAST_URL: Final = "https://api.open-meteo.com/v1/forecast"

#: Hourly variables we request. `rain` and `showers` are separate in
#: Open-Meteo (large-scale vs convective) and are summed to get the total
#: liquid rate; using `rain` alone would under-report thunderstorms.
#: `precipitation` is deliberately NOT used as the rain rate -- it bundles
#: snow's liquid equivalent, which would double-count snowy hours.
HOURLY_VARIABLES: Final = (
    "wind_speed_10m",
    "wind_gusts_10m",
    "rain",
    "showers",
    "snowfall",
)

#: Open-Meteo's documented maximum forecast horizon.
MAX_FORECAST_DAYS: Final = 16

#: Conservative number of coordinates per bulk request. Open-Meteo does not
#: document a hard ceiling; this keeps URLs well inside normal length limits
#: and keeps one failure from taking out an entire analysis.
DEFAULT_CHUNK_SIZE: Final = 50

#: Decimal places used to collapse near-identical checkpoints into a single
#: lookup. Two places is ~1.1 km of latitude (~0.85 km of longitude at 40 N),
#: which is **finer than Open-Meteo's finest model grid** (~2 km), so it can
#: never merge two points the provider would have answered differently. A
#: coarser key -- 1 place is ~11 km -- genuinely would, which is why this is
#: pinned and tested rather than tuned for cache-hit rate.
COORDINATE_PRECISION: Final = 2

# --- Unit normalisation ----------------------------------------------------
# Each table maps a declared provider unit to **how many of that unit make one
# unit of the assessment's scale**, and conversion *divides* by it.
#
# Dividing rather than multiplying by a precomputed reciprocal is not a style
# choice, it is a correctness requirement. These factors (2.54, 25.4, 1.609344,
# 0.44704) are exact decimal definitions, so IEEE-754 division returns the
# exactly-rounded result: 5.08 / 2.54 == 2.0. Multiplying by (1 / 2.54) instead
# gives 1.9999999999999998 -- which classifies as HIGH rather than SEVERE.
# The error is one ULP, and it lands precisely on the risk thresholds, which is
# the one place it can change an answer.
_WIND_PER_MPH: Final[Mapping[str, float]] = {
    "mp/h": 1.0,  # Open-Meteo's actual string for miles per hour
    "mph": 1.0,
    "km/h": 1.609344,
    "kmh": 1.609344,
    "m/s": 0.44704,
    "ms": 0.44704,
    "kn": 0.8689762419006479,  # 1.609344 / 1.852
}

_RAIN_PER_INCH: Final[Mapping[str, float]] = {
    "inch": 1.0,
    "in": 1.0,
    "mm": 25.4,
}

#: Snow depth. Note the factor is 2.54 (cm per inch), *not* 25.4: snowfall is
#: a depth in centimetres, not a liquid depth in millimetres. Getting this
#: wrong by a factor of ten -- or treating it as liquid equivalent, a factor
#: of seven -- is the single most consequential unit error available here.
_SNOW_PER_INCH: Final[Mapping[str, float]] = {
    "inch": 1.0,
    "in": 1.0,
    "cm": 2.54,
    "mm": 25.4,
}


def quantize(coordinate: Coordinate, precision: int = COORDINATE_PRECISION) -> Coordinate:
    """Round a coordinate to the shared lookup grid. See :data:`COORDINATE_PRECISION`."""
    return Coordinate(
        latitude=round(coordinate.latitude, precision),
        longitude=round(coordinate.longitude, precision),
    )


def _scale(value: Any, divisor: float, *, field: str) -> float | None:
    """Convert one measurement, preserving missing values as ``None``.

    A missing reading must never become ``0.0``: zero means "calm and dry",
    which would classify as LOW risk and make a forecast gap look like good
    weather. ``None`` classifies as UNKNOWN instead.

    Division, never multiplication by a reciprocal -- see the unit tables.
    """
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InvalidProviderResponseError(
            f"hourly.{field}: expected a number or null, got {type(value).__name__}.",
            provider=PROVIDER_NAME,
        )
    number = float(value)
    if math.isnan(number):
        return None
    return number if divisor == 1.0 else number / divisor


def _divisor_for(
    units: Mapping[str, Any], variable: str, table: Mapping[str, float]
) -> float:
    """Look up the conversion divisor the response's own metadata implies."""
    declared = units.get(variable)
    if not isinstance(declared, str):
        raise InvalidProviderResponseError(
            f"hourly_units.{variable} is missing; cannot establish units.",
            provider=PROVIDER_NAME,
        )
    divisor = table.get(declared.strip().lower())
    if divisor is None:
        raise InvalidProviderResponseError(
            f"hourly_units.{variable} is {declared!r}, which this adapter "
            "cannot convert. Refusing to guess, because a wrong unit here "
            "silently corrupts every risk classification.",
            provider=PROVIDER_NAME,
        )
    return divisor


def _add_optional(left: float | None, right: float | None) -> float | None:
    """Sum two optional rates, treating "both missing" as missing."""
    if left is None and right is None:
        return None
    return (left or 0.0) + (right or 0.0)


def _parse_time(raw: Any) -> datetime:
    """Parse an Open-Meteo timestamp into timezone-aware UTC.

    With ``timezone=UTC`` the API emits naive strings like
    ``2026-10-28T06:00``; the offset is implied, so it is attached explicitly
    here. Everything downstream is timezone-aware UTC without exception.
    """
    if not isinstance(raw, str):
        raise InvalidProviderResponseError(
            f"hourly.time entries must be strings, got {type(raw).__name__}.",
            provider=PROVIDER_NAME,
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidProviderResponseError(
            f"hourly.time entry {raw!r} is not an ISO-8601 timestamp.",
            provider=PROVIDER_NAME,
        ) from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class OpenMeteoWeatherProvider:
    """Fetches hourly forecasts in bulk from Open-Meteo.

    Open-Meteo needs no API key for non-commercial use, so this adapter works
    out of the box -- there is no credential to misconfigure or leak.
    """

    name = PROVIDER_NAME

    def __init__(
        self,
        *,
        client: ProviderHttpClient | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        cache_ttl_seconds: int = 1800,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if chunk_size < 1:
            raise ValueError("chunk_size must be at least 1")
        self.chunk_size = chunk_size
        self.cache_ttl_seconds = cache_ttl_seconds
        # Injectable so tests are not coupled to the real clock.
        self._now = now or (lambda: datetime.now(UTC))
        self.client = client or ProviderHttpClient(
            provider=PROVIDER_NAME,
            retry_policy=retry_policy,
            cache_ttl_seconds=cache_ttl_seconds,
        )

    # -- public API ---------------------------------------------------------

    def hourly(
        self,
        coordinates: Sequence[Coordinate],
        start: datetime,
        end: datetime,
    ) -> tuple[HourlyForecast, ...]:
        """Hourly forecasts for every coordinate, aligned to the input order.

        Near-identical coordinates are collapsed into one lookup and the
        result shared, so overlapping route alternatives cost one request, not
        three. The returned tuple always has the same length as
        ``coordinates``.
        """
        if not coordinates:
            return ()
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if end < start:
            raise ValueError("end must not precede start")

        # Collapse duplicates, preserving first-seen order for determinism.
        unique: list[Coordinate] = []
        index_of: dict[tuple[float, float], int] = {}
        slot_for_input: list[int] = []
        for coordinate in coordinates:
            grid = quantize(coordinate)
            key = (grid.latitude, grid.longitude)
            if key not in index_of:
                index_of[key] = len(unique)
                unique.append(grid)
            slot_for_input.append(index_of[key])

        past_days, forecast_days = self._horizon(start, end)

        forecasts: list[HourlyForecast] = []
        for offset in range(0, len(unique), self.chunk_size):
            chunk = unique[offset : offset + self.chunk_size]
            forecasts.extend(self._fetch_chunk(chunk, past_days, forecast_days))

        if len(forecasts) != len(unique):  # pragma: no cover - defensive
            # _fetch_chunk already verifies the per-chunk count, so this can
            # only fire if that invariant is ever broken.
            raise InvalidProviderResponseError(
                f"expected {len(unique)} forecast series, got {len(forecasts)}.",
                provider=PROVIDER_NAME,
            )

        return tuple(forecasts[slot] for slot in slot_for_input)

    # -- internals ----------------------------------------------------------

    def _horizon(self, start: datetime, end: datetime) -> tuple[int, int]:
        """Translate an absolute window into Open-Meteo's day-count params.

        The API counts ``forecast_days`` forward from *today*, not from the
        requested start, so today's date is needed to size the window.
        """
        today: date = self._now().astimezone(UTC).date()
        start_date = start.astimezone(UTC).date()
        end_date = end.astimezone(UTC).date()

        past_days = max(0, min(2, (today - start_date).days))
        forecast_days = (end_date - today).days + 1
        forecast_days = max(1, min(MAX_FORECAST_DAYS, forecast_days))
        return past_days, forecast_days

    def _fetch_chunk(
        self, chunk: Sequence[Coordinate], past_days: int, forecast_days: int
    ) -> list[HourlyForecast]:
        params: dict[str, Any] = {
            "latitude": ",".join(f"{c.latitude:g}" for c in chunk),
            "longitude": ",".join(f"{c.longitude:g}" for c in chunk),
            "hourly": ",".join(HOURLY_VARIABLES),
            "timezone": "UTC",
            # Request the assessment's units directly: no conversion on the
            # happy path means no conversion drift before a threshold compare.
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "forecast_days": forecast_days,
        }
        if past_days:
            params["past_days"] = past_days

        payload = self.client.get_json(FORECAST_URL, params)

        # A single-coordinate request returns an object; multi-coordinate
        # returns an array. Normalise to a list either way.
        entries = payload if isinstance(payload, list) else [payload]
        if len(entries) != len(chunk):
            raise InvalidProviderResponseError(
                f"requested {len(chunk)} locations but received {len(entries)}.",
                provider=PROVIDER_NAME,
            )

        # Association is strictly positional. The provider snaps coordinates
        # to its model grid (39.74 comes back as 39.746895), so matching
        # responses back by coordinate equality would fail, and matching by
        # proximity could silently pair the wrong checkpoint with the wrong
        # forecast.
        return [
            self._parse_entry(entry, requested)
            for entry, requested in zip(entries, chunk)
        ]

    def _parse_entry(self, entry: Any, requested: Coordinate) -> HourlyForecast:
        if not isinstance(entry, Mapping):
            raise InvalidProviderResponseError(
                f"expected a forecast object, got {type(entry).__name__}.",
                provider=PROVIDER_NAME,
            )

        hourly = entry.get("hourly")
        units = entry.get("hourly_units")
        if not isinstance(hourly, Mapping) or not isinstance(units, Mapping):
            raise InvalidProviderResponseError(
                "forecast entry is missing `hourly` or `hourly_units`.",
                provider=PROVIDER_NAME,
            )

        wind_divisor = _divisor_for(units, "wind_speed_10m", _WIND_PER_MPH)
        gust_divisor = _divisor_for(units, "wind_gusts_10m", _WIND_PER_MPH)
        rain_divisor = _divisor_for(units, "rain", _RAIN_PER_INCH)
        showers_divisor = _divisor_for(units, "showers", _RAIN_PER_INCH)
        snow_divisor = _divisor_for(units, "snowfall", _SNOW_PER_INCH)

        raw_times = hourly.get("time")
        if not isinstance(raw_times, list):
            raise InvalidProviderResponseError(
                "hourly.time is missing or not a list.", provider=PROVIDER_NAME
            )

        columns = {
            name: self._column(hourly, name, len(raw_times))
            for name in HOURLY_VARIABLES
        }

        times: list[datetime] = []
        samples: list[WeatherSample] = []
        for index, raw_time in enumerate(raw_times):
            moment = _parse_time(raw_time)
            rain = _scale(columns["rain"][index], rain_divisor, field="rain")
            showers = _scale(columns["showers"][index], showers_divisor, field="showers")
            times.append(moment)
            samples.append(
                WeatherSample(
                    wind_mph=_scale(
                        columns["wind_speed_10m"][index],
                        wind_divisor,
                        field="wind_speed_10m",
                    ),
                    rain_in_hr=_add_optional(rain, showers),
                    snow_in_hr=_scale(
                        columns["snowfall"][index], snow_divisor, field="snowfall"
                    ),
                    # Carried for display only. Classification uses sustained
                    # wind, per docs/decisions.md D2.
                    wind_gust_mph=_scale(
                        columns["wind_gusts_10m"][index],
                        gust_divisor,
                        field="wind_gusts_10m",
                    ),
                    forecast_time=moment,
                )
            )

        if any(
            later < earlier for earlier, later in zip(times, times[1:])
        ):  # pragma: no cover - provider always sends ascending series
            raise InvalidProviderResponseError(
                "hourly.time is not in ascending order.", provider=PROVIDER_NAME
            )

        return HourlyForecast(
            coordinate=requested,
            resolved_coordinate=self._resolved_coordinate(entry, requested),
            times=tuple(times),
            samples=tuple(samples),
            provider=PROVIDER_NAME,
            elevation_m=_optional_float(entry.get("elevation")),
        )

    @staticmethod
    def _column(hourly: Mapping[str, Any], name: str, expected: int) -> list[Any]:
        """Fetch one hourly series, tolerating an entirely absent variable.

        A variable the provider omitted becomes a column of ``None`` -- i.e.
        UNKNOWN for every hour -- rather than an exception, so one unavailable
        measurement does not discard an otherwise usable forecast.
        """
        column = hourly.get(name)
        if column is None:
            return [None] * expected
        if not isinstance(column, list):
            raise InvalidProviderResponseError(
                f"hourly.{name} must be a list, got {type(column).__name__}.",
                provider=PROVIDER_NAME,
            )
        if len(column) != expected:
            raise InvalidProviderResponseError(
                f"hourly.{name} has {len(column)} values but hourly.time has "
                f"{expected}.",
                provider=PROVIDER_NAME,
            )
        return column

    @staticmethod
    def _resolved_coordinate(entry: Mapping[str, Any], fallback: Coordinate) -> Coordinate:
        latitude = _optional_float(entry.get("latitude"))
        longitude = _optional_float(entry.get("longitude"))
        if latitude is None or longitude is None:
            return fallback
        try:
            return Coordinate(latitude=latitude, longitude=longitude)
        except ValueError as exc:
            raise InvalidProviderResponseError(
                f"forecast entry reports an out-of-range position: {exc}",
                provider=PROVIDER_NAME,
            ) from exc


def _optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def forecast_window(
    departure: datetime, latest_eta: datetime, *, slider_hours: int = 48
) -> tuple[datetime, datetime]:
    """The window a full analysis needs.

    Wide enough to cover both the slowest route's arrival and the 0-48 hour
    corridor slider, whichever extends further.
    """
    if departure.tzinfo is None or latest_eta.tzinfo is None:
        raise ValueError("departure and latest_eta must be timezone-aware")
    return departure, max(latest_eta, departure + timedelta(hours=slider_hours))
