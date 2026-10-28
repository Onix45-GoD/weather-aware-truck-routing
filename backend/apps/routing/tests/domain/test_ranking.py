"""Tests for deterministic route ranking and recommendation selection."""

from __future__ import annotations

from itertools import permutations

import pytest

from apps.routing.domain.models import RiskLevel, RouteCandidate, RouteMetrics
from apps.routing.domain.ranking import MIN_COVERAGE_PCT, rank_routes
from apps.routing.tests.conftest import make_route


def metrics(
    route_id: str,
    *,
    severe: float = 0.0,
    high: float = 0.0,
    average: float | None = 0.0,
    duration: float = 3600.0,
    unknown: float = 0.0,
    no_travel: float = 0.0,
    no_travel_checkpoints: int = 0,
    distance: float = 100.0,
    coverage: float = 100.0,
) -> RouteMetrics:
    """Build metrics directly so each ranking criterion can be isolated."""
    known = max(0.0, distance - unknown)
    low = max(0.0, known - severe - high - no_travel)
    return RouteMetrics(
        route_id=route_id,
        distance_miles=distance,
        duration_seconds=duration,
        low_miles=low,
        moderate_miles=0.0,
        high_miles=high,
        severe_miles=severe,
        no_travel_miles=no_travel,
        unknown_miles=unknown,
        average_risk=average,
        max_risk=RiskLevel.LOW,
        coverage_pct=coverage,
        no_travel_checkpoints=no_travel_checkpoints,
    )


def route(route_id: str, provider_index: int = 0) -> RouteCandidate:
    return make_route(
        route_id=route_id, label="Route " + route_id, provider_index=provider_index
    )


def recommend(*pairs: tuple[RouteCandidate, RouteMetrics]) -> str | None:
    return rank_routes(list(pairs)).recommended_route_id


class TestCriterionOrder:
    def test_1_fewest_severe_miles_wins(self) -> None:
        assert (
            recommend(
                (route("a", 0), metrics("a", severe=50.0, high=0.0, duration=100.0)),
                (route("b", 1), metrics("b", severe=10.0, high=400.0, duration=9e9)),
            )
            == "b"
        )

    def test_2_fewest_high_miles_breaks_a_severe_tie(self) -> None:
        assert (
            recommend(
                (route("a", 0), metrics("a", severe=10.0, high=80.0, duration=100.0)),
                (route("b", 1), metrics("b", severe=10.0, high=20.0, duration=9e9)),
            )
            == "b"
        )

    def test_3_lowest_average_risk_breaks_a_severe_and_high_tie(self) -> None:
        assert (
            recommend(
                (
                    route("a", 0),
                    metrics("a", severe=5.0, high=5.0, average=1.4, duration=100.0),
                ),
                (
                    route("b", 1),
                    metrics("b", severe=5.0, high=5.0, average=0.9, duration=9e9),
                ),
            )
            == "b"
        )

    def test_4_shortest_travel_time_breaks_an_all_risk_tie(self) -> None:
        assert (
            recommend(
                (
                    route("a", 0),
                    metrics("a", severe=5.0, high=5.0, average=1.0, duration=9000.0),
                ),
                (
                    route("b", 1),
                    metrics("b", severe=5.0, high=5.0, average=1.0, duration=3600.0),
                ),
            )
            == "b"
        )

    def test_criteria_are_applied_in_the_specified_order(self) -> None:
        """A route that is worse on criterion 1 cannot win on 2, 3 and 4."""
        result = rank_routes(
            [
                (
                    route("fast_but_severe", 0),
                    metrics(
                        "fast_but_severe",
                        severe=100.0,
                        high=0.0,
                        average=0.1,
                        duration=60.0,
                    ),
                ),
                (
                    route("slow_but_safe", 1),
                    metrics(
                        "slow_but_safe",
                        severe=0.0,
                        high=90.0,
                        average=1.9,
                        duration=86_400.0,
                    ),
                ),
            ]
        )
        assert result.recommended_route_id == "slow_but_safe"
        assert result.evaluations[1].separated_from_previous_by == "severe_miles"


class TestReportedReasoning:
    @pytest.mark.parametrize(
        ("winner_kwargs", "loser_kwargs", "expected"),
        [
            ({"severe": 0.0}, {"severe": 10.0}, "severe_miles"),
            ({"high": 0.0}, {"high": 10.0}, "high_miles"),
            ({"average": 0.5}, {"average": 1.5}, "average_risk"),
            ({"duration": 100.0}, {"duration": 200.0}, "duration_seconds"),
            ({"unknown": 0.0}, {"unknown": 1.0}, "unknown_miles"),
        ],
    )
    def test_reports_which_criterion_decided(
        self, winner_kwargs: dict, loser_kwargs: dict, expected: str
    ) -> None:
        result = rank_routes(
            [
                (route("w", 0), metrics("w", **winner_kwargs)),
                (route("l", 1), metrics("l", **loser_kwargs)),
            ]
        )
        assert result.recommended_route_id == "w"
        assert result.evaluations[1].separated_from_previous_by == expected

    def test_recommendation_reason_is_human_readable(self) -> None:
        result = rank_routes(
            [
                (route("a", 0), metrics("a", severe=0.0)),
                (route("b", 1), metrics("b", severe=25.0)),
            ]
        )
        assert "fewest Severe miles" in result.recommendation_reason

    def test_first_ranked_route_has_no_separating_criterion(self) -> None:
        result = rank_routes([(route("a", 0), metrics("a"))])
        assert result.evaluations[0].separated_from_previous_by is None

    def test_recommended_accessor_returns_the_winner(self) -> None:
        result = rank_routes(
            [
                (route("a", 0), metrics("a", severe=10.0)),
                (route("b", 1), metrics("b", severe=0.0)),
            ]
        )
        assert result.recommended is not None
        assert result.recommended.route_id == "b"
        assert result.recommended.rank == 1


class TestTieBreaksAndDeterminism:
    def test_fewest_unknown_miles_breaks_a_four_way_tie(self) -> None:
        assert (
            recommend(
                (route("a", 0), metrics("a", unknown=4.0, coverage=96.0)),
                (route("b", 1), metrics("b", unknown=1.0, coverage=99.0)),
            )
            == "b"
        )

    def test_provider_order_breaks_a_total_tie(self) -> None:
        assert (
            recommend(
                (route("second", 1), metrics("second")),
                (route("first", 0), metrics("first")),
            )
            == "first"
        )

    def test_route_id_is_the_final_tie_break(self) -> None:
        """Even identical provider indices must produce a stable answer."""
        assert (
            recommend(
                (route("zulu", 0), metrics("zulu")),
                (route("alpha", 0), metrics("alpha")),
            )
            == "alpha"
        )

    def test_ranking_is_independent_of_input_order(self) -> None:
        pairs = [
            (route("a", 0), metrics("a", severe=5.0, high=10.0, duration=100.0)),
            (route("b", 1), metrics("b", severe=5.0, high=10.0, duration=200.0)),
            (route("c", 2), metrics("c", severe=0.0, high=99.0, duration=300.0)),
        ]
        orders = {
            tuple(e.route_id for e in rank_routes(list(p)).evaluations)
            for p in permutations(pairs)
        }
        assert orders == {("c", "a", "b")}

    def test_repeated_runs_give_an_identical_result(self) -> None:
        pairs = [
            (route("a", 0), metrics("a", severe=1.0)),
            (route("b", 1), metrics("b", severe=1.0)),
            (route("c", 2), metrics("c", severe=1.0)),
        ]
        first = rank_routes(pairs)
        for _ in range(25):
            assert rank_routes(pairs).evaluations == first.evaluations

    def test_float_noise_does_not_flip_the_order(self) -> None:
        """Differences below the comparison tolerance fall through to tie-breaks."""
        assert (
            recommend(
                (route("a", 0), metrics("a", severe=10.0)),
                (route("b", 1), metrics("b", severe=10.0 + 1e-9)),
            )
            == "a"
        )

    def test_ranks_are_sequential(self) -> None:
        result = rank_routes(
            [
                (route("a", 0), metrics("a", severe=30.0)),
                (route("b", 1), metrics("b", severe=10.0)),
                (route("c", 2), metrics("c", severe=20.0)),
            ]
        )
        assert [e.rank for e in result.evaluations] == [1, 2, 3]
        assert [e.route_id for e in result.evaluations] == ["b", "c", "a"]


class TestNoTravelSafetyGate:
    def test_a_blocked_route_is_never_recommended(self) -> None:
        assert (
            recommend(
                (route("blocked", 0), metrics("blocked", no_travel=5.0, duration=60.0)),
                (route("clear", 1), metrics("clear", severe=80.0, duration=99_999.0)),
            )
            == "clear"
        )

    def test_the_gate_outranks_every_assessment_criterion(self) -> None:
        """Blocked loses even when it wins all four criteria outright."""
        result = rank_routes(
            [
                (
                    route("blocked", 0),
                    metrics(
                        "blocked",
                        severe=0.0,
                        high=0.0,
                        average=0.0,
                        duration=60.0,
                        no_travel=1.0,
                    ),
                ),
                (
                    route("clear", 1),
                    metrics(
                        "clear",
                        severe=50.0,
                        high=50.0,
                        average=2.5,
                        duration=86_400.0,
                    ),
                ),
            ]
        )
        assert result.recommended_route_id == "clear"
        assert result.evaluations[0].route_id == "clear"
        assert result.evaluations[1].separated_from_previous_by == "eligibility"

    def test_a_blocked_route_is_still_returned_and_explained(self) -> None:
        result = rank_routes(
            [
                (route("blocked", 0), metrics("blocked", no_travel=12.5)),
                (route("clear", 1), metrics("clear")),
            ]
        )
        blocked = result.evaluations[1]
        assert blocked.route_id == "blocked"
        assert blocked.eligible is False
        assert "No Travel conditions over 12.5 mi" in blocked.ineligibility_reasons[0]

    def test_destination_only_no_travel_blocks_the_route(self) -> None:
        result = rank_routes(
            [
                (
                    route("arrival_storm", 0),
                    metrics("arrival_storm", no_travel=0.0, no_travel_checkpoints=1),
                ),
                (route("clear", 1), metrics("clear", severe=40.0)),
            ]
        )
        assert result.recommended_route_id == "clear"
        assert "at the destination" in result.evaluations[1].ineligibility_reasons[0]

    def test_all_routes_blocked_gives_no_recommendation(self) -> None:
        result = rank_routes(
            [
                (route("a", 0), metrics("a", no_travel=5.0)),
                (route("b", 1), metrics("b", no_travel=50.0)),
            ]
        )
        assert result.recommended_route_id is None
        assert result.recommended is None
        assert "every option encounters No Travel" in result.recommendation_reason

    def test_blocked_routes_are_still_ordered_usefully(self) -> None:
        """With nothing recommendable, the driver still sees least-bad first."""
        result = rank_routes(
            [
                (route("worse", 0), metrics("worse", no_travel=50.0, severe=60.0)),
                (route("better", 1), metrics("better", no_travel=5.0, severe=10.0)),
            ]
        )
        assert [e.route_id for e in result.evaluations] == ["better", "worse"]
        assert all(e.eligible is False for e in result.evaluations)


class TestCoveragePolicy:
    def test_insufficient_coverage_makes_a_route_ineligible(self) -> None:
        result = rank_routes(
            [(route("thin", 0), metrics("thin", unknown=40.0, coverage=60.0))]
        )
        assert result.recommended_route_id is None
        assert "coverage 60.0%" in result.evaluations[0].ineligibility_reasons[0]

    def test_ignorance_cannot_win_a_recommendation(self) -> None:
        """A route with no data scores perfectly on every criterion.

        Without the coverage gate it would beat a fully-forecast route that has
        a little bad weather on it -- a perfect scorecard produced entirely by
        missing data.
        """
        result = rank_routes(
            [
                (
                    route("no_data", 0),
                    metrics(
                        "no_data",
                        severe=0.0,
                        high=0.0,
                        average=None,
                        unknown=100.0,
                        coverage=0.0,
                        duration=60.0,
                    ),
                ),
                (
                    route("forecast", 1),
                    metrics(
                        "forecast",
                        severe=20.0,
                        high=30.0,
                        average=1.8,
                        duration=86_400.0,
                    ),
                ),
            ]
        )
        assert result.recommended_route_id == "forecast"
        assert "no usable forecast data" in (
            result.evaluations[1].ineligibility_reasons[0]
        )

    def test_no_eligible_route_when_data_is_insufficient_everywhere(self) -> None:
        result = rank_routes(
            [
                (route("a", 0), metrics("a", unknown=100.0, coverage=0.0, average=None)),
                (route("b", 1), metrics("b", unknown=60.0, coverage=40.0)),
            ]
        )
        assert result.recommended_route_id is None
        assert "insufficient weather coverage" in result.recommendation_reason

    @pytest.mark.parametrize(
        ("coverage", "eligible"),
        [
            (100.0, True),
            (MIN_COVERAGE_PCT, True),
            (MIN_COVERAGE_PCT - 0.01, False),
            (50.0, False),
        ],
    )
    def test_coverage_threshold_boundary(
        self, coverage: float, eligible: bool
    ) -> None:
        result = rank_routes([(route("a", 0), metrics("a", coverage=coverage))])
        assert result.evaluations[0].eligible is eligible

    def test_the_threshold_is_configurable(self) -> None:
        pairs = [(route("a", 0), metrics("a", unknown=30.0, coverage=70.0))]
        assert rank_routes(pairs).recommended_route_id is None
        assert rank_routes(pairs, min_coverage_pct=50.0).recommended_route_id == "a"


class TestEdgeCases:
    def test_no_routes(self) -> None:
        result = rank_routes([])
        assert result.evaluations == ()
        assert result.recommended_route_id is None
        assert "No routes" in result.recommendation_reason

    def test_a_single_eligible_route_is_recommended(self) -> None:
        result = rank_routes([(route("only", 0), metrics("only", severe=40.0))])
        assert result.recommended_route_id == "only"
        assert "only route" in result.recommendation_reason

    def test_a_single_blocked_route_is_not_recommended(self) -> None:
        result = rank_routes([(route("only", 0), metrics("only", no_travel=1.0))])
        assert result.recommended_route_id is None

    def test_a_route_can_be_ineligible_for_several_reasons(self) -> None:
        result = rank_routes(
            [
                (
                    route("bad", 0),
                    metrics("bad", no_travel=10.0, unknown=50.0, coverage=50.0),
                )
            ]
        )
        assert len(result.evaluations[0].ineligibility_reasons) == 2
