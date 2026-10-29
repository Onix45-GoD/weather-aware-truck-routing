"""Deterministic route ranking and recommendation selection.

Criteria
--------
The assessment specifies four criteria, in this order:

1. Fewest Severe miles
2. Fewest High miles
3. Lowest average risk
4. Shortest travel time

They are applied here exactly as written, with two additions that sit *outside*
that order rather than disturbing it:

* **A safety gate is prepended.** A route that is blocked -- any No Travel
  condition -- or whose weather coverage is too thin to judge is ineligible for
  recommendation. It is still ranked, still returned and still drawn on the
  map, but it sorts behind every eligible route. The assessment's four-tier
  order has no slot for "this route cannot legally or safely be driven", and
  recommending such a route because it happened to have fewer *Severe* miles
  would be an unsafe output. Within the eligible set the ordering is precisely
  the specified one.

* **Tie-breaks are appended.** After all four criteria are equal, routes are
  separated by fewest unknown miles (prefer the better-understood route), then
  by the provider's original ordering, then by route id. The final two keys
  guarantee a **total order**: identical input always produces an identical
  recommendation, with no dependence on dictionary or sort stability.

Comparisons are quantised (see :data:`MILE_TOLERANCE` and friends) so that
floating-point noise a billionth of a mile wide can never flip a ranking.

Incomplete-coverage policy
--------------------------
A route whose forecast coverage falls below :data:`MIN_COVERAGE_PCT` is
ineligible. Without this, a route with no weather data would have zero Severe
miles, zero High miles and no average risk -- a perfect scorecard produced
entirely by ignorance -- and would beat a fully-forecast route with a little
bad weather on it. Unknown mileage is preserved in the metrics and reported;
it is never silently treated as good news.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .models import RouteCandidate, RouteMetrics

__all__ = [
    "MIN_COVERAGE_PCT",
    "RankingResult",
    "RouteEvaluation",
    "rank_routes",
]

#: Minimum percentage of route miles that must carry a usable forecast for the
#: route to be eligible for recommendation.
MIN_COVERAGE_PCT = 95.0

#: Quantisation applied before comparison, to absorb floating-point noise.
MILE_TOLERANCE = 3  # decimal places -> ~1.6 metres
AVERAGE_RISK_TOLERANCE = 6
DURATION_TOLERANCE = 3  # decimal places of a second

#: Human-readable names for each position in the sort key, used to report which
#: criterion actually decided a comparison.
_CRITERION_NAMES: tuple[str, ...] = (
    "eligibility",
    "severe_miles",
    "high_miles",
    "average_risk",
    "duration_seconds",
    "unknown_miles",
    "provider_order",
    "route_id",
)


@dataclass(frozen=True, slots=True)
class RouteEvaluation:
    """One route's place in the ranking, with the reasoning attached."""

    route_id: str
    label: str
    metrics: RouteMetrics
    rank: int
    eligible: bool
    ineligibility_reasons: tuple[str, ...]
    separated_from_previous_by: str | None


@dataclass(frozen=True, slots=True)
class RankingResult:
    """Ordered evaluations plus the recommendation drawn from them."""

    evaluations: tuple[RouteEvaluation, ...]
    recommended_route_id: str | None
    recommendation_reason: str

    @property
    def recommended(self) -> RouteEvaluation | None:
        for evaluation in self.evaluations:
            if evaluation.route_id == self.recommended_route_id:
                return evaluation
        return None


def _ineligibility_reasons(
    metrics: RouteMetrics, min_coverage_pct: float
) -> tuple[str, ...]:
    """Why this route cannot be recommended, or an empty tuple if it can."""
    reasons: list[str] = []

    if metrics.blocked:
        if metrics.no_travel_miles > 0:
            reasons.append(
                f"No Travel conditions over {metrics.no_travel_miles:.1f} mi of this route"
            )
        else:
            reasons.append(
                "No Travel conditions at the destination on arrival"
            )

    if metrics.average_risk is None:
        reasons.append("no usable forecast data for any part of this route")
    elif metrics.coverage_pct < min_coverage_pct:
        reasons.append(
            f"weather coverage {metrics.coverage_pct:.1f}% is below the {min_coverage_pct:.1f}% required "
            "to judge this route"
        )

    return tuple(reasons)


def _sort_key(
    route: RouteCandidate, metrics: RouteMetrics, eligible: bool
) -> tuple[int, float, float, float, float, float, int, str]:
    """Lexicographic key implementing the gate, the four criteria and tie-breaks."""
    average_risk = (
        metrics.average_risk if metrics.average_risk is not None else float("inf")
    )
    return (
        0 if eligible else 1,
        round(metrics.severe_miles, MILE_TOLERANCE),
        round(metrics.high_miles, MILE_TOLERANCE),
        round(average_risk, AVERAGE_RISK_TOLERANCE),
        round(metrics.duration_seconds, DURATION_TOLERANCE),
        round(metrics.unknown_miles, MILE_TOLERANCE),
        route.provider_index,
        route.id,
    )


def _first_difference(
    left: Sequence[object], right: Sequence[object]
) -> str | None:
    """Name of the first sort-key position at which two routes differ."""
    for name, a, b in zip(_CRITERION_NAMES, left, right):
        if a != b:
            return name
    return None


def rank_routes(
    candidates: Sequence[tuple[RouteCandidate, RouteMetrics]],
    min_coverage_pct: float = MIN_COVERAGE_PCT,
) -> RankingResult:
    """Rank routes and select a recommendation.

    Returns every route in ranked order -- ineligible ones included, so the UI
    can show the driver exactly why an option was rejected -- together with
    ``recommended_route_id``, which is ``None`` when no route is eligible.
    """
    if not candidates:
        return RankingResult(
            evaluations=(),
            recommended_route_id=None,
            recommendation_reason="No routes were supplied.",
        )

    scored = []
    for route, metrics in candidates:
        reasons = _ineligibility_reasons(metrics, min_coverage_pct)
        eligible = not reasons
        scored.append((_sort_key(route, metrics, eligible), route, metrics, reasons))

    scored.sort(key=lambda entry: entry[0])

    evaluations: list[RouteEvaluation] = []
    for position, (key, route, metrics, reasons) in enumerate(scored):
        separated_by = (
            _first_difference(scored[position - 1][0], key) if position > 0 else None
        )
        evaluations.append(
            RouteEvaluation(
                route_id=route.id,
                label=route.label,
                metrics=metrics,
                rank=position + 1,
                eligible=not reasons,
                ineligibility_reasons=reasons,
                separated_from_previous_by=separated_by,
            )
        )

    eligible = [evaluation for evaluation in evaluations if evaluation.eligible]

    if not eligible:
        return RankingResult(
            evaluations=tuple(evaluations),
            recommended_route_id=None,
            recommendation_reason=_no_recommendation_reason(evaluations),
        )

    winner = eligible[0]
    return RankingResult(
        evaluations=tuple(evaluations),
        recommended_route_id=winner.route_id,
        recommendation_reason=_recommendation_reason(winner, eligible),
    )


def _recommendation_reason(
    winner: RouteEvaluation, eligible: Sequence[RouteEvaluation]
) -> str:
    if len(eligible) == 1:
        return (
            winner.label
            + " is the only route that can be recommended; "
            + "every other option was ruled out on safety or data coverage."
        )

    runner_up = eligible[1]
    criterion = runner_up.separated_from_previous_by
    explanation = {
        "severe_miles": "it has the fewest Severe miles",
        "high_miles": "Severe miles tie, so it wins on fewest High miles",
        "average_risk": (
            "Severe and High miles tie, so it wins on lowest "
            "distance-weighted average risk"
        ),
        "duration_seconds": (
            "all three risk criteria tie, so it wins on shortest travel time"
        ),
        "unknown_miles": (
            "all four assessment criteria tie, so it wins on having the least "
            "unforecast mileage"
        ),
    }.get(
        criterion or "",
        "all criteria tie, so the provider's original ordering decides",
    )
    return winner.label + " is recommended: " + explanation + "."


def _no_recommendation_reason(evaluations: Sequence[RouteEvaluation]) -> str:
    blocked = [e for e in evaluations if e.metrics.blocked]
    if len(blocked) == len(evaluations):
        return (
            "No route can be recommended: every option encounters No Travel "
            "conditions at this departure time. Consider delaying departure."
        )
    return (
        "No route can be recommended: every option is either under No Travel "
        "conditions or has insufficient weather coverage to assess safely."
    )
