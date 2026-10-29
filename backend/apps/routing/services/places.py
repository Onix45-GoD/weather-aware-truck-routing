"""Place-name suggestions for the trip form.

Thin on purpose: validate the query, ask the configured geocoder, return.
No ranking of our own -- the provider already orders by relevance -- and no
guessing: an empty answer is an empty answer.
"""

from __future__ import annotations

from typing import Final

from apps.routing.providers.base import GeocodingProvider, PlaceSuggestion
from apps.routing.providers.factory import get_geocoding_provider

__all__ = ["MAX_SUGGESTIONS", "MIN_QUERY_LENGTH", "suggest_places"]

#: Below this a type-ahead call is noise: one letter matches everything.
MIN_QUERY_LENGTH: Final = 2
MAX_SUGGESTIONS: Final = 6


def suggest_places(
    query: str, *, limit: int = MAX_SUGGESTIONS, geocoder: GeocodingProvider | None = None
) -> tuple[PlaceSuggestion, ...]:
    """Candidates for a partially typed place. Empty when too short to ask."""
    cleaned = query.strip()
    if len(cleaned) < MIN_QUERY_LENGTH:
        return ()
    geocoder = geocoder or get_geocoding_provider()
    return geocoder.suggest(cleaned, limit=max(1, min(limit, MAX_SUGGESTIONS)))
