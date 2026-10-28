"""Geographic primitives: distance, cumulative route measure, interpolation.

Pure functions over :class:`~apps.routing.domain.models.Coordinate` values.
Distances are in statute miles throughout, matching the assessment's units.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from math import asin, cos, radians, sin, sqrt

from .models import Coordinate

__all__ = [
    "EARTH_RADIUS_MILES",
    "cumulative_distances",
    "decode_polyline",
    "haversine_miles",
    "interpolate",
    "locate_distance",
    "point_at_distance",
    "total_distance_miles",
]

#: IUGG mean Earth radius (6_371.0088 km) expressed in statute miles.
EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(start: Coordinate, end: Coordinate) -> float:
    """Great-circle distance between two coordinates, in miles.

    The haversine form is numerically stable for the short segment lengths
    found in route geometry, where the law-of-cosines form loses precision.
    """
    lat1, lon1 = radians(start.latitude), radians(start.longitude)
    lat2, lon2 = radians(end.latitude), radians(end.longitude)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    h = sin(delta_lat / 2.0) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2.0) ** 2
    # Clamp guards against a hair above 1.0 from floating point accumulation.
    return 2.0 * EARTH_RADIUS_MILES * asin(sqrt(min(1.0, h)))


def cumulative_distances(geometry: Sequence[Coordinate]) -> tuple[float, ...]:
    """Cumulative along-route distance at each geometry vertex.

    Returns ``len(geometry)`` values starting at ``0.0``. This is the measure
    that positions checkpoints: checkpoints are placed by *real distance
    travelled*, never by index into the geometry array, because provider
    polylines have wildly non-uniform vertex spacing (dense through
    interchanges, sparse across open highway).
    """
    if len(geometry) < 2:
        raise ValueError("geometry needs at least two coordinates")

    distances = [0.0]
    running = 0.0
    for previous, current in zip(geometry, geometry[1:]):
        running += haversine_miles(previous, current)
        distances.append(running)
    return tuple(distances)


def total_distance_miles(geometry: Sequence[Coordinate]) -> float:
    """Total great-circle length of a polyline, in miles."""
    return cumulative_distances(geometry)[-1]


def interpolate(start: Coordinate, end: Coordinate, fraction: float) -> Coordinate:
    """Linearly interpolate between two coordinates.

    ``fraction`` is clamped to ``[0, 1]``. Linear interpolation in degrees is
    accurate to well under a metre at the sub-mile vertex spacing of real route
    geometry, and avoids the cost and edge cases of spherical interpolation.
    Longitude is interpolated along the shorter arc so the antimeridian is
    handled correctly.
    """
    fraction = min(1.0, max(0.0, fraction))

    delta_lon = end.longitude - start.longitude
    if delta_lon > 180.0:
        delta_lon -= 360.0
    elif delta_lon < -180.0:
        delta_lon += 360.0

    latitude = start.latitude + (end.latitude - start.latitude) * fraction
    longitude = start.longitude + delta_lon * fraction
    # Re-normalise into [-180, 180) after a wrap.
    if longitude > 180.0 or longitude < -180.0:
        longitude = ((longitude + 180.0) % 360.0) - 180.0

    return Coordinate(latitude=latitude, longitude=longitude)


def locate_distance(
    cumulative: Sequence[float], target_miles: float
) -> tuple[int, float]:
    """Find the geometry segment containing ``target_miles``.

    Returns ``(segment_index, fraction)`` where ``segment_index`` indexes the
    segment from vertex ``i`` to vertex ``i + 1``, and ``fraction`` is the
    position within it. Distances before the start or past the end clamp to the
    first and last vertex respectively.

    Zero-length segments (duplicate vertices, which providers do emit) are
    skipped by construction: ``bisect_right`` lands on the last vertex sharing
    a cumulative value, which is always the start of a segment with length.
    """
    if len(cumulative) < 2:
        raise ValueError("cumulative distances need at least two entries")

    total = cumulative[-1]
    if target_miles <= 0.0:
        return 0, 0.0
    if target_miles >= total:
        return len(cumulative) - 2, 1.0

    index = bisect_right(cumulative, target_miles) - 1
    index = min(index, len(cumulative) - 2)

    segment_length = cumulative[index + 1] - cumulative[index]
    if segment_length <= 0.0:  # pragma: no cover - defensive
        # Unreachable given the clamps above: `bisect_right` always lands on
        # the *last* vertex sharing a cumulative value, so the chosen segment
        # has length unless the target is at or past the end, which returned
        # already. Kept as a division-by-zero guard in case those invariants
        # ever change.
        return index, 0.0
    return index, (target_miles - cumulative[index]) / segment_length


def point_at_distance(
    geometry: Sequence[Coordinate],
    cumulative: Sequence[float],
    target_miles: float,
) -> Coordinate:
    """Coordinate found ``target_miles`` along the route geometry."""
    index, fraction = locate_distance(cumulative, target_miles)
    return interpolate(geometry[index], geometry[index + 1], fraction)


def decode_polyline(encoded: str, precision: int = 5) -> tuple[Coordinate, ...]:
    """Decode a Google/HERE-style encoded polyline into coordinates.

    Several routing providers return geometry in this compressed form.
    Implemented here so provider adapters stay thin and the decoder itself is
    unit-testable without any network access.

    ``precision`` is the number of decimal places the encoder used (5 for
    Google's classic format, 6 for several newer variants).
    """
    if not encoded:
        return ()

    factor = float(10**precision)
    coordinates: list[Coordinate] = []
    index = 0
    latitude = 0
    longitude = 0
    length = len(encoded)

    while index < length:
        for axis in range(2):
            shift = 0
            result = 0
            while True:
                if index >= length:
                    raise ValueError("truncated polyline: unterminated varint")
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if axis == 0:
                latitude += delta
            else:
                longitude += delta

        coordinates.append(
            Coordinate(latitude=latitude / factor, longitude=longitude / factor)
        )

    return tuple(coordinates)
