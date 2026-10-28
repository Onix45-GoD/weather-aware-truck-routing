"""Validation and response shaping for `POST /api/v1/corridor-forecast`.

The request is the selected route's checkpoints sent back as the analysis
emitted them -- index, position, distance -- plus the analysis reference
time and the cargo weight. Geometry is *not* resent; the corridor is sampled
at checkpoints and nothing else. The response is 49 hourly frames, each
holding every checkpoint's measurements and classification for that hour,
in the same `weather` / `risk` shapes the route-analysis response uses, so
the client needs no second set of types.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rest_framework import serializers

from apps.routing.domain.models import Coordinate
from apps.routing.services.analysis import MAX_CHECKPOINTS_PER_ROUTE
from apps.routing.services.corridor import CorridorCheckpoint, CorridorForecast

from .serializers import (
    MAX_LOAD_WEIGHT_LB,
    TimezoneField,
    TripDateTimeField,
    _iso,
    _local,
    _serialise_risk,
    _serialise_weather,
)

__all__ = ["CorridorForecastRequestSerializer", "serialise_corridor"]


class _CheckpointSerializer(serializers.Serializer):
    index = serializers.IntegerField(min_value=0)
    latitude = serializers.FloatField(min_value=-90.0, max_value=90.0)
    longitude = serializers.FloatField(min_value=-180.0, max_value=180.0)
    distance_from_origin_miles = serializers.FloatField(min_value=0.0)


class CorridorForecastRequestSerializer(serializers.Serializer):
    """The selected route, as checkpoints, plus what the analysis was run with."""

    #: The analysis's `effective_departure_at`. Frame +0 is this instant.
    reference_at = TripDateTimeField()
    load_weight_lb = serializers.FloatField(min_value=1.0, max_value=MAX_LOAD_WEIGHT_LB)
    checkpoints = _CheckpointSerializer(many=True, min_length=2, max_length=MAX_CHECKPOINTS_PER_ROUTE)
    #: Echoed back untouched so the client can match a response to a route.
    route_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    #: Display-only: lets the response carry local renderings of each frame.
    timezone = TimezoneField(required=False, allow_null=True)

    def validate_reference_at(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise serializers.ValidationError(
                "`reference_at` must carry a UTC offset; use the analysis's "
                "`effective_departure_at` as returned."
            )
        return value.astimezone(UTC)

    def validate_checkpoints(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        distances = [point["distance_from_origin_miles"] for point in value]
        if any(later < earlier for earlier, later in zip(distances, distances[1:])):
            raise serializers.ValidationError(
                "checkpoints must be in route order: distances may not decrease."
            )
        if distances[-1] <= 0.0:
            raise serializers.ValidationError("the route must have positive length.")
        indexes = [point["index"] for point in value]
        if any(later <= earlier for earlier, later in zip(indexes, indexes[1:])):
            raise serializers.ValidationError(
                "checkpoint indexes must be unique and ascending."
            )
        return value

    def corridor_checkpoints(self) -> tuple[CorridorCheckpoint, ...]:
        return tuple(
            CorridorCheckpoint(
                index=point["index"],
                coordinate=Coordinate(
                    latitude=point["latitude"], longitude=point["longitude"]
                ),
                distance_from_origin_miles=point["distance_from_origin_miles"],
            )
            for point in self.validated_data["checkpoints"]
        )


def _frame_summary(metrics: Any) -> dict[str, Any]:
    """The per-frame risk-mile breakdown, straight from the domain's summary.

    `duration_seconds` is deliberately absent: the corridor shell gives the
    summary a placeholder duration, and reporting it would be a lie.
    """
    return {
        "low_miles": round(metrics.low_miles, 2),
        "moderate_miles": round(metrics.moderate_miles, 2),
        "high_miles": round(metrics.high_miles, 2),
        "severe_miles": round(metrics.severe_miles, 2),
        "no_travel_miles": round(metrics.no_travel_miles, 2),
        "unknown_miles": round(metrics.unknown_miles, 2),
        "average_risk": None if metrics.average_risk is None else round(metrics.average_risk, 3),
        "max_risk": metrics.max_risk.value,
        "coverage_pct": round(metrics.coverage_pct, 1),
        "blocked": metrics.blocked,
    }


def serialise_corridor(
    result: CorridorForecast,
    *,
    route_id: str | None,
    zone_name: str | None,
) -> dict[str, Any]:
    return {
        "route_id": route_id,
        "reference_at": _iso(result.reference_at),
        "reference_at_local": _local(result.reference_at, zone_name),
        "timezone": zone_name,
        "step_hours": result.step_hours,
        "horizon_hours": result.horizon_hours,
        "provider": result.provider,
        "load_weight_lb": result.load_weight_lb,
        "forecast_window": {
            "start": _iso(result.forecast_window_start),
            "end": _iso(result.forecast_window_end),
        },
        "checkpoints": [
            {
                "index": point.index,
                "latitude": round(point.coordinate.latitude, 6),
                "longitude": round(point.coordinate.longitude, 6),
                "distance_from_origin_miles": round(point.distance_from_origin_miles, 2),
                "segment_miles": round(miles, 3),
            }
            for point, miles in zip(result.checkpoints, result.segment_miles)
        ],
        "frames": [
            {
                "hour": frame.hour,
                "at": _iso(frame.at),
                "at_local": _local(frame.at, zone_name),
                "available": frame.available,
                "unavailable_reason": frame.unavailable_reason,
                "summary": _frame_summary(frame.metrics),
                "checkpoints": [
                    {
                        "index": assessed.checkpoint.index,
                        "weather": _serialise_weather(assessed.weather),
                        "risk": _serialise_risk(assessed.risk),
                    }
                    for assessed in frame.assessed
                ],
            }
            for frame in result.frames
        ],
        "available_hours": result.available_hours,
        "warnings": [
            {"code": warning.code, "message": warning.message}
            for warning in result.warnings
        ],
    }
