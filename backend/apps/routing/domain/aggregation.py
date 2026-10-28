"""Segment-mile attribution and per-route risk aggregation.

Forward attribution
-------------------
The ranking criteria are expressed in **miles**, but checkpoints are *points*.
Something has to turn one into the other, and the assessment does not say what.

The convention here is **forward attribution**: the checkpoint at distance
``d_i`` governs the stretch ``[d_i, d_(i+1))``, i.e. every mile is governed by
the conditions measured at the point where the driver *enters* it. The
destination checkpoint is the end of the last segment and therefore owns zero
forward miles; it is still classified and displayed so the driver sees what
they are arriving into, and a No Travel condition there still blocks the route
(see :attr:`~apps.routing.domain.models.RouteMetrics.blocked`).

Two properties follow directly, and both are asserted in the test suite:

* Segment lengths sum to exactly the route distance -- no gaps, no
  double-counting.
* Attribution is causal. A midpoint/Voronoi split would smear severe weather
  backwards onto a clear segment the driver has already passed, and would need
  special cases at both ends.

Distance weighting
------------------
Average risk is weighted by segment miles rather than averaged over
checkpoints. This matters more than it looks: with a plain per-checkpoint mean,
a 50 mile stretch sampled at 10 miles would outvote a 200 mile stretch sampled
at 50 miles purely because of sampling density, so the recommendation could
flip based on the interval the user happened to pick rather than the weather.
Distance weighting makes the metric invariant to checkpoint spacing.

Unknown miles are excluded from both the numerator and the denominator of the
average and are tracked separately, so a forecast gap can never be laundered
into a favourable score.
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import (
    AssessedCheckpoint,
    Checkpoint,
    RiskLevel,
    RouteCandidate,
    RouteMetrics,
    WeatherSample,
)
from .risk import assess_checkpoint, combine_levels

__all__ = [
    "assess_route",
    "segment_miles",
    "summarise_route",
]


def segment_miles(checkpoints: Sequence[Checkpoint]) -> tuple[float, ...]:
    """Forward-attributed miles owned by each checkpoint.

    Entry ``i`` is the distance from checkpoint ``i`` to checkpoint ``i + 1``;
    the final (destination) checkpoint owns ``0.0``. The returned values always
    sum to ``checkpoints[-1].distance_from_origin_miles``.
    """
    if len(checkpoints) < 2:
        raise ValueError("need at least an origin and a destination checkpoint")

    distances = [point.distance_from_origin_miles for point in checkpoints]
    if any(later < earlier for earlier, later in zip(distances, distances[1:])):
        raise ValueError("checkpoint distances must be non-decreasing")

    owned = [later - earlier for earlier, later in zip(distances, distances[1:])]
    owned.append(0.0)
    return tuple(owned)


def assess_route(
    checkpoints: Sequence[Checkpoint],
    samples: Sequence[WeatherSample | None],
    load_weight_lb: float,
) -> tuple[AssessedCheckpoint, ...]:
    """Join checkpoints to their forecasts, classify them and attribute miles.

    ``samples`` is positionally aligned with ``checkpoints``; a ``None`` entry
    means no forecast was obtained for that checkpoint, which classifies as
    ``UNKNOWN``.
    """
    if len(samples) != len(checkpoints):
        raise ValueError(
            "samples and checkpoints must be the same length: "
            + str(len(samples))
            + " vs "
            + str(len(checkpoints))
        )

    owned = segment_miles(checkpoints)
    return tuple(
        AssessedCheckpoint(
            checkpoint=checkpoint,
            weather=sample,
            risk=assess_checkpoint(sample, load_weight_lb),
            segment_miles=miles,
        )
        for checkpoint, sample, miles in zip(checkpoints, samples, owned)
    )


def summarise_route(
    route: RouteCandidate,
    assessed: Sequence[AssessedCheckpoint],
) -> RouteMetrics:
    """Reduce assessed checkpoints to the metrics the ranking engine consumes."""
    if not assessed:
        raise ValueError("cannot summarise a route with no assessed checkpoints")

    miles_by_level: dict[RiskLevel, float] = {level: 0.0 for level in RiskLevel}
    weighted_score_total = 0.0
    known_miles = 0.0
    no_travel_checkpoints = 0

    for point in assessed:
        level = point.risk.level
        miles_by_level[level] += point.segment_miles

        if level is RiskLevel.NO_TRAVEL:
            no_travel_checkpoints += 1

        score = level.score
        if score is not None:
            known_miles += point.segment_miles
            weighted_score_total += score * point.segment_miles

    total_miles = sum(point.segment_miles for point in assessed)

    average_risk = weighted_score_total / known_miles if known_miles > 0 else None
    coverage_pct = (known_miles / total_miles * 100.0) if total_miles > 0 else 0.0

    # max_risk spans every checkpoint, including the zero-mile destination, so
    # an arrival-time hazard is never hidden by having no forward miles.
    max_risk = combine_levels(point.risk.level for point in assessed)

    return RouteMetrics(
        route_id=route.id,
        distance_miles=route.distance_miles,
        duration_seconds=route.duration_seconds,
        low_miles=miles_by_level[RiskLevel.LOW],
        moderate_miles=miles_by_level[RiskLevel.MODERATE],
        high_miles=miles_by_level[RiskLevel.HIGH],
        severe_miles=miles_by_level[RiskLevel.SEVERE],
        no_travel_miles=miles_by_level[RiskLevel.NO_TRAVEL],
        unknown_miles=miles_by_level[RiskLevel.UNKNOWN],
        average_risk=average_risk,
        max_risk=max_risk,
        coverage_pct=coverage_pct,
        no_travel_checkpoints=no_travel_checkpoints,
    )
