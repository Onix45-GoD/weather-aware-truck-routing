"""Contract tests for the TomTom geocoding and routing adapters.

Fixtures here are **synthetic**, modelled on TomTom's documented response
schema -- no API key was available to capture a genuine response. See
``tests/fixtures/PROVENANCE.md``; the limitation is recorded there rather than
glossed over.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from apps.routing.domain.models import Coordinate
from apps.routing.providers.errors import (
    GeocodingNoResultsError,
    InvalidProviderResponseError,
    ProviderAuthError,
    ProviderConfigurationError,
    RoutingNoRoutesError,
)
from apps.routing.providers.tomtom import (
    TomTomGeocodingProvider,
    TomTomRoutingProvider,
)
from apps.routing.tests.providers.conftest import (
    CHICAGO,
    DENVER,
    DEPARTURE,
    FAKE_KEY,
    load_fixture,
)

GEOCODE_HOST = "https://api.tomtom.com/search/2/geocode/"
ROUTING_HOST = "https://api.tomtom.com/routing/1/calculateRoute/"


def tomtom(name: str):
    return load_fixture("tomtom", name)


@pytest.fixture
def geocoder(fast_client):
    return TomTomGeocodingProvider(
        FAKE_KEY, client=fast_client("tomtom"), cache_ttl_seconds=0
    )


@pytest.fixture
def router(fast_client):
    return TomTomRoutingProvider(
        FAKE_KEY, client=fast_client("tomtom"), cache_ttl_seconds=0
    )


class TestCredentialHandling:
    @pytest.mark.parametrize("key", ["", "   ", None])
    def test_missing_key_fails_at_construction(self, key) -> None:
        with pytest.raises(ProviderConfigurationError, match="TOMTOM_API_KEY"):
            TomTomGeocodingProvider(key)  # type: ignore[arg-type]

    def test_construction_error_names_the_variable_not_a_value(self) -> None:
        with pytest.raises(ProviderConfigurationError) as exc:
            TomTomRoutingProvider("")
        assert "TOMTOM_API_KEY" in str(exc.value)
        assert "fixtures" in str(exc.value)  # points at the offline escape hatch

    def test_repr_does_not_leak_the_key(self, geocoder) -> None:
        assert FAKE_KEY not in repr(geocoder)
        assert "***" in repr(geocoder)

    @respx.mock
    def test_key_is_sent_as_the_key_query_parameter(self, geocoder) -> None:
        route = respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=tomtom("synthetic_geocode_success.json"))
        )
        geocoder.geocode("Denver, CO")
        assert route.calls.last.request.url.params["key"] == FAKE_KEY

    @respx.mock
    def test_auth_failure_message_omits_the_key(self, geocoder) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(return_value=httpx.Response(403))
        with pytest.raises(ProviderAuthError) as exc:
            geocoder.geocode("Denver, CO")
        assert FAKE_KEY not in str(exc.value)


class TestGeocodingRequest:
    @respx.mock
    def test_builds_the_documented_url(self, geocoder) -> None:
        route = respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=tomtom("synthetic_geocode_success.json"))
        )
        geocoder.geocode("Denver, CO")
        url = str(route.calls.last.request.url)
        assert url.startswith("https://api.tomtom.com/search/2/geocode/")
        assert ".json" in url

    @respx.mock
    def test_url_encodes_the_query(self, geocoder) -> None:
        route = respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=tomtom("synthetic_geocode_success.json"))
        )
        geocoder.geocode("Winston-Salem, NC / US")
        assert "%2F" in str(route.calls.last.request.url)

    @respx.mock
    def test_asks_for_a_single_result(self, geocoder) -> None:
        route = respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=tomtom("synthetic_geocode_success.json"))
        )
        geocoder.geocode("Denver, CO")
        assert route.calls.last.request.url.params["limit"] == "1"


class TestGeocodingParsing:
    @respx.mock
    def test_parses_position_and_label(self, geocoder) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=tomtom("synthetic_geocode_success.json"))
        )
        result = geocoder.geocode("Denver, CO")

        assert result.coordinate == Coordinate(latitude=39.73915, longitude=-104.9847)
        assert result.label == "Denver, CO, United States"
        assert result.provider == "tomtom"
        # From `matchConfidence.score`, NOT the top-level `score`. See
        # TestConfidenceSemantics below.
        assert result.confidence == pytest.approx(1.0)


class TestConfidenceSemantics:
    """TomTom's top-level `score` is not a confidence, despite the docs.

    The published documentation describes `score` as a 0-1 relevance score.
    Real responses return 4.7333083153 for an exact match. Exposing that as
    `confidence` would make any later `confidence > 0.8` threshold pass for
    every result, good or bad. `matchConfidence.score` is the real 0-1 value.

    Only the genuine capture exposed this -- the original synthetic fixture
    had faithfully encoded the documented-but-wrong assumption.
    """

    @respx.mock
    def test_confidence_comes_from_match_confidence_not_score(
        self, geocoder
    ) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "position": {"lat": 40.0, "lon": -100.0},
                            "score": 4.7333083153,
                            "matchConfidence": {"score": 0.75},
                        }
                    ]
                },
            )
        )
        result = geocoder.geocode("Denver")
        assert result.confidence == pytest.approx(0.75)
        assert result.confidence != pytest.approx(4.7333083153)

    @respx.mock
    def test_confidence_is_always_within_zero_and_one(self, geocoder) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_geocode_success.json")
            )
        )
        confidence = geocoder.geocode("Denver, CO").confidence
        assert confidence is not None
        assert 0.0 <= confidence <= 1.0

    @respx.mock
    @pytest.mark.parametrize(
        "match_confidence",
        [None, {}, {"score": "high"}, {"score": 4.73}, {"score": -0.1}, "not-an-object"],
    )
    def test_an_unusable_match_confidence_reports_none(
        self, geocoder, match_confidence
    ) -> None:
        """Better to report nothing than a number meaning something else."""
        result_body = {"position": {"lat": 40.0, "lon": -100.0}, "score": 4.73}
        if match_confidence is not None:
            result_body["matchConfidence"] = match_confidence
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json={"results": [result_body]})
        )
        assert geocoder.geocode("Denver").confidence is None

    @respx.mock
    def test_no_results_raises_rather_than_guessing(self, geocoder) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_geocode_no_results.json")
            )
        )
        with pytest.raises(GeocodingNoResultsError) as exc:
            geocoder.geocode("zzzz nowhere")
        assert exc.value.query == "zzzz nowhere"

    @pytest.mark.parametrize("query", ["", "   "])
    def test_blank_query_is_rejected_without_a_request(self, geocoder, query) -> None:
        with pytest.raises(GeocodingNoResultsError):
            geocoder.geocode(query)

    @respx.mock
    def test_result_without_a_position_is_a_contract_violation(self, geocoder) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_geocode_malformed.json")
            )
        )
        with pytest.raises(InvalidProviderResponseError, match="position"):
            geocoder.geocode("Denver")

    @respx.mock
    @pytest.mark.parametrize(
        "payload",
        [
            [],
            {"summary": {}},
            {"results": "not-a-list"},
            {"results": ["not-an-object"]},
            {"results": [{"position": {"lat": "x", "lon": 1}}]},
            {"results": [{"position": {"lat": 999.0, "lon": 0.0}}]},
        ],
    )
    def test_malformed_payloads_raise_typed_errors(self, geocoder, payload) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=payload)
        )
        with pytest.raises(InvalidProviderResponseError):
            geocoder.geocode("Denver")

    @respx.mock
    def test_falls_back_to_the_query_when_no_address_is_given(self, geocoder) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(
                200, json={"results": [{"position": {"lat": 40.0, "lon": -100.0}}]}
            )
        )
        assert geocoder.geocode("Somewhere").label == "Somewhere"


class TestRoutingRequest:
    @respx.mock
    def test_builds_the_documented_url_with_both_points(self, router) -> None:
        route = respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        router.routes(DENVER, CHICAGO, DEPARTURE)
        url = str(route.calls.last.request.url)
        assert "39.739200,-104.990300:41.878100,-87.629800" in url.replace("%2C", ",").replace(
            "%3A", ":"
        )

    @respx.mock
    def test_requests_truck_mode(self, router) -> None:
        route = respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        router.routes(DENVER, CHICAGO, DEPARTURE)
        assert route.calls.last.request.url.params["travelMode"] == "truck"

    @respx.mock
    def test_requests_two_alternatives_by_default(self, router) -> None:
        route = respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        router.routes(DENVER, CHICAGO, DEPARTURE)
        params = route.calls.last.request.url.params
        assert params["maxAlternatives"] == "2"
        assert params["alternativeType"] == "anyRoute"

    @respx.mock
    def test_passes_the_departure_time(self, router) -> None:
        route = respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        router.routes(DENVER, CHICAGO, DEPARTURE)
        assert route.calls.last.request.url.params["departAt"].startswith(
            "2026-11-02T12:00:00"
        )

    @respx.mock
    def test_alternatives_are_clamped_to_the_provider_range(self, router) -> None:
        route = respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        router.routes(DENVER, CHICAGO, DEPARTURE, max_alternatives=99)
        assert route.calls.last.request.url.params["maxAlternatives"] == "5"

    @respx.mock
    def test_cargo_weight_is_never_sent_as_a_vehicle_weight(self, router) -> None:
        """The assessment gives cargo weight, not gross vehicle weight.

        Sending one as the other would understate the truck's mass by roughly
        30,000 lb and could route it over a bridge it must not cross.
        """
        route = respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        router.routes(DENVER, CHICAGO, DEPARTURE)
        params = route.calls.last.request.url.params
        for forbidden in (
            "vehicleWeight",
            "vehicleAxleWeight",
            "vehicleLength",
            "vehicleHeight",
            "vehicleWidth",
            "vehicleMaxSpeed",
            "vehicleLoadType",
        ):
            assert forbidden not in params

    def test_naive_departure_time_is_rejected(self, router) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            router.routes(DENVER, CHICAGO, datetime(2026, 11, 2, 12, 0))


class TestRoutingParsing:
    @respx.mock
    def test_parses_three_alternatives(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        result = router.routes(DENVER, CHICAGO, DEPARTURE)

        assert len(result.routes) == 3
        assert [r.id for r in result.routes] == ["tomtom-0", "tomtom-1", "tomtom-2"]
        assert [r.provider_index for r in result.routes] == [0, 1, 2]
        assert result.routes[0].label == "Primary route"

    @respx.mock
    def test_normalises_distance_from_metres_to_miles(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        primary = router.routes(DENVER, CHICAGO, DEPARTURE).routes[0]
        # 1_610_000 m / 1609.344 = 1000.4 mi
        assert primary.distance_miles == pytest.approx(1000.41, abs=0.01)

    @respx.mock
    def test_duration_is_carried_through_in_seconds(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        assert router.routes(DENVER, CHICAGO, DEPARTURE).routes[0].duration_seconds == 54000.0

    @respx.mock
    def test_geometry_is_decoded_into_coordinates(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        geometry = router.routes(DENVER, CHICAGO, DEPARTURE).routes[0].geometry
        assert len(geometry) == 40
        assert all(isinstance(point, Coordinate) for point in geometry)
        assert geometry[0].latitude == pytest.approx(39.7392)
        assert geometry[-1].latitude == pytest.approx(41.8781)

    @respx.mock
    def test_alternatives_have_genuinely_different_geometry(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        routes = router.routes(DENVER, CHICAGO, DEPARTURE).routes
        shapes = {tuple((p.latitude, p.longitude) for p in r.geometry) for r in routes}
        assert len(shapes) == 3

    @respx.mock
    def test_encoded_polyline_is_decoded_with_the_domain_decoder(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_encoded_polyline.json")
            )
        )
        geometry = router.routes(DENVER, CHICAGO, DEPARTURE).routes[0].geometry
        assert len(geometry) == 3
        assert geometry[0].latitude == pytest.approx(38.5)
        assert geometry[0].longitude == pytest.approx(-120.2)


class TestSegmentDurations:
    @respx.mock
    def test_single_leg_reports_no_provider_timings(self, router) -> None:
        """A single leg carries no more information than the route total.

        Spreading that total over the geometry would reproduce the domain's
        own fallback while dressing it up as provider data, so the adapter
        returns None and lets the fallback be applied -- and reported --
        honestly.
        """
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        result = router.routes(DENVER, CHICAGO, DEPARTURE)
        assert all(route.segment_durations is None for route in result.routes)
        assert result.has_provider_timings is False

    @respx.mock
    def test_multi_leg_routes_yield_real_segment_timings(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_two_legs.json")
            )
        )
        result = router.routes(DENVER, CHICAGO, DEPARTURE)
        route = result.routes[0]

        assert route.segment_durations is not None
        assert len(route.segment_durations) == len(route.geometry) - 1
        assert result.has_provider_timings is True

    @respx.mock
    def test_multi_leg_timings_reflect_the_slower_first_leg(self, router) -> None:
        """First leg 36000 s, second 18000 s over similar distances."""
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_two_legs.json")
            )
        )
        durations = router.routes(DENVER, CHICAGO, DEPARTURE).routes[0].segment_durations
        assert durations is not None
        half = len(durations) // 2
        assert sum(durations[:half]) > sum(durations[half:])
        assert sum(durations) == pytest.approx(54000.0, rel=0.02)


class TestDeduplication:
    @respx.mock
    def test_identical_routes_are_merged(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_duplicate_alternatives.json")
            )
        )
        result = router.routes(DENVER, CHICAGO, DEPARTURE)

        assert result.returned_count == 3
        assert len(result.routes) == 2
        assert result.duplicates_removed == 1
        assert any("merged" in notice for notice in result.notices)

    @respx.mock
    def test_the_earlier_route_survives_a_merge(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_duplicate_alternatives.json")
            )
        )
        routes = router.routes(DENVER, CHICAGO, DEPARTURE).routes
        assert routes[0].id == "tomtom-0"
        assert routes[0].provider_index == 0

    @respx.mock
    def test_genuinely_different_alternatives_are_kept(self, router) -> None:
        """Losing a real option is worse than showing two similar ones."""
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        result = router.routes(DENVER, CHICAGO, DEPARTURE)
        assert len(result.routes) == 3
        assert result.duplicates_removed == 0


class TestFewerThanThreeRoutes:
    @respx.mock
    def test_two_routes_are_reported_as_two(self, router) -> None:
        """Never invent a third, and never claim three were returned."""
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_two_alternatives.json")
            )
        )
        result = router.routes(DENVER, CHICAGO, DEPARTURE)

        assert len(result.routes) == 2
        assert result.returned_count == 2
        assert any("2 distinct route" in notice for notice in result.notices)

    @respx.mock
    def test_no_routes_raises(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(200, json=tomtom("synthetic_route_empty.json"))
        )
        with pytest.raises(RoutingNoRoutesError):
            router.routes(DENVER, CHICAGO, DEPARTURE)


class TestRoutingMalformedResponses:
    @respx.mock
    @pytest.mark.parametrize(
        "payload",
        [
            [],
            {"formatVersion": "0.0.12"},
            {"routes": "not-a-list"},
            {"routes": ["not-an-object"]},
            {"routes": [{"legs": []}]},
            {"routes": [{"summary": {"lengthInMeters": 1, "travelTimeInSeconds": 1}}]},
            {
                "routes": [
                    {
                        "summary": {"lengthInMeters": 0, "travelTimeInSeconds": 10},
                        "legs": [{"points": [{"latitude": 1, "longitude": 1}]}],
                    }
                ]
            },
            {
                "routes": [
                    {
                        "summary": {"lengthInMeters": 10, "travelTimeInSeconds": 10},
                        "legs": [{"points": [{"latitude": 1, "longitude": 1}]}],
                    }
                ]
            },
            {
                "routes": [
                    {
                        "summary": {"lengthInMeters": 10, "travelTimeInSeconds": 10},
                        "legs": [{"points": [{"latitude": "x", "longitude": 1}] * 2}],
                    }
                ]
            },
        ],
    )
    def test_malformed_payloads_raise_typed_errors(self, router, payload) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(200, json=payload)
        )
        with pytest.raises(InvalidProviderResponseError):
            router.routes(DENVER, CHICAGO, DEPARTURE)

    @respx.mock
    def test_non_numeric_summary_raises(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_malformed.json")
            )
        )
        with pytest.raises(InvalidProviderResponseError, match="lengthInMeters"):
            router.routes(DENVER, CHICAGO, DEPARTURE)

    @respx.mock
    def test_out_of_range_geometry_point_raises(self, router) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200,
                json={
                    "routes": [
                        {
                            "summary": {
                                "lengthInMeters": 10,
                                "travelTimeInSeconds": 10,
                            },
                            "legs": [
                                {
                                    "points": [
                                        {"latitude": 91.0, "longitude": 0.0},
                                        {"latitude": 40.0, "longitude": 0.0},
                                    ]
                                }
                            ],
                        }
                    ]
                },
            )
        )
        with pytest.raises(InvalidProviderResponseError, match="out of range"):
            router.routes(DENVER, CHICAGO, DEPARTURE)


class TestRoutingCaching:
    @respx.mock
    def test_repeated_identical_requests_hit_the_cache(self, fast_client) -> None:
        route = respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        provider = TomTomRoutingProvider(
            FAKE_KEY, client=fast_client("tomtom", cache_ttl_seconds=600)
        )
        provider.routes(DENVER, CHICAGO, DEPARTURE)
        provider.routes(DENVER, CHICAGO, DEPARTURE)
        assert route.call_count == 1

    @respx.mock
    def test_a_different_departure_time_misses_the_cache(self, fast_client) -> None:
        route = respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(
                200, json=tomtom("synthetic_route_three_alternatives.json")
            )
        )
        provider = TomTomRoutingProvider(
            FAKE_KEY, client=fast_client("tomtom", cache_ttl_seconds=600)
        )
        provider.routes(DENVER, CHICAGO, DEPARTURE)
        provider.routes(
            DENVER, CHICAGO, datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)
        )
        assert route.call_count == 2
