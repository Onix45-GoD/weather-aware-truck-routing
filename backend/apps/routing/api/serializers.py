"""Request validation and response shaping for the route-analysis endpoint.

The response contract is written for a typed React client: stable field
names, explicit nulls rather than omitted keys, enum values as fixed strings,
and no provider-specific object ever reaching the wire.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework import serializers

from apps.routing.domain.geo import simplify_polyline
from apps.routing.domain.models import CheckpointInterval, RiskLevel
from apps.routing.services.analysis import (
    GEOMETRY_TOLERANCE_MILES,
    MAX_FORECAST_OFFSET_HOURS,
    AnalysedRoute,
    AnalysisRequest,
    AnalysisResult,
)

__all__ = [
    "RouteAnalysisRequestSerializer",
    "TimezoneField",
    "TripDateTimeField",
    "serialise_analysis",
]

#: Hard ceiling, far above any legal gross combination weight (80,000 lb
#: federal limit). Rejects transcription errors like an extra zero.
MAX_LOAD_WEIGHT_LB = 200_000

#: A trailing UTC offset: `Z`, `+05:30`, `-0600`.
_HAS_UTC_OFFSET = re.compile(r"(?:Z|z|[+-]\d{2}:?\d{2})$")


class TripDateTimeField(serializers.DateTimeField):
    """Parses a departure time, preserving whether it carried an offset.

    DRF will not do: with `USE_TZ = True` it *localises* a naive timestamp
    into the server's timezone, which is a silent, plausible-looking error --
    a driver typing `2026-11-02T06:00:00` would have it read as 06:00 UTC,
    moving the whole trip by their offset and quietly changing every forecast
    lookup and therefore the recommendation.

    So the raw value is parsed here and handed on **exactly as given**: naive
    stays naive, aware stays aware. The serializer's `validate()` then decides
    what a naive value means, using `departure_timezone`.
    """

    def to_internal_value(self, value):
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            self.fail("invalid", format="YYYY-MM-DDThh:mm[:ss][+HH:MM]")

        text = value.strip()
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            self.fail("invalid", format="YYYY-MM-DDThh:mm[:ss][+HH:MM]")


class TimezoneField(serializers.CharField):
    """An IANA timezone name, e.g. `America/Denver`.

    A named zone beats a fixed offset for user input because it carries the
    DST rules with it. Denver is -06:00 on 2026-11-01 and -07:00 on
    2026-11-02; a client computing "my offset" from today's date would be an
    hour out across that boundary, and every checkpoint forecast with it.

    Browsers can populate a picker from `Intl.supportedValuesOf('timeZone')`,
    so no endpoint is needed to list these.
    """

    default_error_messages = {
        "unknown": (
            "Unknown timezone {value!r}. Use an IANA name such as "
            "'America/Denver' or 'UTC'."
        )
    }

    def to_internal_value(self, value) -> str:
        name = super().to_internal_value(value).strip()
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            self.fail("unknown", value=name)
        return name


class RouteAnalysisRequestSerializer(serializers.Serializer):
    """Validates trip inputs before any external request is made.

    Every check here is cheap and local. Nothing reaches a provider until the
    whole payload is known-good, so a typo cannot burn API quota.
    """

    origin = serializers.CharField(
        max_length=200,
        trim_whitespace=True,
        allow_blank=False,
        help_text="Free-text origin, e.g. 'Denver, CO'.",
    )
    destination = serializers.CharField(
        max_length=200,
        trim_whitespace=True,
        allow_blank=False,
        help_text="Free-text destination, e.g. 'Chicago, IL'.",
    )
    departure_at = TripDateTimeField(
        help_text=(
            "ISO 8601 departure time. Either carry an explicit offset "
            "('2026-11-02T06:00:00-06:00') or send local wall-clock time "
            "('2026-11-02T06:00:00') together with `departure_timezone`."
        )
    )
    departure_timezone = TimezoneField(
        required=False,
        allow_blank=True,
        max_length=64,
        help_text=(
            "IANA timezone for `departure_at`, e.g. 'America/Denver'. "
            "Required when `departure_at` has no offset. Handles daylight "
            "saving correctly, which a fixed offset cannot."
        ),
    )
    load_weight_lb = serializers.FloatField(
        min_value=1,
        max_value=MAX_LOAD_WEIGHT_LB,
        help_text="Cargo weight in pounds. Not gross vehicle weight.",
    )
    checkpoint_interval_miles = serializers.ChoiceField(
        choices=[int(value) for value in CheckpointInterval],
        help_text="Distance between weather checkpoints: 10, 25 or 50 miles.",
    )
    forecast_offset_hours = serializers.IntegerField(
        required=False,
        default=0,
        min_value=0,
        max_value=MAX_FORECAST_OFFSET_HOURS,
        help_text=(
            "Shift the whole trip later by this many hours. Re-runs routing, "
            "ETAs, weather and ranking against the later departure -- this is "
            "a departure offset, not the corridor heatmap slider."
        ),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        #: Non-fatal notes raised while interpreting the input, merged into
        #: the response by the view. DST oddities belong here: they are worth
        #: telling the driver about but are not reasons to refuse the trip.
        self.input_warnings: list[dict[str, Any]] = []

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Resolve the departure instant, then normalise it to UTC.

        Three accepted shapes:

        * offset in the timestamp -- that is the instant; any
          `departure_timezone` is kept for display only.
        * naive timestamp + `departure_timezone` -- read as local wall-clock
          time in that zone, which is what a person actually means when they
          say "I leave at six".
        * naive timestamp alone -- rejected. Guessing a zone would move the
          trip by hours and silently change the recommendation.
        """
        departure: datetime = attrs["departure_at"]
        zone_name: str = (attrs.get("departure_timezone") or "").strip()

        if departure.utcoffset() is not None:
            attrs["departure_at"] = departure.astimezone(UTC)
            attrs["departure_timezone"] = zone_name or None
            return attrs

        if not zone_name:
            raise serializers.ValidationError(
                {
                    "departure_timezone": [
                        "Required when `departure_at` has no UTC offset. Send "
                        "an IANA name such as 'America/Denver', or include an "
                        "offset in the timestamp itself."
                    ]
                }
            )

        zone = ZoneInfo(zone_name)
        localised = self._resolve_wall_clock(departure, zone, zone_name)
        attrs["departure_at"] = localised.astimezone(UTC)
        attrs["departure_timezone"] = zone_name
        return attrs

    def _resolve_wall_clock(
        self, naive: datetime, zone: ZoneInfo, zone_name: str
    ) -> datetime:
        """Attach a zone to a wall-clock time, flagging the DST oddities.

        Twice a year a local time is either ambiguous or impossible, and
        `zoneinfo` resolves both silently. Silent is the problem: the driver
        would get an analysis for an hour they did not ask for.
        """
        attached = naive.replace(tzinfo=zone)

        # Order matters. PEP 495's `fold` yields two different offsets for
        # *both* kinds of transition, so comparing folds cannot tell a
        # fall-back from a spring-forward. The round-trip can: a wall time
        # that exists survives it, and one that does not gets moved.
        round_tripped = attached.astimezone(UTC).astimezone(zone)
        if round_tripped.replace(tzinfo=None) != naive:
            self.input_warnings.append(
                {
                    "code": "NONEXISTENT_LOCAL_TIME",
                    "message": (
                        f"{naive.isoformat()} does not exist in {zone_name} "
                        "because the clocks go forward that morning. "
                        f"{round_tripped.strftime('%H:%M')} local was used "
                        "instead."
                    ),
                    "route_id": None,
                }
            )
            return round_tripped

        # The wall time exists. If the two folds disagree it exists *twice*.
        earlier = naive.replace(tzinfo=zone, fold=0)
        later = naive.replace(tzinfo=zone, fold=1)
        if earlier.utcoffset() != later.utcoffset():
            self.input_warnings.append(
                {
                    "code": "AMBIGUOUS_LOCAL_TIME",
                    "message": (
                        f"{naive.isoformat()} occurs twice in {zone_name} "
                        "because the clocks go back that morning. The earlier "
                        "of the two was used, which is the safer reading for a "
                        "departure."
                    ),
                    "route_id": None,
                }
            )
            return earlier

        return attached

    def to_analysis_request(self) -> AnalysisRequest:
        """Build the service-layer value object from validated data."""
        data = self.validated_data
        return AnalysisRequest(
            origin=data["origin"],
            destination=data["destination"],
            departure_at=data["departure_at"],
            load_weight_lb=float(data["load_weight_lb"]),
            checkpoint_interval_miles=int(data["checkpoint_interval_miles"]),
            forecast_offset_hours=int(data.get("forecast_offset_hours") or 0),
            departure_timezone=data.get("departure_timezone") or None,
        )


# --- response shaping -------------------------------------------------------
# Plain builders rather than serializer classes. A single analysis carries
# ~1,400 geometry points and up to 300 checkpoints per route; DRF's field
# machinery would walk every one of them to produce output we already hold as
# native types. These functions are the serialisation layer, kept explicit so
# the wire format is readable in one place.


def _iso(value: datetime | None) -> str | None:
    """UTC, ISO 8601, with an explicit offset. Never a naive timestamp."""
    return None if value is None else value.astimezone(UTC).isoformat()


def _local(value: datetime | None, zone_name: str | None) -> str | None:
    """Render an instant in the traveller's own timezone.

    Every timestamp in this API is UTC; this is an additional echo so a
    client can confirm we read their input the way they meant it. Checkpoint
    ETAs are deliberately *not* duplicated -- the client formats those from
    UTC plus `departure_timezone`, which keeps the payload half the size.
    """
    if value is None or not zone_name:
        return None
    try:
        return value.astimezone(ZoneInfo(zone_name)).isoformat()
    except (ZoneInfoNotFoundError, ValueError, KeyError):  # pragma: no cover
        return None


def _risk(level: RiskLevel) -> str:
    """Risk level as a stable enum string the client can switch on."""
    return level.value


def _round(value: float | None, places: int) -> float | None:
    return None if value is None else round(value, places)


def _serialise_weather(sample: Any) -> dict[str, Any] | None:
    if sample is None:
        return None
    return {
        "wind_mph": _round(sample.wind_mph, 2),
        "wind_gust_mph": _round(sample.wind_gust_mph, 2),
        "rain_in_hr": _round(sample.rain_in_hr, 4),
        "snow_in_hr": _round(sample.snow_in_hr, 4),
        "forecast_time": _iso(sample.forecast_time),
    }


def _serialise_checkpoint(assessed: Any) -> dict[str, Any]:
    point = assessed.checkpoint
    risk = assessed.risk
    return {
        "index": point.index,
        "latitude": round(point.coordinate.latitude, 6),
        "longitude": round(point.coordinate.longitude, 6),
        "distance_from_origin_miles": round(point.distance_from_origin_miles, 2),
        "segment_miles": round(assessed.segment_miles, 3),
        "eta": _iso(point.eta),
        "is_origin": point.is_origin,
        "is_destination": point.is_destination,
        "weather": _serialise_weather(assessed.weather),
        "risk": {
            "level": _risk(risk.level),
            "driver": risk.driver,
            "base_level": _risk(risk.base_level),
            "wind_level": _risk(risk.wind_level),
            "rain_level": _risk(risk.rain_level),
            "snow_level": _risk(risk.snow_level),
            "load_override_applied": risk.load_override_applied,
            "partial_data": risk.partial_data,
            "explanation": risk.explanation,
        },
    }


def _serialise_metrics(metrics: Any) -> dict[str, Any]:
    return {
        "distance_miles": round(metrics.distance_miles, 2),
        "duration_seconds": round(metrics.duration_seconds, 1),
        "low_miles": round(metrics.low_miles, 2),
        "moderate_miles": round(metrics.moderate_miles, 2),
        "high_miles": round(metrics.high_miles, 2),
        "severe_miles": round(metrics.severe_miles, 2),
        "no_travel_miles": round(metrics.no_travel_miles, 2),
        "unknown_miles": round(metrics.unknown_miles, 2),
        "average_risk": _round(metrics.average_risk, 4),
        "max_risk": _risk(metrics.max_risk),
        "coverage_pct": round(metrics.coverage_pct, 2),
        "no_travel_checkpoints": metrics.no_travel_checkpoints,
        "blocked": metrics.blocked,
    }


def _serialise_route(
    analysed: AnalysedRoute,
    evaluation: Any,
    recommended_route_id: str | None,
    zone_name: str | None = None,
) -> dict[str, Any]:
    route = analysed.route
    simplified = simplify_polyline(route.geometry, GEOMETRY_TOLERANCE_MILES)
    return {
        "route_id": route.id,
        "label": route.label,
        "rank": evaluation.rank,
        "is_recommended": route.id == recommended_route_id,
        "eligible": evaluation.eligible,
        "ineligibility_reasons": list(evaluation.ineligibility_reasons),
        "separated_from_previous_by": evaluation.separated_from_previous_by,
        "summary": {
            "distance_miles": round(route.distance_miles, 2),
            "duration_seconds": round(route.duration_seconds, 1),
            "departure_at": _iso(analysed.checkpoints[0].checkpoint.eta),
            "arrival_at": _iso(analysed.arrival_at),
            "arrival_at_local": _local(analysed.arrival_at, zone_name),
            "eta_source": analysed.eta_source,
        },
        "metrics": _serialise_metrics(analysed.metrics),
        "geometry": [
            [round(point.latitude, 6), round(point.longitude, 6)]
            for point in simplified
        ],
        "geometry_detail": {
            "returned_points": len(simplified),
            "source_points": analysed.geometry_points,
            "simplified": len(simplified) < analysed.geometry_points,
            "tolerance_miles": GEOMETRY_TOLERANCE_MILES,
        },
        "checkpoints": [
            _serialise_checkpoint(point) for point in analysed.checkpoints
        ],
    }


def serialise_analysis(result: AnalysisResult) -> dict[str, Any]:
    """Shape an :class:`AnalysisResult` into the public JSON contract.

    Routes come back in ranked order, with ineligible ones included so the UI
    can show *why* an option was rejected rather than silently dropping it.
    """
    evaluations = {
        evaluation.route_id: evaluation for evaluation in result.ranking.evaluations
    }
    by_id = {analysed.route.id: analysed for analysed in result.routes}

    ordered = [
        _serialise_route(
            by_id[evaluation.route_id],
            evaluation,
            result.recommended_route_id,
            result.request.departure_timezone,
        )
        for evaluation in result.ranking.evaluations
        if evaluation.route_id in by_id
    ]

    request = result.request
    return {
        "request": {
            "origin": request.origin,
            "destination": request.destination,
            "departure_at": _iso(request.departure_at),
            "departure_timezone": request.departure_timezone,
            "departure_at_local": _local(
                request.departure_at, request.departure_timezone
            ),
            "effective_departure_at": _iso(request.effective_departure_at),
            "effective_departure_at_local": _local(
                request.effective_departure_at, request.departure_timezone
            ),
            "forecast_offset_hours": request.forecast_offset_hours,
            "load_weight_lb": request.load_weight_lb,
            "checkpoint_interval_miles": request.checkpoint_interval_miles,
        },
        "origin": {
            "label": result.origin.label,
            "latitude": round(result.origin.coordinate.latitude, 6),
            "longitude": round(result.origin.coordinate.longitude, 6),
            "confidence": _round(result.origin.confidence, 4),
        },
        "destination": {
            "label": result.destination.label,
            "latitude": round(result.destination.coordinate.latitude, 6),
            "longitude": round(result.destination.coordinate.longitude, 6),
            "confidence": _round(result.destination.confidence, 4),
        },
        "recommended_route_id": result.recommended_route_id,
        "recommendation_reason": result.ranking.recommendation_reason,
        "routes": ordered,
        "warnings": [
            {
                "code": warning.code,
                "message": warning.message,
                "route_id": warning.route_id,
            }
            for warning in result.warnings
        ],
        "meta": {
            "routes_returned_by_provider": result.routes_returned_by_provider,
            "routes_analysed": len(ordered),
            "providers": dict(result.providers),
            "risk_levels": [level.value for level in RiskLevel],
        },
    }
