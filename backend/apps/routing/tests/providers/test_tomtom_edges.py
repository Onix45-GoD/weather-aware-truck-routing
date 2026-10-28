"""Edge-case and internal-helper tests for the TomTom adapter.

Split from ``test_tomtom.py``, which covers the main request/response
contract. These exercise the failure and fallback paths.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from apps.routing.providers.errors import InvalidProviderResponseError
from apps.routing.providers.tomtom import (
    TomTomGeocodingProvider,
    TomTomRoutingProvider,
    _close,
    _deduplicate,
)
from apps.routing.tests.conftest import make_route, meridian_geometry
from apps.routing.tests.providers.conftest import (
    CHICAGO,
    DENVER,
    DEPARTURE,
    FAKE_KEY,
)

GEOCODE_HOST = "https://api.tomtom.com/search/2/geocode/"
ROUTING_HOST = "https://api.tomtom.com/routing/1/calculateRoute/"


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


def mock_routing(payload):
    return respx.get(url__startswith=ROUTING_HOST).mock(
        return_value=httpx.Response(200, json=payload)
    )


def points(start: float, end: float, count: int = 5) -> list[dict]:
    step = (end - start) / (count - 1)
    return [
        {"latitude": start + step * index, "longitude": -100.0}
        for index in range(count)
    ]


def multi_leg(first: dict, second: dict) -> dict:
    return {
        "routes": [
            {
                "summary": {"lengthInMeters": 100000, "travelTimeInSeconds": 3600},
                "legs": [first, second],
            }
        ]
    }


class TestGeocodingLabelFallbacks:
    @respx.mock
    def test_a_blank_freeform_address_falls_back_to_the_query(self, geocoder) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "position": {"lat": 40.0, "lon": -100.0},
                            "address": {"freeformAddress": "   "},
                        }
                    ]
                },
            )
        )
        assert geocoder.geocode("Nowhere, NE").label == "Nowhere, NE"

    @respx.mock
    def test_a_missing_score_is_reported_as_unknown_confidence(
        self, geocoder
    ) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(
                200, json={"results": [{"position": {"lat": 40.0, "lon": -100.0}}]}
            )
        )
        assert geocoder.geocode("Somewhere").confidence is None


class TestGeometryErrorPaths:
    @respx.mock
    def test_an_undecodable_encoded_polyline_raises(self, router) -> None:
        mock_routing(
            {
                "routes": [
                    {
                        "summary": {"lengthInMeters": 10, "travelTimeInSeconds": 10},
                        # Truncated varint: decodes a latitude then runs out.
                        "encodedPolyline": "_p~iF~ps|U_ulL",
                    }
                ]
            }
        )
        with pytest.raises(InvalidProviderResponseError, match="could not be decoded"):
            router.routes(DENVER, CHICAGO, DEPARTURE)

    @respx.mock
    @pytest.mark.parametrize(
        "legs",
        [
            ["not-an-object"],
            [{"summary": {}}],
            [{"points": ["not-an-object", "also-not"]}],
        ],
    )
    def test_malformed_legs_raise_typed_errors(self, router, legs) -> None:
        mock_routing(
            {
                "routes": [
                    {
                        "summary": {"lengthInMeters": 10, "travelTimeInSeconds": 10},
                        "legs": legs,
                    }
                ]
            }
        )
        with pytest.raises(InvalidProviderResponseError):
            router.routes(DENVER, CHICAGO, DEPARTURE)


class TestSegmentDurationFallbacks:
    """Per-leg timings are used only when they are genuinely usable."""

    @respx.mock
    def test_a_leg_without_a_summary_falls_back_to_no_timings(self, router) -> None:
        mock_routing(
            multi_leg(
                {"points": points(40.0, 41.0)},
                {
                    "points": points(41.0, 42.0),
                    "summary": {"travelTimeInSeconds": 1800},
                },
            )
        )
        route = router.routes(DENVER, CHICAGO, DEPARTURE).routes[0]
        assert route.segment_durations is None

    @respx.mock
    def test_a_leg_of_coincident_points_does_not_divide_by_zero(
        self, router
    ) -> None:
        """A stalled leg must neither crash nor fabricate an alignment.

        The repeated vertices collapse when the geometry is built, so the
        per-leg span count no longer matches the final geometry. The adapter
        declines to guess and reports no provider timings, letting the domain
        apply its documented fallback instead.
        """
        stuck = [{"latitude": 40.0, "longitude": -100.0} for _ in range(5)]
        mock_routing(
            multi_leg(
                {"points": stuck, "summary": {"travelTimeInSeconds": 400}},
                {
                    "points": [{"latitude": 40.0, "longitude": -100.0}]
                    + points(40.0, 41.0),
                    "summary": {"travelTimeInSeconds": 3200},
                },
            )
        )
        route = router.routes(DENVER, CHICAGO, DEPARTURE).routes[0]
        assert route.segment_durations is None
        assert route.duration_seconds == 3600.0  # the route itself still parses

    @respx.mock
    def test_a_single_point_leg_is_skipped_and_the_rest_still_times(
        self, router
    ) -> None:
        """A degenerate leg is skipped; if the remainder still aligns, its
        genuine timings are kept rather than thrown away."""
        mock_routing(
            multi_leg(
                {
                    "points": [{"latitude": 40.0, "longitude": -100.0}],
                    "summary": {"travelTimeInSeconds": 0},
                },
                {
                    "points": points(40.0, 41.0),
                    "summary": {"travelTimeInSeconds": 3600},
                },
            )
        )
        route = router.routes(DENVER, CHICAGO, DEPARTURE).routes[0]
        assert route.segment_durations is not None
        assert len(route.segment_durations) == len(route.geometry) - 1
        assert sum(route.segment_durations) == pytest.approx(3600.0)


class TestDeduplicationInternals:
    def test_similar_shapes_with_different_summaries_are_kept(self) -> None:
        """A 50-mile detour off a 900-mile run shares most of its length.

        Discarding it would cost the driver a genuinely different option, so
        shape overlap alone is never enough to merge.
        """
        geometry = meridian_geometry(vertices=50)
        fast = make_route(
            route_id="a",
            geometry=geometry,
            distance_miles=900.0,
            duration_seconds=50000.0,
            provider_index=0,
        )
        slow = make_route(
            route_id="b",
            geometry=geometry,
            distance_miles=950.0,
            duration_seconds=62000.0,
            provider_index=1,
        )

        kept, duplicates = _deduplicate([fast, slow])
        assert duplicates == 0
        assert len(kept) == 2

    def test_identical_routes_collapse_to_one(self) -> None:
        geometry = meridian_geometry(vertices=50)
        first = make_route(route_id="a", geometry=geometry, provider_index=0)
        second = make_route(route_id="b", geometry=geometry, provider_index=1)

        kept, duplicates = _deduplicate([first, second])
        assert duplicates == 1
        assert [route.id for route in kept] == ["a"]

    def test_distinct_shapes_are_compared_against_every_survivor(self) -> None:
        a = make_route(
            route_id="a", geometry=meridian_geometry(vertices=30, start_lat=40.0),
            provider_index=0,
        )
        b = make_route(
            route_id="b", geometry=meridian_geometry(vertices=30, start_lat=50.0),
            provider_index=1,
        )
        c = make_route(
            route_id="c", geometry=meridian_geometry(vertices=30, start_lat=60.0),
            provider_index=2,
        )

        kept, duplicates = _deduplicate([a, b, c])
        assert duplicates == 0
        assert [route.id for route in kept] == ["a", "b", "c"]

    def test_closeness_treats_two_zeroes_as_equal(self) -> None:
        assert _close(0.0, 0.0) is True
        assert _close(100.0, 100.5) is True
        assert _close(100.0, 150.0) is False

    def test_an_empty_input_deduplicates_to_nothing(self) -> None:
        assert _deduplicate([]) == ([], 0)
