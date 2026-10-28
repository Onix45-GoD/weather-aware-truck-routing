"""Tests for the domain's input validation and defensive edges.

Malformed input should fail loudly at the boundary rather than quietly
producing a plausible-looking but wrong number further downstream.
"""

from __future__ import annotations

import pytest

from apps.routing.domain.checkpoints import (
    build_duration_profile,
    generate_checkpoints,
)
from apps.routing.domain.geo import interpolate
from apps.routing.domain.models import Coordinate, RouteCandidate
from apps.routing.domain.ranking import rank_routes
from apps.routing.tests.conftest import DEPARTURE, make_route, meridian_geometry
from apps.routing.tests.domain.test_ranking import metrics, route


class TestCoordinateValidation:
    @pytest.mark.parametrize("latitude", [90.1, -90.1, 1000.0])
    def test_latitude_out_of_range_is_rejected(self, latitude: float) -> None:
        with pytest.raises(ValueError, match="latitude out of range"):
            Coordinate(latitude=latitude, longitude=0.0)

    @pytest.mark.parametrize("longitude", [180.1, -180.1, 1000.0])
    def test_longitude_out_of_range_is_rejected(self, longitude: float) -> None:
        with pytest.raises(ValueError, match="longitude out of range"):
            Coordinate(latitude=0.0, longitude=longitude)

    @pytest.mark.parametrize(
        ("latitude", "longitude"),
        [(90.0, 180.0), (-90.0, -180.0), (0.0, 0.0)],
    )
    def test_extremes_are_accepted(self, latitude: float, longitude: float) -> None:
        assert Coordinate(latitude, longitude).latitude == latitude

    def test_coordinates_are_immutable(self) -> None:
        point = Coordinate(40.0, -100.0)
        with pytest.raises(AttributeError):
            point.latitude = 41.0  # type: ignore[misc]


class TestRouteCandidateValidation:
    def test_single_point_geometry_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least two coordinates"):
            RouteCandidate(
                id="r",
                label="r",
                geometry=(Coordinate(40.0, -100.0),),
                distance_miles=10.0,
                duration_seconds=600.0,
            )

    @pytest.mark.parametrize("distance", [0.0, -5.0])
    def test_non_positive_distance_is_rejected(self, distance: float) -> None:
        with pytest.raises(ValueError, match="distance must be positive"):
            make_route(distance_miles=distance)

    @pytest.mark.parametrize("duration", [0.0, -600.0])
    def test_non_positive_duration_is_rejected(self, duration: float) -> None:
        with pytest.raises(ValueError, match="duration must be positive"):
            make_route(duration_seconds=duration)

    def test_zero_length_geometry_is_rejected_at_checkpoint_time(self) -> None:
        """Two coincident vertices pass the shape check but have no length."""
        point = Coordinate(40.0, -100.0)
        route = make_route(geometry=(point, point))
        with pytest.raises(ValueError, match="zero length"):
            generate_checkpoints(route, 25.0, DEPARTURE)


class TestDurationProfileEdges:
    def test_zero_length_geometry_yields_a_zero_profile(self) -> None:
        """Directly exercised: `generate_checkpoints` rejects this earlier."""
        route = make_route(geometry=meridian_geometry(vertices=3))
        profile = build_duration_profile(route, (0.0, 0.0, 0.0))
        assert profile(0.0) == 0.0
        assert profile(50.0) == 0.0


class TestAntimeridianInterpolation:
    def test_eastward_wrap_takes_the_short_way(self) -> None:
        result = interpolate(Coordinate(0.0, -179.0), Coordinate(0.0, 179.0), 0.5)
        assert abs(result.longitude) == pytest.approx(180.0)

    def test_a_wrapped_result_is_renormalised_into_range(self) -> None:
        result = interpolate(Coordinate(0.0, -179.0), Coordinate(0.0, 179.0), 0.75)
        assert -180.0 <= result.longitude <= 180.0
        assert result.longitude == pytest.approx(179.5)

    def test_no_wrap_for_ordinary_longitudes(self) -> None:
        result = interpolate(Coordinate(0.0, -100.0), Coordinate(0.0, -98.0), 0.5)
        assert result.longitude == pytest.approx(-99.0)


class TestRankingDegenerateInput:
    def test_duplicate_route_ids_do_not_crash_the_comparator(self) -> None:
        """Two fully identical sort keys must still produce a stable order."""
        result = rank_routes(
            [
                (route("same", 0), metrics("same")),
                (route("same", 0), metrics("same")),
            ]
        )
        assert len(result.evaluations) == 2
        assert result.recommended_route_id == "same"
        assert result.evaluations[1].separated_from_previous_by is None
