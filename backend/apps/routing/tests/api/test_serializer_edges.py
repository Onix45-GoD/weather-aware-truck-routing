"""Edge cases in request validation and response shaping."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.test import Client
from rest_framework import serializers

from apps.routing.api.serializers import (
    RouteAnalysisRequestSerializer,
    TimezoneField,
    TripDateTimeField,
)

URL = "/api/v1/route-analysis"


class TestTripDateTimeField:
    """Hands the value on exactly as given, so `validate()` can interpret it.

    DRF would otherwise localise a naive timestamp into the server timezone,
    silently moving the whole trip.
    """

    def test_preserves_an_offset(self) -> None:
        parsed = TripDateTimeField().to_internal_value("2026-11-02T12:00:00Z")
        assert parsed.utcoffset() is not None

    @pytest.mark.parametrize(
        "raw", ["2026-11-02T12:00:00", "2026-11-02 12:00:00", "2026-11-02"]
    )
    def test_keeps_naive_input_naive(self, raw: str) -> None:
        """Crucially NOT localised -- `validate()` decides what it means."""
        assert TripDateTimeField().to_internal_value(raw).utcoffset() is None

    def test_passes_a_datetime_object_through(self) -> None:
        value = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
        assert TripDateTimeField().to_internal_value(value) == value

    @pytest.mark.parametrize(
        "raw",
        [
            "2026-11-02T12:00:00+00:00",
            "2026-11-02T12:00:00-0600",
            "2026-11-02T12:00:00+05:30",
        ],
    )
    def test_accepts_every_offset_form(self, raw: str) -> None:
        assert TripDateTimeField().to_internal_value(raw).utcoffset() is not None

    @pytest.mark.parametrize("raw", ["next tuesday", "", "2026-13-45T99:99"])
    def test_rejects_unparseable_input(self, raw: str) -> None:
        with pytest.raises(serializers.ValidationError):
            TripDateTimeField().to_internal_value(raw)

    def test_rejects_a_non_string_non_datetime(self) -> None:
        with pytest.raises(serializers.ValidationError):
            TripDateTimeField().to_internal_value(12345)


class TestTimezoneField:
    @pytest.mark.parametrize(
        "name", ["America/Denver", "UTC", "Europe/London", "Asia/Tokyo"]
    )
    def test_accepts_iana_names(self, name: str) -> None:
        assert TimezoneField().to_internal_value(name) == name

    def test_trims_whitespace(self) -> None:
        assert TimezoneField().to_internal_value("  UTC  ") == "UTC"

    @pytest.mark.parametrize(
        "name", ["Mars/Olympus", "EST5EDT_NOPE", "not a zone", "America/Denverr"]
    )
    def test_rejects_unknown_zones(self, name: str) -> None:
        with pytest.raises(serializers.ValidationError, match="Unknown timezone"):
            TimezoneField().to_internal_value(name)


class TestRequestSerializer:
    def test_normalises_departure_to_utc(self) -> None:
        serializer = RouteAnalysisRequestSerializer(
            data={
                "origin": "Denver",
                "destination": "Chicago",
                "departure_at": "2026-11-02T06:00:00-06:00",
                "load_weight_lb": 42000,
                "checkpoint_interval_miles": 25,
            }
        )
        assert serializer.is_valid(), serializer.errors
        request = serializer.to_analysis_request()

        assert request.departure_at == datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
        assert request.departure_at.tzinfo is UTC

    def test_trims_surrounding_whitespace(self) -> None:
        serializer = RouteAnalysisRequestSerializer(
            data={
                "origin": "  Denver  ",
                "destination": "  Chicago ",
                "departure_at": "2026-11-02T12:00:00Z",
                "load_weight_lb": 42000,
                "checkpoint_interval_miles": 25,
            }
        )
        assert serializer.is_valid(), serializer.errors
        request = serializer.to_analysis_request()
        assert request.origin == "Denver"
        assert request.destination == "Chicago"

    def test_offset_defaults_to_zero(self) -> None:
        serializer = RouteAnalysisRequestSerializer(
            data={
                "origin": "Denver",
                "destination": "Chicago",
                "departure_at": "2026-11-02T12:00:00Z",
                "load_weight_lb": 1,
                "checkpoint_interval_miles": 10,
            }
        )
        assert serializer.is_valid(), serializer.errors
        assert serializer.to_analysis_request().forecast_offset_hours == 0


class TestServiceLayerDisagreement:
    def test_a_rejected_value_object_becomes_a_400_not_a_500(
        self, valid_payload
    ) -> None:
        """Defence in depth.

        The serializer and the service dataclass enforce the same invariants.
        If they ever disagree, the caller gets a clear 400 rather than an
        opaque 500 -- and the mismatch is visible instead of hidden.
        """
        with patch.object(
            RouteAnalysisRequestSerializer,
            "to_analysis_request",
            side_effect=ValueError("load_weight_lb must be positive"),
        ):
            response = Client().post(
                URL,
                data=json.dumps(valid_payload),
                content_type="application/json",
            )

        assert response.status_code == 400
        body = response.json()["error"]
        assert body["code"] == "INVALID_REQUEST"
        assert "load_weight_lb" in body["message"]


class TestEmptyRouteSet:
    def test_a_provider_returning_no_routes_yields_no_recommendation(
        self, valid_payload
    ) -> None:
        """Some providers return an empty list rather than raising."""
        from apps.routing.providers.base import RouteSet

        class EmptyRouter:
            name = "empty"

            def routes(self, origin, destination, departure_time, *, max_alternatives=2):
                return RouteSet(
                    routes=(),
                    provider=self.name,
                    requested_alternatives=max_alternatives,
                    returned_count=0,
                )

        with patch(
            "apps.routing.services.analysis.get_routing_provider",
            return_value=EmptyRouter(),
        ):
            response = Client().post(
                URL,
                data=json.dumps(valid_payload),
                content_type="application/json",
            )

        assert response.status_code == 200
        body = response.json()
        assert body["routes"] == []
        assert body["recommended_route_id"] is None
        assert body["recommendation_reason"]
