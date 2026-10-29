"""Type-ahead suggestions: TomTom (mocked with respx) and the fixture gazetteer."""

from __future__ import annotations

import httpx
import pytest
import respx

from apps.routing.providers.base import GeocodingProvider, PlaceSuggestion
from apps.routing.providers.errors import InvalidProviderResponseError, ProviderAuthError
from apps.routing.providers.fixtures import FixtureGeocodingProvider
from apps.routing.providers.tomtom import TomTomGeocodingProvider
from apps.routing.services.places import suggest_places
from apps.routing.tests.providers.conftest import FAKE_KEY

SEARCH_HOST = "https://api.tomtom.com/search/2/search/"


def result(label: str, lat: float, lon: float, kind: str = "Geography") -> dict:
    return {
        "type": kind,
        "score": 5.0,
        "position": {"lat": lat, "lon": lon},
        "address": {"freeformAddress": label},
    }


@pytest.fixture
def geocoder(fast_client):
    return TomTomGeocodingProvider(FAKE_KEY, client=fast_client("tomtom"), cache_ttl_seconds=0)


class TestTomTomSuggest:
    @respx.mock
    def test_parses_results_in_provider_order(self, geocoder) -> None:
        route = respx.get(url__startswith=SEARCH_HOST).mock(
            return_value=httpx.Response(
                200,
                json={"results": [result("Denver, CO", 39.74, -104.99), result("Denver, PA", 40.23, -76.14)]},
            )
        )
        out = geocoder.suggest("den")
        assert [s.label for s in out] == ["Denver, CO", "Denver, PA"]
        assert out[0].coordinate.latitude == 39.74
        sent = route.calls.last.request
        assert sent.url.params["typeahead"] == "true"
        assert sent.url.params["idxSet"] == "Geo,PAD"
        assert sent.url.params["key"] == FAKE_KEY
        assert "den" in str(sent.url)

    @respx.mock
    def test_collapses_duplicate_labels(self, geocoder) -> None:
        respx.get(url__startswith=SEARCH_HOST).mock(
            return_value=httpx.Response(
                200,
                json={"results": [result("Austin, TX", 30.27, -97.74), result("Austin, TX", 30.27, -97.74, "POI")]},
            )
        )
        assert [s.label for s in geocoder.suggest("aus")] == ["Austin, TX"]

    def test_too_short_never_calls_the_provider(self, geocoder) -> None:
        with respx.mock(assert_all_mocked=True):
            assert geocoder.suggest("d") == ()
            assert geocoder.suggest("   ") == ()

    @respx.mock
    def test_limit_is_forwarded_and_capped(self, geocoder) -> None:
        route = respx.get(url__startswith=SEARCH_HOST).mock(return_value=httpx.Response(200, json={"results": []}))
        geocoder.suggest("den", limit=50)
        assert route.calls.last.request.url.params["limit"] == "10"

    @respx.mock
    def test_malformed_body_is_a_typed_error(self, geocoder) -> None:
        respx.get(url__startswith=SEARCH_HOST).mock(return_value=httpx.Response(200, json={"nope": 1}))
        with pytest.raises(InvalidProviderResponseError):
            geocoder.suggest("den")

    @respx.mock
    def test_rejected_key(self, geocoder) -> None:
        respx.get(url__startswith=SEARCH_HOST).mock(return_value=httpx.Response(403))
        with pytest.raises(ProviderAuthError):
            geocoder.suggest("den")


class TestFixtureSuggest:
    def test_substring_match_on_name_or_label(self) -> None:
        out = FixtureGeocodingProvider().suggest("chi")
        assert any(s.label.startswith("Chicago") for s in out)
        assert all(isinstance(s, PlaceSuggestion) for s in out)

    def test_short_or_unknown_is_empty(self) -> None:
        assert FixtureGeocodingProvider().suggest("c") == ()
        assert FixtureGeocodingProvider().suggest("qqq") == ()

    def test_limit(self) -> None:
        assert len(FixtureGeocodingProvider().suggest("a", limit=2)) <= 2


class TestProtocol:
    def test_both_adapters_still_satisfy_the_protocol(self) -> None:
        assert isinstance(FixtureGeocodingProvider(), GeocodingProvider)
        assert isinstance(TomTomGeocodingProvider("k"), GeocodingProvider)


class TestService:
    def test_trims_and_caps(self) -> None:
        out = suggest_places("  den  ", limit=99, geocoder=FixtureGeocodingProvider())
        assert out and len(out) <= 6

    def test_short_query_does_not_touch_the_provider(self) -> None:
        class Exploding:
            name = "x"

            def geocode(self, query):  # pragma: no cover - never called
                raise AssertionError

            def suggest(self, query, *, limit=6):
                raise AssertionError("should not be called")

        assert suggest_places("d", geocoder=Exploding()) == ()
