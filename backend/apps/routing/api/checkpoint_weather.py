"""Validation and response shaping for `GET /api/v1/checkpoint-weather`.

Kept apart from the route-analysis serializers: this endpoint has its own,
much smaller contract, and the two should be readable independently.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from rest_framework import serializers

from apps.routing.domain.models import Coordinate
from apps.routing.services.checkpoint_weather import CheckpointWeather

from .serializers import TripDateTimeField

__all__ = ["CheckpointWeatherQuerySerializer", "serialise_checkpoint_weather"]


class CheckpointWeatherQuerySerializer(serializers.Serializer):
    """`?lat=&lon=&at=` -- a point and, optionally, the ETA to look up."""

    lat = serializers.FloatField(min_value=-90.0, max_value=90.0)
    lon = serializers.FloatField(min_value=-180.0, max_value=180.0)
    #: Aware ISO 8601. The analysis response emits every ETA with an offset,
    #: so a naive value here is a client bug, not something to guess about.
    #: `TripDateTimeField` keeps a naive value naive; DRF's own field would
    #: silently localise it and the check below could never fire.
    at = TripDateTimeField(required=False, allow_null=True)

    def validate_at(self, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise serializers.ValidationError(
                "`at` must carry a UTC offset, e.g. 2026-11-02T18:00:00+00:00."
            )
        return None if value is None else value.astimezone(UTC)

    def coordinate(self) -> Coordinate:
        return Coordinate(
            latitude=self.validated_data["lat"], longitude=self.validated_data["lon"]
        )

    def eta(self) -> datetime | None:
        return self.validated_data.get("at")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _slot(slot: Any) -> dict[str, Any]:
    data = asdict(slot)
    data["at"] = _iso(slot.at)
    for key in ("temp_f", "feels_like_f", "wind_mph", "wind_gust_mph"):
        data[key] = _round(data[key], 1)
    for key in ("rain_in_3h", "snow_in_3h"):
        data[key] = _round(data[key], 3)
    data["precipitation_probability"] = _round(data["precipitation_probability"], 2)
    return data


def serialise_checkpoint_weather(result: CheckpointWeather) -> dict[str, Any]:
    current = asdict(result.current)
    for key in ("observed_at", "sunrise", "sunset"):
        current[key] = _iso(getattr(result.current, key))
    for key in ("temp_f", "feels_like_f", "wind_mph", "wind_gust_mph", "visibility_miles"):
        current[key] = _round(current[key], 1)
    for key in ("rain_in_last_hour", "snow_in_last_hour"):
        current[key] = _round(current[key], 3)

    return {
        "source": "openweathermap",
        "coordinate": {
            "latitude": round(result.coordinate.latitude, 6),
            "longitude": round(result.coordinate.longitude, 6),
        },
        "place_name": result.place_name,
        "current": current,
        "forecast": [_slot(slot) for slot in result.forecast],
        "eta": _iso(result.eta),
        "at_eta": None if result.at_eta is None else _slot(result.at_eta),
        "eta_gap_minutes": result.eta_gap_minutes,
        "eta_beyond_horizon": result.eta_beyond_horizon,
        "forecast_horizon_end": _iso(result.forecast[-1].at) if result.forecast else None,
    }
