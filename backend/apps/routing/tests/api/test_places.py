"""Contract tests for `GET /api/v1/places?q=` (offline, fixture geocoder)."""

from __future__ import annotations

from unittest.mock import patch

from django.test import Client

from apps.routing.providers.errors import ProviderTimeoutError

URL = "/api/v1/places"


def get(q: str | None = None):
    return Client().get(URL, {} if q is None else {"q": q})


class TestSuggestions:
    def test_matches_known_places(self) -> None:
        body = get("den").json()
        assert body["query"] == "den"
        labels = [item["label"] for item in body["suggestions"]]
        assert "Denver, CO, USA" in labels
        first = body["suggestions"][0]
        assert set(first) == {"label", "latitude", "longitude"}

    def test_short_query_is_an_empty_list_not_an_error(self) -> None:
        assert get("d").json()["suggestions"] == []
        assert get("").json()["suggestions"] == []
        assert get().status_code == 200

    def test_unmatched_query_is_empty(self) -> None:
        assert get("zzzz").json()["suggestions"] == []

    def test_at_most_six(self) -> None:
        assert len(get("a").json()["suggestions"]) <= 6
        assert len(get("an").json()["suggestions"]) <= 6

    def test_overlong_query_is_400(self) -> None:
        assert get("x" * 121).status_code == 400

    def test_provider_failure_maps_like_everywhere_else(self) -> None:
        with patch(
            "apps.routing.services.places.get_geocoding_provider",
            side_effect=ProviderTimeoutError("slow", provider="tomtom"),
        ):
            response = get("denver")
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "PROVIDER_TIMEOUT"
