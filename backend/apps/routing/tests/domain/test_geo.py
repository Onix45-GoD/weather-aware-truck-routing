"""Tests for geographic primitives."""

from __future__ import annotations

import pytest

from apps.routing.domain.geo import (
    cumulative_distances,
    decode_polyline,
    haversine_miles,
    interpolate,
    locate_distance,
    point_at_distance,
    total_distance_miles,
)
from apps.routing.domain.models import Coordinate
from apps.routing.tests.conftest import meridian_geometry


class TestHaversine:
    def test_zero_distance_to_itself(self) -> None:
        point = Coordinate(40.0, -100.0)
        assert haversine_miles(point, point) == pytest.approx(0.0, abs=1e-9)

    def test_one_degree_of_latitude_is_about_69_miles(self) -> None:
        distance = haversine_miles(Coordinate(40.0, -100.0), Coordinate(41.0, -100.0))
        assert distance == pytest.approx(69.09, abs=0.05)

    def test_is_symmetric(self) -> None:
        a, b = Coordinate(39.7392, -104.9903), Coordinate(41.8781, -87.6298)
        assert haversine_miles(a, b) == pytest.approx(haversine_miles(b, a))

    def test_denver_to_chicago_is_about_900_miles(self) -> None:
        """Great-circle, not road distance -- sanity check against a known pair."""
        distance = haversine_miles(
            Coordinate(39.7392, -104.9903), Coordinate(41.8781, -87.6298)
        )
        assert 900.0 < distance < 925.0

    def test_longitude_shrinks_with_latitude(self) -> None:
        at_equator = haversine_miles(Coordinate(0.0, 0.0), Coordinate(0.0, 1.0))
        at_sixty = haversine_miles(Coordinate(60.0, 0.0), Coordinate(60.0, 1.0))
        assert at_sixty == pytest.approx(at_equator * 0.5, rel=0.01)

    def test_antipodal_points_do_not_overflow_the_domain_of_asin(self) -> None:
        half_circumference = haversine_miles(
            Coordinate(0.0, 0.0), Coordinate(0.0, 180.0)
        )
        assert half_circumference == pytest.approx(12_437.0, rel=0.001)


class TestCumulativeDistances:
    def test_starts_at_zero_and_has_one_entry_per_vertex(self) -> None:
        geometry = meridian_geometry(vertices=11)
        cumulative = cumulative_distances(geometry)
        assert len(cumulative) == 11
        assert cumulative[0] == 0.0

    def test_is_monotonically_non_decreasing(self) -> None:
        cumulative = cumulative_distances(meridian_geometry(vertices=25))
        assert all(b >= a for a, b in zip(cumulative, cumulative[1:]))

    def test_evenly_spaced_vertices_give_evenly_spaced_distances(self) -> None:
        cumulative = cumulative_distances(meridian_geometry(vertices=11))
        steps = [b - a for a, b in zip(cumulative, cumulative[1:])]
        assert all(step == pytest.approx(steps[0], rel=1e-6) for step in steps)

    def test_total_equals_last_entry(self) -> None:
        geometry = meridian_geometry(vertices=7)
        assert total_distance_miles(geometry) == cumulative_distances(geometry)[-1]

    def test_rejects_degenerate_geometry(self) -> None:
        with pytest.raises(ValueError, match="at least two coordinates"):
            cumulative_distances([Coordinate(40.0, -100.0)])

    def test_handles_duplicate_vertices(self) -> None:
        point = Coordinate(40.0, -100.0)
        cumulative = cumulative_distances([point, point, Coordinate(41.0, -100.0)])
        assert cumulative[1] == pytest.approx(0.0, abs=1e-9)
        assert cumulative[2] > 60.0


class TestInterpolate:
    def test_endpoints_are_exact(self) -> None:
        a, b = Coordinate(40.0, -100.0), Coordinate(41.0, -99.0)
        assert interpolate(a, b, 0.0) == a
        assert interpolate(a, b, 1.0) == b

    def test_midpoint(self) -> None:
        result = interpolate(Coordinate(40.0, -100.0), Coordinate(42.0, -98.0), 0.5)
        assert result.latitude == pytest.approx(41.0)
        assert result.longitude == pytest.approx(-99.0)

    def test_fraction_is_clamped(self) -> None:
        a, b = Coordinate(40.0, -100.0), Coordinate(41.0, -100.0)
        assert interpolate(a, b, -5.0) == a
        assert interpolate(a, b, 5.0) == b

    def test_takes_the_short_way_across_the_antimeridian(self) -> None:
        result = interpolate(Coordinate(0.0, 179.0), Coordinate(0.0, -179.0), 0.5)
        # The short way is 2 degrees through 180, not 358 degrees through 0.
        assert abs(result.longitude) == pytest.approx(180.0)


class TestLocateDistance:
    def test_before_the_start_clamps_to_the_first_vertex(self) -> None:
        cumulative = cumulative_distances(meridian_geometry(vertices=5))
        assert locate_distance(cumulative, -10.0) == (0, 0.0)

    def test_past_the_end_clamps_to_the_last_vertex(self) -> None:
        cumulative = cumulative_distances(meridian_geometry(vertices=5))
        index, fraction = locate_distance(cumulative, cumulative[-1] * 2)
        assert (index, fraction) == (len(cumulative) - 2, 1.0)

    def test_finds_the_containing_segment(self) -> None:
        cumulative = (0.0, 10.0, 20.0, 30.0)
        assert locate_distance(cumulative, 15.0) == (1, 0.5)

    def test_exact_vertex_lands_at_the_segment_start(self) -> None:
        assert locate_distance((0.0, 10.0, 20.0, 30.0), 20.0) == (2, 0.0)

    def test_skips_zero_length_segments(self) -> None:
        # Vertices 1 and 2 are coincident; the lookup must not divide by zero.
        index, fraction = locate_distance((0.0, 10.0, 10.0, 20.0), 10.0)
        assert index == 2
        assert fraction == 0.0

    def test_rejects_degenerate_input(self) -> None:
        with pytest.raises(ValueError, match="at least two entries"):
            locate_distance((0.0,), 0.0)


class TestPointAtDistance:
    def test_quarter_way_along_an_even_line(self) -> None:
        geometry = meridian_geometry(vertices=11, start_lat=40.0, span_lat=1.0)
        cumulative = cumulative_distances(geometry)
        point = point_at_distance(geometry, cumulative, cumulative[-1] * 0.25)
        assert point.latitude == pytest.approx(40.25, abs=1e-6)

    def test_endpoints(self) -> None:
        geometry = meridian_geometry(vertices=6)
        cumulative = cumulative_distances(geometry)
        assert point_at_distance(geometry, cumulative, 0.0) == geometry[0]
        assert point_at_distance(geometry, cumulative, cumulative[-1]) == geometry[-1]


class TestDecodePolyline:
    def test_decodes_the_canonical_google_example(self) -> None:
        # From Google's encoded polyline specification.
        decoded = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
        assert len(decoded) == 3
        assert decoded[0].latitude == pytest.approx(38.5)
        assert decoded[0].longitude == pytest.approx(-120.2)
        assert decoded[1].latitude == pytest.approx(40.7)
        assert decoded[1].longitude == pytest.approx(-120.95)
        assert decoded[2].latitude == pytest.approx(43.252)
        assert decoded[2].longitude == pytest.approx(-126.453)

    def test_empty_string_decodes_to_nothing(self) -> None:
        assert decode_polyline("") == ()

    def test_rejects_a_truncated_varint(self) -> None:
        with pytest.raises(ValueError, match="truncated polyline"):
            decode_polyline("_p~iF~ps|U_ulL")
