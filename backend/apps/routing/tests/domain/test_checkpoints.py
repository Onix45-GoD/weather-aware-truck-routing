"""Tests for checkpoint placement and arrival-time estimation."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from apps.routing.domain.checkpoints import (
    checkpoint_distances,
    generate_checkpoints,
)
from apps.routing.domain.geo import cumulative_distances
from apps.routing.domain.models import CheckpointInterval
from apps.routing.tests.conftest import (
    DEPARTURE,
    make_route,
    meridian_geometry,
    uneven_geometry,
)


class TestCheckpointDistances:
    def test_exact_multiple_leaves_no_remainder(self) -> None:
        assert checkpoint_distances(100.0, 25.0) == (0.0, 25.0, 50.0, 75.0, 100.0)

    def test_partial_final_segment_is_kept(self) -> None:
        distances = checkpoint_distances(110.0, 50.0)
        assert distances == (0.0, 50.0, 100.0, 110.0)

    def test_route_shorter_than_the_interval_is_origin_plus_destination(self) -> None:
        assert checkpoint_distances(7.0, 50.0) == (0.0, 7.0)

    def test_always_starts_at_the_origin(self) -> None:
        assert checkpoint_distances(1234.5, 10.0)[0] == 0.0

    def test_always_ends_exactly_at_the_destination(self) -> None:
        assert checkpoint_distances(1234.5, 10.0)[-1] == 1234.5

    def test_is_strictly_increasing(self) -> None:
        distances = checkpoint_distances(873.2, 25.0)
        assert all(b > a for a, b in zip(distances, distances[1:]))

    def test_no_degenerate_final_segment_from_float_drift(self) -> None:
        """A route a hair over an exact multiple must not emit a 1e-9 segment."""
        distances = checkpoint_distances(100.0000000001, 25.0)
        assert distances[-2] == 75.0
        assert distances[-1] == pytest.approx(100.0)

    @pytest.mark.parametrize("interval", list(CheckpointInterval))
    def test_all_assessment_intervals_are_supported(
        self, interval: CheckpointInterval
    ) -> None:
        distances = checkpoint_distances(500.0, float(interval))
        assert distances[0] == 0.0
        assert distances[-1] == 500.0
        steps = [b - a for a, b in zip(distances[:-1], distances[1:-1])]
        assert all(step == pytest.approx(float(interval)) for step in steps)

    @pytest.mark.parametrize("bad_interval", [0.0, -10.0])
    def test_rejects_a_non_positive_interval(self, bad_interval: float) -> None:
        with pytest.raises(ValueError, match="interval must be positive"):
            checkpoint_distances(100.0, bad_interval)

    def test_rejects_a_non_positive_distance(self) -> None:
        with pytest.raises(ValueError, match="distance must be positive"):
            checkpoint_distances(0.0, 25.0)


class TestCheckpointSpacing:
    def test_spacing_matches_the_requested_interval(self) -> None:
        route = make_route(distance_miles=100.0)
        points = generate_checkpoints(route, 25.0, DEPARTURE)

        assert len(points) == 5
        assert [p.distance_from_origin_miles for p in points] == [
            0.0,
            25.0,
            50.0,
            75.0,
            100.0,
        ]

    def test_origin_and_destination_are_flagged(self) -> None:
        points = generate_checkpoints(make_route(), 25.0, DEPARTURE)

        assert points[0].is_origin is True
        assert points[0].is_destination is False
        assert points[-1].is_destination is True
        assert points[-1].is_origin is False
        assert not any(p.is_origin for p in points[1:])
        assert not any(p.is_destination for p in points[:-1])

    def test_indices_are_sequential(self) -> None:
        points = generate_checkpoints(make_route(), 10.0, DEPARTURE)
        assert [p.index for p in points] == list(range(len(points)))

    def test_origin_coordinate_matches_the_route_start(self) -> None:
        route = make_route()
        points = generate_checkpoints(route, 25.0, DEPARTURE)
        assert points[0].coordinate.latitude == pytest.approx(
            route.geometry[0].latitude
        )

    def test_destination_coordinate_matches_the_route_end(self) -> None:
        route = make_route()
        points = generate_checkpoints(route, 25.0, DEPARTURE)
        assert points[-1].coordinate.latitude == pytest.approx(
            route.geometry[-1].latitude
        )


class TestCoordinateInterpolation:
    def test_checkpoints_land_proportionally_along_an_even_route(self) -> None:
        route = make_route(
            distance_miles=100.0,
            geometry=meridian_geometry(vertices=11, start_lat=40.0, span_lat=1.0),
        )
        points = generate_checkpoints(route, 25.0, DEPARTURE)
        latitudes = [p.coordinate.latitude for p in points]
        assert latitudes == pytest.approx([40.0, 40.25, 40.5, 40.75, 41.0], abs=1e-6)

    def test_placement_follows_distance_not_vertex_index(self) -> None:
        """With clustered vertices, index-based sampling would be badly wrong.

        `uneven_geometry` has 6 of its 9 vertices inside the first 5% of the
        route. Sampling by index would put the midpoint checkpoint at ~4% of
        the way along; sampling by distance puts it at the actual halfway mark.
        """
        route = make_route(distance_miles=100.0, geometry=uneven_geometry())
        points = generate_checkpoints(route, 50.0, DEPARTURE)

        midpoint = points[1]
        assert midpoint.distance_from_origin_miles == pytest.approx(50.0)
        # Geometry spans latitude 40.0 -> 41.0, so halfway by distance is 40.5.
        assert midpoint.coordinate.latitude == pytest.approx(40.5, abs=1e-6)

        # Index-based sampling would have landed on vertex 4 of 8 -> lat 40.04.
        assert midpoint.coordinate.latitude > 40.4

    def test_interpolated_points_lie_on_the_route(self) -> None:
        route = make_route(distance_miles=100.0)
        points = generate_checkpoints(route, 10.0, DEPARTURE)
        for point in points:
            assert 40.0 <= point.coordinate.latitude <= 41.0
            assert point.coordinate.longitude == pytest.approx(-100.0)


class TestEtaProportionalFallback:
    def test_etas_are_proportional_to_distance(self) -> None:
        route = make_route(distance_miles=100.0, duration_seconds=7200.0)
        points = generate_checkpoints(route, 25.0, DEPARTURE)

        expected = [
            DEPARTURE + timedelta(seconds=seconds)
            for seconds in (0, 1800, 3600, 5400, 7200)
        ]
        assert [p.eta for p in points] == expected

    def test_first_eta_is_the_departure_time(self) -> None:
        points = generate_checkpoints(make_route(), 25.0, DEPARTURE)
        assert points[0].eta == DEPARTURE

    def test_final_eta_matches_the_route_duration_exactly(self) -> None:
        route = make_route(distance_miles=873.4, duration_seconds=50_123.0)
        points = generate_checkpoints(route, 25.0, DEPARTURE)
        assert points[-1].eta == DEPARTURE + timedelta(seconds=50_123.0)

    @pytest.mark.parametrize("interval", [10.0, 25.0, 50.0])
    def test_etas_are_monotonic(self, interval: float) -> None:
        route = make_route(distance_miles=437.0, duration_seconds=28_800.0)
        points = generate_checkpoints(route, interval, DEPARTURE)
        etas = [p.eta for p in points]
        assert all(b >= a for a, b in zip(etas, etas[1:]))
        assert etas == sorted(etas)


class TestEtaFromProviderSegmentDurations:
    def _slow_first_half_route(self) -> object:
        """A route whose first half takes three times as long as its second."""
        geometry = meridian_geometry(vertices=5)  # 4 segments
        return make_route(
            distance_miles=100.0,
            duration_seconds=8000.0,
            geometry=geometry,
            segment_durations=(3000.0, 3000.0, 1000.0, 1000.0),
        )

    def test_provider_timings_beat_distance_proportionality(self) -> None:
        route = self._slow_first_half_route()
        points = generate_checkpoints(route, 50.0, DEPARTURE)

        midpoint = points[1]
        assert midpoint.distance_from_origin_miles == pytest.approx(50.0)
        # Proportional would say 4000 s; the real profile says 6000 s.
        assert midpoint.eta == DEPARTURE + timedelta(seconds=6000.0)

    def test_final_eta_still_matches_the_route_total(self) -> None:
        route = self._slow_first_half_route()
        points = generate_checkpoints(route, 25.0, DEPARTURE)
        assert points[-1].eta == DEPARTURE + timedelta(seconds=8000.0)

    def test_segment_durations_are_normalised_to_the_headline_total(self) -> None:
        """Provider per-segment numbers often don't sum to its own total."""
        route = make_route(
            distance_miles=100.0,
            duration_seconds=8000.0,
            geometry=meridian_geometry(vertices=5),
            segment_durations=(1000.0, 1000.0, 1000.0, 1000.0),  # sums to 4000
        )
        points = generate_checkpoints(route, 50.0, DEPARTURE)

        assert points[1].eta == DEPARTURE + timedelta(seconds=4000.0)
        assert points[-1].eta == DEPARTURE + timedelta(seconds=8000.0)

    def test_all_zero_durations_fall_back_to_proportional(self) -> None:
        route = make_route(
            distance_miles=100.0,
            duration_seconds=7200.0,
            geometry=meridian_geometry(vertices=5),
            segment_durations=(0.0, 0.0, 0.0, 0.0),
        )
        points = generate_checkpoints(route, 50.0, DEPARTURE)
        assert points[1].eta == DEPARTURE + timedelta(seconds=3600.0)

    def test_etas_stay_monotonic_with_a_stalled_segment(self) -> None:
        route = make_route(
            distance_miles=100.0,
            duration_seconds=7200.0,
            geometry=meridian_geometry(vertices=5),
            segment_durations=(3600.0, 0.0, 3600.0, 0.0),
        )
        etas = [p.eta for p in generate_checkpoints(route, 10.0, DEPARTURE)]
        assert all(b >= a for a, b in zip(etas, etas[1:]))

    def test_mismatched_segment_duration_count_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="segment_durations must have 4 entries"):
            make_route(
                geometry=meridian_geometry(vertices=5),
                segment_durations=(1.0, 2.0),
            )

    def test_negative_segment_duration_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            make_route(
                geometry=meridian_geometry(vertices=5),
                segment_durations=(1.0, -2.0, 3.0, 4.0),
            )


class TestDistanceScaleReconciliation:
    def test_checkpoints_use_the_provider_distance_scale(self) -> None:
        """Haversine over the polyline never exactly equals road distance.

        Checkpoints are reported in the provider's scale so the mileage
        accounting downstream reconciles exactly; coordinates are still looked
        up in the geometry's own measure.
        """
        geometry = meridian_geometry(vertices=11, span_lat=1.0)
        geometry_miles = cumulative_distances(geometry)[-1]
        assert geometry_miles == pytest.approx(69.09, abs=0.05)

        route = make_route(distance_miles=75.0, geometry=geometry)
        points = generate_checkpoints(route, 25.0, DEPARTURE)

        assert [p.distance_from_origin_miles for p in points] == [
            0.0,
            25.0,
            50.0,
            75.0,
        ]
        # 25/75 of the way by provider distance is 1/3 of the way by geometry.
        assert points[1].coordinate.latitude == pytest.approx(40.0 + 1 / 3, abs=1e-6)


class TestDepartureTimeValidation:
    def test_naive_departure_time_is_rejected(self) -> None:
        naive = datetime(2026, 11, 2, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            generate_checkpoints(make_route(), 25.0, naive)
