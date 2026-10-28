"""Contract tests against **genuine** captured TomTom responses.

These skip until a real capture exists. Run
``python scripts/capture_tomtom_fixtures.py`` with ``TOMTOM_API_KEY`` set and
they activate automatically -- closing the limitation recorded in
docs/decisions.md D26.

They stay fully offline: the captured body is replayed through ``respx``, so
no credential and no network are needed to run them once the fixture is in the
repository.

The point of a *separate* module is honesty. The synthetic fixtures in
``test_tomtom.py`` prove the adapter handles the documented schema; only these
prove it handles what TomTom actually sends. Conflating the two would make the
suite look like it had evidence it does not have.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from apps.routing.domain.models import Coordinate
from apps.routing.providers.errors import InvalidProviderResponseError
from apps.routing.providers.tomtom import (
    TomTomGeocodingProvider,
    TomTomRoutingProvider,
)
from apps.routing.tests.providers.conftest import (
    CHICAGO,
    DENVER,
    DEPARTURE,
    FAKE_KEY,
    FIXTURE_ROOT,
)

GEOCODE_HOST = "https://api.tomtom.com/search/2/geocode/"
ROUTING_HOST = "https://api.tomtom.com/routing/1/calculateRoute/"

TOMTOM_FIXTURES = FIXTURE_ROOT / "tomtom"
REAL_GEOCODE = TOMTOM_FIXTURES / "real_geocode_denver.json"
REAL_ROUTE = TOMTOM_FIXTURES / "real_route_denver_chicago.json"

_SKIP_REASON = (
    "No genuine TomTom capture in the repository. Run "
    "`python scripts/capture_tomtom_fixtures.py` with TOMTOM_API_KEY set. "
    "See docs/decisions.md D26."
)


def _load(path: Path):
    if not path.exists():
        pytest.skip(_SKIP_REASON)
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def real_geocode():
    return _load(REAL_GEOCODE)


@pytest.fixture
def real_route():
    return _load(REAL_ROUTE)


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


class TestRealGeocodingResponse:
    @respx.mock
    def test_parses_a_genuine_geocoding_response(self, geocoder, real_geocode) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=real_geocode)
        )
        result = geocoder.geocode("Denver, CO")

        assert isinstance(result.coordinate, Coordinate)
        assert 39.0 < result.coordinate.latitude < 40.5
        assert -105.5 < result.coordinate.longitude < -104.5
        assert result.label.strip()
        assert result.provider == "tomtom"

    def test_the_genuine_score_is_not_a_zero_to_one_confidence(
        self, real_geocode
    ) -> None:
        """Pins the defect the real capture exposed.

        TomTom's documentation calls the top-level `score` a 0-1 relevance
        score. The genuine response returns 4.73 for an exact match. This
        test fails if a future capture ever makes the documented claim true,
        which would mean the workaround should be revisited.
        """
        score = real_geocode["results"][0]["score"]
        assert score > 1.0, "if score is now 0-1, re-examine _match_confidence"

    @respx.mock
    def test_confidence_from_genuine_data_is_a_real_confidence(
        self, geocoder, real_geocode
    ) -> None:
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=real_geocode)
        )
        confidence = geocoder.geocode("Denver, CO").confidence

        assert confidence is not None
        assert 0.0 <= confidence <= 1.0
        assert confidence != pytest.approx(real_geocode["results"][0]["score"])

    @respx.mock
    def test_a_genuine_response_without_results_is_handled(
        self, geocoder, real_geocode
    ) -> None:
        emptied = {**real_geocode, "results": []}
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=emptied)
        )
        from apps.routing.providers.errors import GeocodingNoResultsError

        with pytest.raises(GeocodingNoResultsError):
            geocoder.geocode("Denver, CO")

    @respx.mock
    def test_a_genuine_response_missing_position_raises(
        self, geocoder, real_geocode
    ) -> None:
        damaged = json.loads(json.dumps(real_geocode))
        damaged["results"][0].pop("position", None)
        respx.get(url__startswith=GEOCODE_HOST).mock(
            return_value=httpx.Response(200, json=damaged)
        )
        with pytest.raises(InvalidProviderResponseError, match="position"):
            geocoder.geocode("Denver, CO")


class TestRealRoutingResponse:
    @respx.mock
    def test_parses_genuine_route_alternatives(self, router, real_route) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(200, json=real_route)
        )
        result = router.routes(DENVER, CHICAGO, DEPARTURE)

        # However many TomTom actually returned is what we assert on. The
        # count is never padded to three.
        assert 1 <= len(result.routes) <= 3
        assert result.returned_count == len(real_route["routes"])
        assert len({route.id for route in result.routes}) == len(result.routes)

    @respx.mock
    def test_decodes_genuine_route_geometry(self, router, real_route) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(200, json=real_route)
        )
        route = router.routes(DENVER, CHICAGO, DEPARTURE).routes[0]

        assert len(route.geometry) > 50, "a real 900-mile route has many vertices"
        assert all(isinstance(point, Coordinate) for point in route.geometry)
        # Spans roughly Denver -> Chicago.
        assert abs(route.geometry[0].latitude - DENVER.latitude) < 1.0
        assert abs(route.geometry[-1].latitude - CHICAGO.latitude) < 1.0

    @respx.mock
    def test_normalises_genuine_distance_and_duration(
        self, router, real_route
    ) -> None:
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(200, json=real_route)
        )
        route = router.routes(DENVER, CHICAGO, DEPARTURE).routes[0]

        metres = real_route["routes"][0]["summary"]["lengthInMeters"]
        seconds = real_route["routes"][0]["summary"]["travelTimeInSeconds"]

        assert route.distance_miles == pytest.approx(metres / 1609.344)
        assert route.duration_seconds == float(seconds)
        # Denver to Chicago by road is ~1,000 mi at a plausible truck average.
        assert 900 < route.distance_miles < 1200
        assert 40_000 < route.duration_seconds < 90_000

    @respx.mock
    def test_genuine_alternatives_are_distinct(self, router, real_route) -> None:
        if len(real_route.get("routes", [])) < 2:
            pytest.skip("the capture contains only one route; nothing to compare")

        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(200, json=real_route)
        )
        routes = router.routes(DENVER, CHICAGO, DEPARTURE).routes
        shapes = {
            tuple((p.latitude, p.longitude) for p in route.geometry)
            for route in routes
        }
        assert len(shapes) == len(routes), "survivors must be genuinely distinct"

    @respx.mock
    def test_a_genuine_response_with_damaged_summary_raises(
        self, router, real_route
    ) -> None:
        damaged = json.loads(json.dumps(real_route))
        damaged["routes"][0]["summary"]["lengthInMeters"] = "a long way"
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(200, json=damaged)
        )
        with pytest.raises(InvalidProviderResponseError, match="lengthInMeters"):
            router.routes(DENVER, CHICAGO, DEPARTURE)

    @respx.mock
    def test_a_genuine_response_without_geometry_raises(
        self, router, real_route
    ) -> None:
        damaged = json.loads(json.dumps(real_route))
        damaged["routes"][0].pop("legs", None)
        damaged["routes"][0].pop("encodedPolyline", None)
        respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(200, json=damaged)
        )
        with pytest.raises(InvalidProviderResponseError):
            router.routes(DENVER, CHICAGO, DEPARTURE)


class TestCargoWeightSafetyAgainstRealResponse:
    @respx.mock
    def test_no_vehicle_weight_is_sent_when_routing_for_real(
        self, router, real_route
    ) -> None:
        """The D16 rule, re-asserted on the real request path.

        Cargo weight is not gross vehicle weight. Sending one as the other
        could route a loaded truck over a bridge it must not cross.
        """
        route = respx.get(url__startswith=ROUTING_HOST).mock(
            return_value=httpx.Response(200, json=real_route)
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
            "vehicleCommercial",
        ):
            assert forbidden not in params
        assert params["travelMode"] == "truck"


class TestCaptureHygiene:
    """Whatever is captured must never carry a credential into the repo."""

    @pytest.mark.parametrize("path", [REAL_GEOCODE, REAL_ROUTE])
    def test_no_fixture_contains_a_key_shaped_query_parameter(
        self, path: Path
    ) -> None:
        if not path.exists():
            pytest.skip(_SKIP_REASON)
        text = path.read_text(encoding="utf-8")
        for marker in ("key=", "apiKey=", "api_key=", "subscription-key"):
            assert marker not in text, f"{path.name} may embed a credential"

    def test_the_capture_script_exists_and_refuses_without_a_key(self) -> None:
        """The limitation is closeable in one command, not by improvisation."""
        script = (
            Path(__file__).resolve().parents[4] / "scripts/capture_tomtom_fixtures.py"
        )
        assert script.exists()
        source = script.read_text(encoding="utf-8")
        assert "TOMTOM_API_KEY" in source
        assert "os.environ" in source
