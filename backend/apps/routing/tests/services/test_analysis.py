"""Orchestration tests.

These verify the *wiring*: that the service hands the right values to the
domain in the right order and reports what the domain decided. They
deliberately do not re-test the thresholds or the ranking comparator -- those
have their own exhaustive suites, and duplicating them here would mean two
places to update when a rule changes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.routing.domain.models import RiskLevel, WeatherSample
from apps.routing.providers.errors import (
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RoutingNoRoutesError,
)
from apps.routing.services.analysis import (
    MAX_CHECKPOINTS_PER_ROUTE,
    AnalysisRequest,
    analyse_trip,
)
from apps.routing.services.errors import AmbiguousLocationError
from apps.routing.tests.services.conftest import (
    CALM,
    DEPARTURE,
    ScriptedWeather,
    StubGeocoder,
    StubRouter,
    make_request,
    snow_at,
    straight_route,
    wind_at,
)


def run(geocoder, router, weather, **overrides):
    return analyse_trip(
        make_request(**overrides), geocoder=geocoder, router=router, weather=weather
    )


class TestHappyPath:
    def test_analyses_every_route(self, geocoder, router, weather) -> None:
        result = run(geocoder, router, weather)

        assert len(result.routes) == 3
        assert result.recommended_route_id is not None
        assert result.ranking.recommendation_reason

    def test_geocodes_both_endpoints(self, geocoder, router, weather) -> None:
        run(geocoder, router, weather)
        assert sorted(geocoder.calls) == ["Chicago, IL", "Denver, CO"]

    def test_reports_the_providers_used(self, geocoder, router, weather) -> None:
        result = run(geocoder, router, weather)
        assert result.providers == {
            "geocoding": "stub",
            "routing": "stub",
            "weather": "scripted",
        }

    def test_checkpoints_cover_each_route_end_to_end(
        self, geocoder, router, weather
    ) -> None:
        for analysed in run(geocoder, router, weather).routes:
            points = analysed.checkpoints
            assert points[0].checkpoint.is_origin
            assert points[-1].checkpoint.is_destination
            assert points[0].checkpoint.distance_from_origin_miles == 0.0
            assert points[-1].checkpoint.distance_from_origin_miles == pytest.approx(
                analysed.route.distance_miles
            )

    def test_segment_miles_sum_to_route_distance(
        self, geocoder, router, weather
    ) -> None:
        for analysed in run(geocoder, router, weather).routes:
            total = sum(point.segment_miles for point in analysed.checkpoints)
            assert total == pytest.approx(analysed.route.distance_miles)

    def test_etas_are_monotonic_and_timezone_aware(
        self, geocoder, router, weather
    ) -> None:
        for analysed in run(geocoder, router, weather).routes:
            etas = [point.checkpoint.eta for point in analysed.checkpoints]
            assert all(eta.tzinfo is not None for eta in etas)
            assert etas == sorted(etas)
            assert etas[0] == DEPARTURE

    def test_final_eta_matches_route_duration(
        self, geocoder, router, weather
    ) -> None:
        for analysed in run(geocoder, router, weather).routes:
            expected = DEPARTURE + timedelta(seconds=analysed.route.duration_seconds)
            assert analysed.arrival_at == expected


class TestCheckpointIntervals:
    @pytest.mark.parametrize("interval", [10, 25, 50])
    def test_each_supported_interval_is_honoured(
        self, geocoder, router, weather, interval: int
    ) -> None:
        result = run(geocoder, router, weather, checkpoint_interval_miles=interval)
        route = result.routes[0]
        spacings = {
            round(
                b.checkpoint.distance_from_origin_miles
                - a.checkpoint.distance_from_origin_miles,
                6,
            )
            for a, b in zip(route.checkpoints[:-2], route.checkpoints[1:-1])
        }
        assert spacings == {float(interval)}

    def test_finer_intervals_produce_more_checkpoints(
        self, geocoder, router, weather
    ) -> None:
        counts = [
            len(run(geocoder, router, weather, checkpoint_interval_miles=i).routes[0].checkpoints)
            for i in (50, 25, 10)
        ]
        assert counts == sorted(counts)

    def test_a_very_long_route_coarsens_rather_than_exploding(
        self, geocoder, weather
    ) -> None:
        """Closes the checkpoint-ceiling open item from Milestone 1."""
        router = StubRouter(
            [straight_route("long", distance_miles=6000.0, duration_seconds=360_000.0)]
        )
        result = analyse_trip(
            make_request(checkpoint_interval_miles=10),
            geocoder=geocoder,
            router=router,
            weather=weather,
        )
        route = result.routes[0]
        assert len(route.checkpoints) <= MAX_CHECKPOINTS_PER_ROUTE + 1
        assert any(
            warning.code == "CHECKPOINT_INTERVAL_COARSENED"
            for warning in result.warnings
        )


class TestWeatherAssociation:
    def test_weather_is_requested_once_for_every_checkpoint(
        self, geocoder, router, weather
    ) -> None:
        """One batched call, not one per route and certainly not one per point."""
        result = run(geocoder, router, weather)
        expected = sum(len(route.checkpoints) for route in result.routes)

        assert len(weather.requests) == 1
        assert weather.requests[0][0] == expected

    def test_each_checkpoint_gets_the_forecast_for_its_own_eta(
        self, geocoder, router
    ) -> None:
        """Wind rises each hour; a checkpoint must see its own arrival hour."""

        def rising(_coordinate, when: datetime) -> WeatherSample:
            hours = int((when - DEPARTURE).total_seconds() // 3600)
            return wind_at(float(max(0, hours)))

        weather = ScriptedWeather(rising)
        route = run(geocoder, router, weather).routes[0]

        for point in route.checkpoints:
            elapsed = (point.checkpoint.eta - DEPARTURE).total_seconds() / 3600.0
            assert point.weather is not None
            # Nearest hour, ties up (D19).
            assert point.weather.wind_mph == pytest.approx(round(elapsed + 1e-9))

    def test_weather_is_keyed_on_position_not_just_time(self, geocoder, router) -> None:
        def by_latitude(coordinate, _when) -> WeatherSample:
            return wind_at(coordinate.latitude)

        weather = ScriptedWeather(by_latitude)
        route = run(geocoder, router, weather).routes[0]
        winds = {point.weather.wind_mph for point in route.checkpoints}
        assert len(winds) > 1


class TestMissingWeather:
    def test_a_forecast_gap_becomes_unknown_not_low(self, geocoder, router) -> None:
        """A hole in the series must never read as calm."""
        # Only the departure hour is forecast, so later checkpoints -- which
        # do own mileage -- fall outside the 30-minute match tolerance.
        weather = ScriptedWeather(
            lambda _c, when: CALM if when <= DEPARTURE else None
        )
        result = run(geocoder, router, weather)
        route = result.routes[0]

        levels = {point.risk.level for point in route.checkpoints}
        assert RiskLevel.UNKNOWN in levels
        assert route.metrics.unknown_miles > 0
        assert route.metrics.coverage_pct < 100.0
        assert route.metrics.low_miles < route.route.distance_miles

    def test_a_gap_at_the_destination_alone_costs_no_mileage(
        self, geocoder, router
    ) -> None:
        """Forward attribution: the destination owns zero forward miles.

        A missing forecast *only* at the arrival point leaves every mile
        accounted for, because each mile is governed by the checkpoint that
        enters it (D6). The destination is still reported UNKNOWN so the
        driver sees it.
        """
        weather = ScriptedWeather(
            lambda _c, when: None if when > DEPARTURE + timedelta(hours=1) else CALM
        )
        route = run(geocoder, router, weather).routes[0]

        assert route.checkpoints[-1].risk.level is RiskLevel.UNKNOWN
        assert route.checkpoints[-1].segment_miles == pytest.approx(0.0)
        assert route.metrics.unknown_miles == pytest.approx(0.0)
        assert route.metrics.coverage_pct == pytest.approx(100.0)

    def test_partial_coverage_raises_a_warning(self, geocoder, router) -> None:
        weather = ScriptedWeather(
            lambda _c, when: CALM if when <= DEPARTURE else None
        )
        result = run(geocoder, router, weather)
        assert any(w.code == "INCOMPLETE_FORECAST" for w in result.warnings)

    def test_null_measurements_are_unknown_not_zero(self, geocoder, router) -> None:
        empty = WeatherSample(wind_mph=None, rain_in_hr=None, snow_in_hr=None)
        result = run(geocoder, router, ScriptedWeather(lambda _c, _w: empty))
        route = result.routes[0]

        assert route.metrics.low_miles == pytest.approx(0.0)
        assert route.metrics.unknown_miles == pytest.approx(
            route.route.distance_miles
        )

    def test_no_route_is_eligible_when_weather_is_missing(
        self, geocoder, router
    ) -> None:
        """Ignorance must not win a recommendation."""
        empty = WeatherSample(wind_mph=None, rain_in_hr=None, snow_in_hr=None)
        result = run(geocoder, router, ScriptedWeather(lambda _c, _w: empty))

        assert result.recommended_route_id is None
        assert any(w.code == "NO_ELIGIBLE_ROUTE" for w in result.warnings)

    def test_a_weather_outage_degrades_instead_of_failing(
        self, geocoder, router
    ) -> None:
        """Routes and ETAs are still useful without a forecast."""
        weather = ScriptedWeather(
            error=ProviderUnavailableError("down", provider="scripted")
        )
        result = run(geocoder, router, weather)

        assert len(result.routes) == 3
        assert result.recommended_route_id is None
        assert any(w.code == "WEATHER_UNAVAILABLE" for w in result.warnings)
        assert all(
            point.risk.level is RiskLevel.UNKNOWN
            for point in result.routes[0].checkpoints
        )


class TestRiskAndRanking:
    def test_the_domain_decides_the_recommendation(self, geocoder, weather) -> None:
        """Route 1 is calm; routes 0 and 2 are severe. The gate is the domain's."""
        router = StubRouter(
            [
                straight_route("storm", provider_index=0, lat_offset=0.0),
                straight_route("calm", provider_index=1, lat_offset=10.0),
            ]
        )

        def by_region(coordinate, _when):
            return CALM if coordinate.latitude > 45 else wind_at(50.0)

        result = analyse_trip(
            make_request(load_weight_lb=10_000),
            geocoder=geocoder,
            router=router,
            weather=ScriptedWeather(by_region),
        )

        assert result.recommended_route_id == "calm"
        storm = next(r for r in result.routes if r.route.id == "storm")
        assert storm.metrics.severe_miles > 0

    def test_cargo_weight_overrides_flow_through_the_whole_workflow(
        self, geocoder, router
    ) -> None:
        """38 mph is High at 40,000 lb and Severe one pound above."""
        weather = ScriptedWeather(lambda _c, _w: wind_at(38.0))

        light = run(geocoder, router, weather, load_weight_lb=40_000.0)
        heavy = run(geocoder, router, weather, load_weight_lb=40_000.01)

        assert light.routes[0].metrics.high_miles > 0
        assert light.routes[0].metrics.severe_miles == pytest.approx(0.0)
        assert heavy.routes[0].metrics.severe_miles > 0
        assert heavy.routes[0].metrics.high_miles == pytest.approx(0.0)
        assert any(
            point.risk.load_override_applied for point in heavy.routes[0].checkpoints
        )

    def test_a_no_travel_route_is_excluded_but_still_returned(
        self, geocoder, weather
    ) -> None:
        router = StubRouter(
            [
                straight_route("blocked", provider_index=0, lat_offset=0.0,
                               duration_seconds=3600.0),
                straight_route("clear", provider_index=1, lat_offset=10.0,
                               duration_seconds=36_000.0),
            ]
        )

        def blizzard_in_the_south(coordinate, _when):
            return CALM if coordinate.latitude > 45 else snow_at(4.0)

        result = analyse_trip(
            make_request(),
            geocoder=geocoder,
            router=router,
            weather=ScriptedWeather(blizzard_in_the_south),
        )

        assert result.recommended_route_id == "clear"
        blocked = next(r for r in result.routes if r.route.id == "blocked")
        assert blocked.metrics.blocked is True
        # Still present, so the UI can explain the rejection.
        assert blocked.route.id in {r.route.id for r in result.routes}

    def test_all_routes_blocked_yields_no_recommendation(
        self, geocoder, router
    ) -> None:
        weather = ScriptedWeather(lambda _c, _w: snow_at(5.0))
        result = run(geocoder, router, weather)

        assert result.recommended_route_id is None
        assert all(route.metrics.blocked for route in result.routes)
        assert any(w.code == "NO_ELIGIBLE_ROUTE" for w in result.warnings)
        assert "No route can be recommended" in result.ranking.recommendation_reason

    def test_ranking_order_is_the_domains(self, geocoder, router, weather) -> None:
        result = run(geocoder, router, weather)
        ranks = [e.rank for e in result.ranking.evaluations]
        assert ranks == sorted(ranks) == list(range(1, len(ranks) + 1))

    def test_analysis_is_deterministic(self, geocoder, router, weather) -> None:
        first = run(geocoder, router, weather)
        for _ in range(3):
            again = run(geocoder, router, weather)
            assert again.recommended_route_id == first.recommended_route_id
            assert [r.route.id for r in again.routes] == [
                r.route.id for r in first.routes
            ]


class TestRouteAlternatives:
    @pytest.mark.parametrize("count", [1, 2, 3])
    def test_returns_exactly_what_the_provider_supplied(
        self, geocoder, weather, count: int
    ) -> None:
        router = StubRouter(
            [
                straight_route(f"r{i}", provider_index=i, lat_offset=i * 2.0)
                for i in range(count)
            ]
        )
        result = analyse_trip(
            make_request(), geocoder=geocoder, router=router, weather=weather
        )
        assert len(result.routes) == count

    @pytest.mark.parametrize("count", [1, 2])
    def test_fewer_than_three_raises_a_warning_and_invents_nothing(
        self, geocoder, weather, count: int
    ) -> None:
        router = StubRouter(
            [
                straight_route(f"r{i}", provider_index=i, lat_offset=i * 2.0)
                for i in range(count)
            ]
        )
        result = analyse_trip(
            make_request(), geocoder=geocoder, router=router, weather=weather
        )
        warning = next(w for w in result.warnings if w.code == "FEWER_ALTERNATIVES")
        assert str(count) in warning.message
        assert len(result.routes) == count

    def test_three_routes_raise_no_shortfall_warning(
        self, geocoder, router, weather
    ) -> None:
        result = run(geocoder, router, weather)
        assert not any(w.code == "FEWER_ALTERNATIVES" for w in result.warnings)

    def test_provider_notices_are_surfaced(self, geocoder, weather) -> None:
        router = StubRouter(notices=("2 near-identical routes merged.",))
        result = analyse_trip(
            make_request(), geocoder=geocoder, router=router, weather=weather
        )
        assert any(w.code == "ROUTING_NOTICE" for w in result.warnings)


class TestEtaSource:
    def test_reports_the_proportional_fallback_honestly(
        self, geocoder, router, weather
    ) -> None:
        result = run(geocoder, router, weather)
        assert result.routes[0].eta_source == "distance_proportional"
        assert any(w.code == "ETA_ESTIMATED" for w in result.warnings)

    def test_reports_provider_timings_when_supplied(self, geocoder, weather) -> None:
        route = straight_route(
            "timed", vertices=5, segment_durations=(3600.0, 1800.0, 900.0, 900.0)
        )
        result = analyse_trip(
            make_request(),
            geocoder=geocoder,
            router=StubRouter([route]),
            weather=weather,
        )
        assert result.routes[0].eta_source == "provider_segments"
        assert not any(w.code == "ETA_ESTIMATED" for w in result.warnings)


class TestForecastOffset:
    def test_offset_shifts_the_effective_departure(self) -> None:
        request = make_request(forecast_offset_hours=6)
        assert request.effective_departure_at == DEPARTURE + timedelta(hours=6)

    def test_offset_reaches_the_routing_provider(
        self, geocoder, router, weather
    ) -> None:
        """Not just a recolour: routing itself is asked about the later time."""
        run(geocoder, router, weather, forecast_offset_hours=6)
        assert router.calls == [DEPARTURE + timedelta(hours=6)]

    def test_offset_shifts_every_checkpoint_eta(
        self, geocoder, router, weather
    ) -> None:
        base = run(geocoder, router, weather)
        later = run(geocoder, router, weather, forecast_offset_hours=12)

        for first, second in zip(base.routes[0].checkpoints, later.routes[0].checkpoints):
            assert second.checkpoint.eta - first.checkpoint.eta == timedelta(hours=12)

    def test_offset_shifts_the_weather_window(
        self, geocoder, router, weather
    ) -> None:
        run(geocoder, router, weather, forecast_offset_hours=6)
        _count, start, _end = weather.requests[0]
        assert start == DEPARTURE + timedelta(hours=6)

    def test_offset_can_change_the_recommendation(self, geocoder) -> None:
        """The whole point of a departure offset, versus a display control."""
        router = StubRouter(
            [
                straight_route("north", provider_index=0, lat_offset=10.0),
                straight_route("south", provider_index=1, lat_offset=0.0),
            ]
        )

        def storm_moves_north(coordinate, when: datetime):
            # Before 18:00 the north is dangerous; after, the south is.
            northern = coordinate.latitude > 45
            early = when < DEPARTURE + timedelta(hours=6)
            dangerous = northern if early else not northern
            return wind_at(50.0) if dangerous else CALM

        weather = ScriptedWeather(storm_moves_north)
        now = analyse_trip(
            make_request(load_weight_lb=10_000),
            geocoder=geocoder, router=router, weather=weather,
        )
        later = analyse_trip(
            make_request(load_weight_lb=10_000, forecast_offset_hours=12),
            geocoder=geocoder, router=router, weather=weather,
        )

        assert now.recommended_route_id != later.recommended_route_id


class TestGeocodingPolicy:
    def test_low_confidence_is_refused(self, router, weather) -> None:
        geocoder = StubGeocoder(confidence=0.2)
        with pytest.raises(AmbiguousLocationError) as exc:
            analyse_trip(
                make_request(), geocoder=geocoder, router=router, weather=weather
            )
        assert exc.value.field in {"origin", "destination"}
        assert exc.value.confidence == pytest.approx(0.2)

    def test_high_confidence_proceeds(self, router, weather) -> None:
        geocoder = StubGeocoder(confidence=0.95)
        result = analyse_trip(
            make_request(), geocoder=geocoder, router=router, weather=weather
        )
        assert result.routes

    def test_missing_confidence_warns_rather_than_assuming_a_good_match(
        self, router, weather
    ) -> None:
        """D27's lesson: absent evidence is not strong evidence."""
        geocoder = StubGeocoder(confidence=None)
        result = analyse_trip(
            make_request(), geocoder=geocoder, router=router, weather=weather
        )
        assert any(w.code == "GEOCODE_CONFIDENCE_UNKNOWN" for w in result.warnings)

    def test_unresolved_locations_propagate(
        self, no_results_geocoder, router, weather
    ) -> None:
        from apps.routing.providers.errors import GeocodingNoResultsError

        with pytest.raises(GeocodingNoResultsError):
            analyse_trip(
                make_request(),
                geocoder=no_results_geocoder,
                router=router,
                weather=weather,
            )


class TestProviderFailures:
    @pytest.mark.parametrize(
        "error",
        [
            RoutingNoRoutesError("no route", provider="stub"),
            ProviderTimeoutError("slow", provider="stub"),
            ProviderRateLimitError("429", provider="stub"),
            ProviderUnavailableError("502", provider="stub"),
        ],
    )
    def test_routing_failures_propagate_rather_than_becoming_empty_results(
        self, geocoder, weather, error
    ) -> None:
        """An outage and 'no safe route' are different answers."""
        with pytest.raises(type(error)):
            analyse_trip(
                make_request(),
                geocoder=geocoder,
                router=StubRouter(error=error),
                weather=weather,
            )


class TestRequestValidation:
    def test_naive_departure_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            AnalysisRequest(
                origin="a", destination="b",
                departure_at=datetime(2026, 11, 2, 12, 0),
                load_weight_lb=1000, checkpoint_interval_miles=25,
            )

    @pytest.mark.parametrize("weight", [0, -1])
    def test_non_positive_weight_is_rejected(self, weight: float) -> None:
        with pytest.raises(ValueError, match="load_weight_lb"):
            make_request(load_weight_lb=weight)

    @pytest.mark.parametrize("interval", [0, 5, 15, 100])
    def test_unsupported_intervals_are_rejected(self, interval: int) -> None:
        with pytest.raises(ValueError, match="10, 25 or 50"):
            make_request(checkpoint_interval_miles=interval)

    @pytest.mark.parametrize("offset", [-1, 49, 1000])
    def test_out_of_range_offsets_are_rejected(self, offset: int) -> None:
        with pytest.raises(ValueError, match="forecast_offset_hours"):
            make_request(forecast_offset_hours=offset)

    def test_departure_is_preserved_alongside_the_effective_time(self) -> None:
        request = make_request(forecast_offset_hours=3)
        assert request.departure_at == DEPARTURE
        assert request.effective_departure_at == DEPARTURE + timedelta(hours=3)
