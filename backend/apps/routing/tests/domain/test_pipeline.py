"""End-to-end acceptance tests for the domain pipeline.

These wire the whole chain together -- route -> checkpoints -> ETAs ->
classification -> segment attribution -> ranking -- on synthetic data, and
assert the behaviours a reviewer would check by hand. Still no network, no
clock, no keys.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from apps.routing.domain.aggregation import assess_route, summarise_route
from apps.routing.domain.checkpoints import generate_checkpoints
from apps.routing.domain.models import RiskLevel, WeatherSample
from apps.routing.domain.ranking import rank_routes
from apps.routing.tests.conftest import CALM, DEPARTURE, make_route, rain, wind

LIGHT_LOAD = 10_000.0
HEAVY_LOAD = 45_000.0


def analyse(route, samples, load):
    """Run one route through the full domain pipeline."""
    checkpoints = generate_checkpoints(route, 25.0, DEPARTURE)
    assert len(samples) == len(checkpoints)
    return summarise_route(route, assess_route(checkpoints, samples, load))


def storm_at(count: int, index: int, speed: float) -> list[WeatherSample]:
    """Calm everywhere except one checkpoint."""
    samples = [CALM] * count
    samples[index] = wind(speed)
    return samples


class TestFullPipeline:
    def test_clear_weather_route_scores_perfectly(self) -> None:
        route = make_route(distance_miles=100.0, duration_seconds=7200.0)
        checkpoints = generate_checkpoints(route, 25.0, DEPARTURE)
        metrics = analyse(route, [CALM] * len(checkpoints), LIGHT_LOAD)

        assert metrics.low_miles == pytest.approx(100.0)
        assert metrics.average_risk == pytest.approx(0.0)
        assert metrics.coverage_pct == pytest.approx(100.0)
        assert metrics.blocked is False
        assert metrics.max_risk is RiskLevel.LOW

    def test_mileage_is_conserved_through_the_whole_chain(self) -> None:
        route = make_route(distance_miles=873.4, duration_seconds=50_400.0)
        checkpoints = generate_checkpoints(route, 25.0, DEPARTURE)
        samples = storm_at(len(checkpoints), 3, 47.0)

        metrics = summarise_route(route, assess_route(checkpoints, samples, LIGHT_LOAD))

        assert sum(metrics.miles_by_level.values()) == pytest.approx(873.4)
        assert metrics.known_miles == pytest.approx(873.4)

    def test_etas_stay_consistent_with_the_route_duration(self) -> None:
        route = make_route(distance_miles=500.0, duration_seconds=32_400.0)
        checkpoints = generate_checkpoints(route, 10.0, DEPARTURE)

        assert checkpoints[0].eta == DEPARTURE
        assert checkpoints[-1].eta == DEPARTURE + timedelta(seconds=32_400.0)
        etas = [c.eta for c in checkpoints]
        assert etas == sorted(etas)

    def test_identical_weather_scores_identically_at_every_interval(self) -> None:
        """Controlled constant conditions: the algorithm must not care about
        sampling density. (Real forecasts legitimately differ between
        intervals because finer sampling discovers weather coarser sampling
        misses -- that is a property of the data, not of the algorithm, so it
        is not asserted here.)"""
        route = make_route(distance_miles=500.0, duration_seconds=32_400.0)

        results = []
        for interval in (10.0, 25.0, 50.0):
            checkpoints = generate_checkpoints(route, interval, DEPARTURE)
            samples = [wind(37.0)] * len(checkpoints)
            results.append(
                summarise_route(route, assess_route(checkpoints, samples, LIGHT_LOAD))
            )

        for metrics in results:
            assert metrics.high_miles == pytest.approx(500.0)
            assert metrics.average_risk == pytest.approx(2.0)


class TestLoadSensitivity:
    def test_the_same_weather_ranks_differently_with_a_heavier_load(self) -> None:
        """38 mph wind is High at 40,000 lb and Severe one pound above it.

        Both routes are uniformly High risk, but only route A's risk comes from
        wind, so only route A is exposed to the cargo override. Route B's High
        comes from rain, which no load rule touches.

        At 40,000 lb the two tie on Severe miles (0 each), High miles (100
        each) and average risk (2.0 each), so criterion 4 decides and the
        faster route A wins. One pound heavier, route A's miles become Severe
        and route B wins outright on criterion 1.
        """
        route_a = make_route(
            route_id="a", label="Windy", distance_miles=100.0,
            duration_seconds=7200.0, provider_index=0,
        )
        route_b = make_route(
            route_id="b", label="Rainy detour", distance_miles=100.0,
            duration_seconds=10_800.0, provider_index=1,
        )

        checkpoints = generate_checkpoints(route_a, 25.0, DEPARTURE)
        windy = [wind(38.0)] * len(checkpoints)
        rainy = [rain(0.30)] * len(checkpoints)

        def rank(load: float) -> str | None:
            return rank_routes(
                [
                    (route_a, analyse(route_a, windy, load)),
                    (route_b, analyse(route_b, rainy, load)),
                ]
            ).recommended_route_id

        # Sanity: at 40,000 lb the override has not fired, so the two routes
        # really are tied on all three risk criteria.
        at_limit_a = analyse(route_a, windy, 40_000.0)
        at_limit_b = analyse(route_b, rainy, 40_000.0)
        assert at_limit_a.severe_miles == at_limit_b.severe_miles == 0.0
        assert at_limit_a.high_miles == at_limit_b.high_miles == 100.0

        assert rank(40_000.0) == "a"
        assert rank(40_000.01) == "b"


class TestSafetyBehaviour:
    def test_a_single_no_travel_checkpoint_blocks_an_otherwise_perfect_route(
        self,
    ) -> None:
        fast = make_route(
            route_id="fast", label="Fast", distance_miles=100.0,
            duration_seconds=7200.0, provider_index=0,
        )
        slow = make_route(
            route_id="slow", label="Slow", distance_miles=140.0,
            duration_seconds=18_000.0, provider_index=1,
        )

        fast_points = generate_checkpoints(fast, 25.0, DEPARTURE)
        slow_points = generate_checkpoints(slow, 25.0, DEPARTURE)

        result = rank_routes(
            [
                (
                    fast,
                    analyse(
                        fast,
                        storm_at(len(fast_points), 2, 58.0),
                        HEAVY_LOAD,
                    ),
                ),
                (slow, analyse(slow, [CALM] * len(slow_points), HEAVY_LOAD)),
            ]
        )

        assert result.recommended_route_id == "slow"
        assert result.evaluations[1].route_id == "fast"
        assert result.evaluations[1].eligible is False

    def test_every_route_blocked_yields_no_recommendation(self) -> None:
        routes = [
            make_route(
                route_id=str(index), label="Route " + str(index),
                distance_miles=100.0, duration_seconds=7200.0,
                provider_index=index,
            )
            for index in range(3)
        ]
        pairs = []
        for route in routes:
            points = generate_checkpoints(route, 25.0, DEPARTURE)
            pairs.append(
                (route, analyse(route, storm_at(len(points), 1, 60.0), LIGHT_LOAD))
            )

        result = rank_routes(pairs)

        assert result.recommended_route_id is None
        assert len(result.evaluations) == 3
        assert all(e.eligible is False for e in result.evaluations)
        assert "Consider delaying departure" in result.recommendation_reason

    def test_a_forecast_blackout_prevents_a_recommendation(self) -> None:
        route = make_route(distance_miles=100.0, duration_seconds=7200.0)
        points = generate_checkpoints(route, 25.0, DEPARTURE)

        result = rank_routes([(route, analyse(route, [None] * len(points), LIGHT_LOAD))])

        assert result.recommended_route_id is None
        assert result.evaluations[0].metrics.unknown_miles == pytest.approx(100.0)
        assert result.evaluations[0].metrics.average_risk is None


class TestDomainPurity:
    def test_the_domain_imports_no_framework_or_io_modules(self) -> None:
        """Guards the architectural boundary the whole design rests on."""
        import ast
        from pathlib import Path

        forbidden = {
            "django",
            "rest_framework",
            "httpx",
            "requests",
            "urllib",
            "socket",
            "os",
            "random",
            "time",
        }
        domain = Path(__file__).resolve().parents[2] / "domain"
        offenders: list[str] = []

        for module in sorted(domain.glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names = [node.module or ""]
                for name in names:
                    if name.split(".")[0] in forbidden:
                        offenders.append(module.name + " imports " + name)

        assert offenders == []

    def test_the_domain_never_reads_the_clock(self) -> None:
        """`datetime.now`/`utcnow` would make results irreproducible."""
        from pathlib import Path

        domain = Path(__file__).resolve().parents[2] / "domain"
        for module in sorted(domain.glob("*.py")):
            source = module.read_text(encoding="utf-8")
            assert "datetime.now" not in source, module.name
            assert "utcnow" not in source, module.name
