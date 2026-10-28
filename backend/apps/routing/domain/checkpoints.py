"""Distance-based checkpoint generation and arrival-time estimation.

Checkpoints are positioned by *cumulative distance travelled*, never by index
into the provider's geometry array. Provider polylines have wildly uneven
vertex spacing -- dense through interchanges, sparse across open highway -- so
index-based sampling would cluster checkpoints around intersections and leave
long stretches unsampled.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from .geo import cumulative_distances, locate_distance, point_at_distance
from .models import Checkpoint, RouteCandidate

__all__ = [
    "EPSILON_MILES",
    "build_duration_profile",
    "checkpoint_distances",
    "generate_checkpoints",
]

#: Tolerance used to avoid emitting a degenerate final segment when the route
#: length lands within rounding distance of an exact interval multiple.
EPSILON_MILES = 1e-6


def checkpoint_distances(
    total_distance_miles: float, interval_miles: float
) -> tuple[float, ...]:
    """Along-route distances at which to sample weather.

    Produces ``0, interval, 2*interval, ...`` for every multiple strictly
    inside the route, then the destination at exactly ``total_distance_miles``.

    Including both the origin (distance 0) and the destination endpoint is what
    makes segment coverage complete: with ``n`` checkpoints there are ``n - 1``
    segments whose lengths sum to exactly the route distance.

    A 100 mile route at a 25 mile interval therefore yields distances
    ``(0, 25, 50, 75, 100)`` -- four 25 mile segments, no remainder.
    """
    if interval_miles <= 0:
        raise ValueError("checkpoint interval must be positive")
    if total_distance_miles <= 0:
        raise ValueError("route distance must be positive")

    distances: list[float] = []
    step = 0
    while True:
        position = step * interval_miles
        if position >= total_distance_miles - EPSILON_MILES:
            break
        distances.append(position)
        step += 1

    distances.append(total_distance_miles)
    return tuple(distances)


def build_duration_profile(
    route: RouteCandidate, geometry_cumulative: Sequence[float]
) -> Callable[[float], float]:
    """Return a function mapping geometry distance to cumulative seconds.

    Two strategies, in preference order:

    1. **Provider segment durations.** When ``route.segment_durations`` is
       present, cumulative time is interpolated linearly *within* the geometry
       segment containing the target distance. This respects the real speed
       profile of the road -- terrain, speed limits, traffic -- so a checkpoint
       halfway along a route through mountains does not get the ETA it would
       have on flat interstate.

       The profile is rescaled so its final value equals
       ``route.duration_seconds`` exactly, reconciling any drift between the
       provider's per-segment numbers and its headline total.

    2. **Distance-proportional fallback.** Otherwise, cumulative time is
       ``duration_seconds * (distance / total_distance)``, i.e. a constant
       average speed for the whole route. Documented as an approximation and
       reported in the API response so it is never mistaken for the real thing.

    Both strategies are monotonic non-decreasing in distance, which is what
    guarantees checkpoint ETAs never travel backwards.
    """
    geometry_total = geometry_cumulative[-1]

    cumulative_seconds = _cumulative_segment_seconds(route)

    if cumulative_seconds is None:

        def proportional(distance: float) -> float:
            if geometry_total <= 0:
                return 0.0
            ratio = min(1.0, max(0.0, distance / geometry_total))
            return route.duration_seconds * ratio

        return proportional

    def from_segments(distance: float) -> float:
        index, fraction = locate_distance(geometry_cumulative, distance)
        start = cumulative_seconds[index]
        end = cumulative_seconds[index + 1]
        return start + (end - start) * fraction

    return from_segments


def _cumulative_segment_seconds(route: RouteCandidate) -> tuple[float, ...] | None:
    """Running travel time at each geometry vertex, normalised to the total.

    Returns ``None`` when the provider gave no usable per-segment timing, which
    signals the caller to use the distance-proportional fallback.
    """
    if route.segment_durations is None:
        return None

    running = 0.0
    values = [0.0]
    for seconds in route.segment_durations:
        running += seconds
        values.append(running)

    if running <= 0.0:
        return None

    scale = route.duration_seconds / running
    normalised = [value * scale for value in values]
    # Pin the endpoint so the final ETA matches the route total exactly rather
    # than to within floating-point drift.
    normalised[-1] = route.duration_seconds
    return tuple(normalised)


def generate_checkpoints(
    route: RouteCandidate,
    interval_miles: float,
    departure_time: datetime,
) -> tuple[Checkpoint, ...]:
    """Generate checkpoints along ``route`` at ``interval_miles`` spacing.

    Checkpoint distances are expressed in the provider's distance scale, so
    ``distance_from_origin_miles`` values run from ``0`` to exactly
    ``route.distance_miles`` and the derived segment lengths sum to the route
    distance with no residual. Coordinates are looked up by converting into the
    geometry's own measure, because the haversine sum over a polyline differs
    slightly from the provider's road-following distance.

    ``departure_time`` must be timezone-aware. The domain layer never reads the
    clock; the caller supplies the reference instant.
    """
    if departure_time.tzinfo is None or departure_time.utcoffset() is None:
        raise ValueError("departure_time must be timezone-aware")

    geometry_cumulative = cumulative_distances(route.geometry)
    geometry_total = geometry_cumulative[-1]
    if geometry_total <= 0.0:
        raise ValueError("route geometry has zero length")

    # Geometry miles per reported route mile. Normally within a fraction of a
    # percent of 1.0; it exists so distance accounting is exact either way.
    geometry_per_route_mile = geometry_total / route.distance_miles

    positions = checkpoint_distances(route.distance_miles, interval_miles)
    duration_at = build_duration_profile(route, geometry_cumulative)
    last_index = len(positions) - 1

    checkpoints: list[Checkpoint] = []
    for index, route_miles in enumerate(positions):
        geometry_miles = route_miles * geometry_per_route_mile
        coordinate = point_at_distance(
            route.geometry, geometry_cumulative, geometry_miles
        )

        if index == last_index:
            # Pin the destination to the route's own total duration rather than
            # to an interpolated value a few microseconds short of it.
            seconds = route.duration_seconds
        else:
            seconds = duration_at(geometry_miles)

        checkpoints.append(
            Checkpoint(
                index=index,
                coordinate=coordinate,
                distance_from_origin_miles=route_miles,
                eta=departure_time + timedelta(seconds=seconds),
                is_origin=index == 0,
                is_destination=index == last_index,
            )
        )

    return tuple(checkpoints)
