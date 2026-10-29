"""TomTom geocoding and truck-routing adapters.

Endpoints (TomTom docs, checked 2026-10-28):

* Geocoding  ``GET https://api.tomtom.com/search/2/geocode/{query}.json``
* Routing    ``GET https://api.tomtom.com/routing/1/calculateRoute/{locs}/json``

Both authenticate with a ``key`` query parameter, which is why every log
line, exception and cache key goes through :func:`...http.redact` first.

Cargo weight is deliberately NOT sent
-------------------------------------
TomTom's ``vehicleWeight`` parameter means **gross vehicle weight** -- tractor
plus trailer plus cargo. The assessment gives us only the *cargo load weight*.
Passing one as the other would understate the vehicle's real mass by roughly
30,000 lb and could route a heavy truck over a bridge it must not cross, so
this adapter sends no vehicle-weight parameter at all.

The consequence, stated plainly rather than papered over: returned routes
respect generic truck restrictions (``travelMode=truck``) but **not**
weight-, height-, length- or axle-specific ones, because we do not have that
data and will not invent it. The assessment's cargo-weight rules are a
*risk-scoring* input and live in :mod:`apps.routing.domain.risk`, which is the
only place they belong. Collecting real vehicle specifications would be the
fix; guessing them would not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final
from urllib.parse import quote

from apps.routing.domain.geo import decode_polyline, haversine_miles
from apps.routing.domain.models import Coordinate, RouteCandidate

from .base import GeocodeResult, PlaceSuggestion, RouteSet
from .errors import (
    GeocodingNoResultsError,
    InvalidProviderResponseError,
    ProviderConfigurationError,
    RoutingNoRoutesError,
)
from .http import DEFAULT_RETRY_POLICY, ProviderHttpClient, RetryPolicy

__all__ = [
    "TomTomGeocodingProvider",
    "TomTomRoutingProvider",
]

PROVIDER_NAME: Final = "tomtom"
GEOCODE_URL: Final = "https://api.tomtom.com/search/2/geocode/{query}.json"
#: Fuzzy search with `typeahead=true` is the documented type-ahead product.
#: `idxSet=Geo,PAD` limits results to geographies (cities, counties,
#: states) and point addresses -- what a trip origin or destination is.
SUGGEST_URL: Final = "https://api.tomtom.com/search/2/search/{query}.json"
ROUTING_URL: Final = "https://api.tomtom.com/routing/1/calculateRoute/{locations}/json"

METRES_PER_MILE: Final = 1609.344

#: Two routes count as duplicates only when they are near-identical on *both*
#: shape and summary. Deliberately strict: wrongly discarding a genuinely
#: different alternative loses the driver a real option, which is worse than
#: showing two similar ones.
GEOMETRY_OVERLAP_THRESHOLD: Final = 0.98
SUMMARY_TOLERANCE: Final = 0.01  # 1% on both distance and duration

#: Decimal places used when comparing shapes. Five places is ~1 m -- fine
#: enough that two routes down different carriageways stay distinct.
SHAPE_PRECISION: Final = 5


class _TomTomBase:
    """Shared construction and credential handling."""

    name = PROVIDER_NAME

    def __init__(
        self,
        api_key: str,
        *,
        client: ProviderHttpClient | None = None,
        cache_ttl_seconds: int = 600,
        retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    ) -> None:
        if not api_key or not api_key.strip():
            # Fail at construction, not mid-analysis. The message names the
            # variable, never the value.
            raise ProviderConfigurationError(
                "TomTom API key is not configured. Set TOMTOM_API_KEY, or "
                "select the `fixtures` provider to run without credentials.",
                provider=PROVIDER_NAME,
            )
        self._api_key = api_key.strip()
        self.client = client or ProviderHttpClient(
            provider=PROVIDER_NAME,
            retry_policy=retry_policy,
            cache_ttl_seconds=cache_ttl_seconds,
        )

    def __repr__(self) -> str:
        # Defensive: a bare repr in a log or traceback must not leak the key.
        return f"<{type(self).__name__} provider={PROVIDER_NAME} key=***>"


class TomTomGeocodingProvider(_TomTomBase):
    """Resolves free-text places via TomTom Search v2."""

    def geocode(self, query: str) -> GeocodeResult:
        """Resolve ``query`` to its single best match.

        Results come back sorted by descending score, so the first is the best
        match. An empty result set raises rather than returning a guess -- a
        silently wrong origin would poison the entire analysis.
        """
        cleaned = query.strip()
        if not cleaned:
            raise GeocodingNoResultsError(
                "Enter an origin and a destination.",
                provider=PROVIDER_NAME,
                query=query,
            )

        url = GEOCODE_URL.format(query=quote(cleaned, safe=""))
        payload = self.client.get_json(url, {"key": self._api_key, "limit": 1})

        if not isinstance(payload, Mapping):
            raise InvalidProviderResponseError(
                f"geocoding: expected a JSON object, got {type(payload).__name__}.",
                provider=PROVIDER_NAME,
            )

        results = payload.get("results")
        if not isinstance(results, list):
            raise InvalidProviderResponseError(
                "geocoding: response has no `results` array.", provider=PROVIDER_NAME
            )
        if not results:
            raise GeocodingNoResultsError(
                f"No location found for {cleaned!r}. Try adding a city or state.",
                provider=PROVIDER_NAME,
                query=cleaned,
            )

        return self._parse_result(results[0], cleaned)

    def suggest(self, query: str, *, limit: int = 6) -> tuple[PlaceSuggestion, ...]:
        """Type-ahead candidates. Empty for a blank or unmatched query."""
        cleaned = query.strip()
        if len(cleaned) < 2:
            return ()
        url = SUGGEST_URL.format(query=quote(cleaned, safe=""))
        payload = self.client.get_json(
            url,
            {
                "key": self._api_key,
                "limit": max(1, min(limit, 10)),
                "typeahead": "true",
                "idxSet": "Geo,PAD",
            },
        )
        if not isinstance(payload, Mapping):
            raise InvalidProviderResponseError(
                f"suggest: expected a JSON object, got {type(payload).__name__}.",
                provider=PROVIDER_NAME,
            )
        results = payload.get("results")
        if not isinstance(results, list):
            raise InvalidProviderResponseError(
                "suggest: response has no `results` array.", provider=PROVIDER_NAME
            )
        seen: set[str] = set()
        suggestions: list[PlaceSuggestion] = []
        for entry in results:
            parsed = self._parse_result(entry, cleaned)
            # TomTom returns the same town under several entity types;
            # one label is enough for a picker.
            if parsed.label in seen:
                continue
            seen.add(parsed.label)
            suggestions.append(
                PlaceSuggestion(
                    label=parsed.label, coordinate=parsed.coordinate, provider=PROVIDER_NAME
                )
            )
        return tuple(suggestions)

    @staticmethod
    def _parse_result(result: Any, query: str) -> GeocodeResult:
        if not isinstance(result, Mapping):
            raise InvalidProviderResponseError(
                "geocoding: result entry is not an object.", provider=PROVIDER_NAME
            )

        position = result.get("position")
        if not isinstance(position, Mapping):
            raise InvalidProviderResponseError(
                "geocoding: result has no `position` object.", provider=PROVIDER_NAME
            )

        latitude = position.get("lat")
        longitude = position.get("lon")
        if not _is_number(latitude) or not _is_number(longitude):
            raise InvalidProviderResponseError(
                "geocoding: `position.lat`/`position.lon` are not numbers.",
                provider=PROVIDER_NAME,
            )

        try:
            coordinate = Coordinate(latitude=float(latitude), longitude=float(longitude))
        except ValueError as exc:
            raise InvalidProviderResponseError(
                f"geocoding: returned position is out of range ({exc}).",
                provider=PROVIDER_NAME,
            ) from exc

        address = result.get("address")
        label = query
        if isinstance(address, Mapping):
            freeform = address.get("freeformAddress")
            if isinstance(freeform, str) and freeform.strip():
                label = freeform.strip()

        return GeocodeResult(
            coordinate=coordinate,
            label=label,
            provider=PROVIDER_NAME,
            confidence=_match_confidence(result),
        )


class TomTomRoutingProvider(_TomTomBase):
    """Truck-route alternatives via TomTom Routing v1."""

    def routes(
        self,
        origin: Coordinate,
        destination: Coordinate,
        departure_time: datetime,
        *,
        max_alternatives: int = 2,
    ) -> RouteSet:
        """Request a truck route plus up to ``max_alternatives`` alternatives.

        Returns exactly the distinct routes the provider supplied. If it finds
        only one, one comes back with a notice explaining why -- the count is
        never padded to three.
        """
        if departure_time.tzinfo is None:
            raise ValueError("departure_time must be timezone-aware")
        # TomTom accepts 0-5; the assessment wants at most three candidates.
        alternatives = max(0, min(5, max_alternatives))

        locations = (
            f"{origin.latitude:.6f},{origin.longitude:.6f}:"
            f"{destination.latitude:.6f},{destination.longitude:.6f}"
        )
        params: dict[str, Any] = {
            "key": self._api_key,
            "travelMode": "truck",
            "maxAlternatives": alternatives,
            # `anyRoute` asks for genuinely different alternatives rather than
            # only ones that beat the primary on time -- we want options that
            # differ in *weather exposure*, which TomTom knows nothing about.
            "alternativeType": "anyRoute",
            "routeRepresentation": "polyline",
            "traffic": "true",
            "departAt": _rfc3339(departure_time),
            # NOTE: no vehicleWeight. See the module docstring.
        }

        payload = self.client.get_json(
            ROUTING_URL.format(locations=locations), params
        )

        if not isinstance(payload, Mapping):
            raise InvalidProviderResponseError(
                f"routing: expected a JSON object, got {type(payload).__name__}.",
                provider=PROVIDER_NAME,
            )

        raw_routes = payload.get("routes")
        if not isinstance(raw_routes, list):
            raise InvalidProviderResponseError(
                "routing: response has no `routes` array.", provider=PROVIDER_NAME
            )
        if not raw_routes:
            raise RoutingNoRoutesError(
                "No truck route could be found between these locations.",
                provider=PROVIDER_NAME,
            )

        parsed = [
            self._parse_route(raw, index) for index, raw in enumerate(raw_routes)
        ]
        distinct, duplicates = _deduplicate(parsed)

        notices: list[str] = []
        wanted = alternatives + 1
        if duplicates:
            notices.append(
                f"{duplicates} near-identical route"
                f"{'s' if duplicates > 1 else ''} merged."
            )
        if len(distinct) < wanted:
            notices.append(
                f"TomTom returned {len(distinct)} distinct route"
                f"{'s' if len(distinct) != 1 else ''} of the {wanted} requested; "
                "no further alternatives exist for this trip."
            )

        return RouteSet(
            routes=tuple(distinct),
            provider=PROVIDER_NAME,
            requested_alternatives=alternatives,
            returned_count=len(parsed),
            duplicates_removed=duplicates,
            notices=tuple(notices),
        )

    # -- parsing ------------------------------------------------------------

    def _parse_route(self, raw: Any, index: int) -> RouteCandidate:
        if not isinstance(raw, Mapping):
            raise InvalidProviderResponseError(
                "routing: route entry is not an object.", provider=PROVIDER_NAME
            )

        summary = raw.get("summary")
        if not isinstance(summary, Mapping):
            raise InvalidProviderResponseError(
                "routing: route has no `summary` object.", provider=PROVIDER_NAME
            )

        metres = summary.get("lengthInMeters")
        seconds = summary.get("travelTimeInSeconds")
        if not _is_number(metres) or not _is_number(seconds):
            raise InvalidProviderResponseError(
                "routing: summary lacks numeric `lengthInMeters` / "
                "`travelTimeInSeconds`.",
                provider=PROVIDER_NAME,
            )
        if float(metres) <= 0 or float(seconds) <= 0:
            raise InvalidProviderResponseError(
                "routing: route reports a non-positive distance or duration.",
                provider=PROVIDER_NAME,
            )

        legs = raw.get("legs")
        geometry = self._geometry(raw, legs)
        if len(geometry) < 2:
            raise InvalidProviderResponseError(
                "routing: route geometry has fewer than two points.",
                provider=PROVIDER_NAME,
            )

        return RouteCandidate(
            # TomTom assigns no route identifier, so a stable internal one is
            # derived from the provider name and response position.
            id=f"{PROVIDER_NAME}-{index}",
            label="Primary route" if index == 0 else f"Alternative {index}",
            geometry=geometry,
            distance_miles=float(metres) / METRES_PER_MILE,
            duration_seconds=float(seconds),
            provider_index=index,
            segment_durations=_leg_segment_durations(legs, geometry, float(seconds)),
        )

    def _geometry(self, raw: Mapping[str, Any], legs: Any) -> tuple[Coordinate, ...]:
        """Extract geometry from whichever representation TomTom returned.

        ``routeRepresentation=polyline`` yields explicit lat/lon objects per
        leg, which is what we request. ``encodedPolyline`` is also handled,
        decoded with the domain's own
        :func:`~apps.routing.domain.geo.decode_polyline`, so switching
        representation does not need a new parser.
        """
        encoded = raw.get("encodedPolyline")
        if isinstance(encoded, str) and encoded:
            precision = raw.get("encodedPolylinePrecision", 5)
            try:
                return decode_polyline(
                    encoded, precision=int(precision) if _is_number(precision) else 5
                )
            except ValueError as exc:
                raise InvalidProviderResponseError(
                    f"routing: encoded polyline could not be decoded ({exc}).",
                    provider=PROVIDER_NAME,
                ) from exc

        if not isinstance(legs, list) or not legs:
            raise InvalidProviderResponseError(
                "routing: route has neither `legs` nor an `encodedPolyline`.",
                provider=PROVIDER_NAME,
            )

        points: list[Coordinate] = []
        for leg in legs:
            for point in _leg_points(leg):
                # Providers emit a duplicate vertex where legs join; drop it
                # so the geometry has no zero-length segments.
                if points and points[-1] == point:
                    continue
                points.append(point)
        return tuple(points)


# -- helpers ----------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _match_confidence(result: Mapping[str, Any]) -> float | None:
    """Extract a genuine 0-1 confidence from a geocoding result.

    **Deliberately not `result["score"]`.** TomTom's published documentation
    describes the top-level `score` as a 0-1 relevance score, but real
    responses disagree: an exact match for "Denver, CO" returns
    ``score: 4.7333083153``. It is an unbounded relevance ranking, useful for
    ordering several results against each other and meaningless as an absolute
    confidence.

    Storing that under a field named ``confidence`` was a latent bug -- any
    later `confidence > 0.8` threshold would pass for *every* result,
    including bad ones. Only the genuine capture exposed it; the synthetic
    fixture had encoded the documented-but-wrong 0-1 assumption.

    ``matchConfidence.score`` is the real 0-1 value, so that is what we
    expose. When it is absent or out of range we report ``None`` rather than
    substituting a number that means something else.
    """
    match_confidence = result.get("matchConfidence")
    if not isinstance(match_confidence, Mapping):
        return None
    value = match_confidence.get("score")
    if not _is_number(value):
        return None
    confidence = float(value)
    return confidence if 0.0 <= confidence <= 1.0 else None


def _rfc3339(moment: datetime) -> str:
    """TomTom's ``departAt`` wants an RFC 3339 timestamp with an offset."""
    return moment.isoformat(timespec="seconds")


def _leg_points(leg: Any) -> list[Coordinate]:
    if not isinstance(leg, Mapping):
        raise InvalidProviderResponseError(
            "routing: leg entry is not an object.", provider=PROVIDER_NAME
        )
    raw_points = leg.get("points")
    if not isinstance(raw_points, list):
        raise InvalidProviderResponseError(
            "routing: leg has no `points` array.", provider=PROVIDER_NAME
        )

    points: list[Coordinate] = []
    for raw in raw_points:
        if not isinstance(raw, Mapping):
            raise InvalidProviderResponseError(
                "routing: geometry point is not an object.", provider=PROVIDER_NAME
            )
        latitude = raw.get("latitude")
        longitude = raw.get("longitude")
        if not _is_number(latitude) or not _is_number(longitude):
            raise InvalidProviderResponseError(
                "routing: geometry point lacks numeric latitude/longitude.",
                provider=PROVIDER_NAME,
            )
        try:
            points.append(
                Coordinate(latitude=float(latitude), longitude=float(longitude))
            )
        except ValueError as exc:
            raise InvalidProviderResponseError(
                f"routing: geometry point is out of range ({exc}).",
                provider=PROVIDER_NAME,
            ) from exc
    return points


def _leg_segment_durations(
    legs: Any, geometry: Sequence[Coordinate], total_seconds: float
) -> tuple[float, ...] | None:
    """Per-geometry-segment durations, when TomTom gives enough to build them.

    A ``calculateRoute`` call with no intermediate waypoints returns a
    **single leg**, whose only timing is the route total. Spreading that total
    across the geometry would just reproduce the domain's own
    distance-proportional fallback while dressing it up as provider data, so
    this returns ``None`` instead and lets the domain apply -- and report --
    its documented fallback honestly.

    With two or more legs the per-leg times are real extra information, so
    each leg's duration is distributed across its own segments by distance.
    """
    if not isinstance(legs, list) or len(legs) < 2:
        return None

    durations: list[float] = []
    for leg in legs:
        summary = leg.get("summary") if isinstance(leg, Mapping) else None
        leg_seconds = (
            float(summary["travelTimeInSeconds"])
            if isinstance(summary, Mapping) and _is_number(summary.get("travelTimeInSeconds"))
            else None
        )
        if leg_seconds is None:
            return None

        points = _leg_points(leg)
        if len(points) < 2:
            continue
        spans = [
            haversine_miles(a, b) for a, b in zip(points, points[1:])
        ]
        span_total = sum(spans)
        if span_total <= 0:
            durations.extend(leg_seconds / len(spans) for _ in spans)
        else:
            durations.extend(leg_seconds * span / span_total for span in spans)

    expected = len(geometry) - 1
    if len(durations) != expected:
        # Leg joins were de-duplicated out of the geometry, so the counts no
        # longer line up. Rather than guess an alignment, fall back.
        return None
    if total_seconds <= 0:  # pragma: no cover - guarded by caller
        return None
    return tuple(durations)


def _shape_key(route: RouteCandidate) -> frozenset[tuple[float, float]]:
    return frozenset(
        (round(p.latitude, SHAPE_PRECISION), round(p.longitude, SHAPE_PRECISION))
        for p in route.geometry
    )


def _deduplicate(
    routes: Sequence[RouteCandidate],
) -> tuple[list[RouteCandidate], int]:
    """Drop routes that are the same road by another name.

    Two routes are merged only when their vertex sets overlap by at least
    :data:`GEOMETRY_OVERLAP_THRESHOLD` *and* their distance and duration agree
    to within :data:`SUMMARY_TOLERANCE`. Requiring both keeps a genuinely
    different alternative that happens to share most of its length -- a
    50-mile detour off a 900-mile interstate run -- from being thrown away.

    The earlier route always wins, so the provider's preferred ordering and
    the resulting ``provider_index`` tie-break stay stable.
    """
    kept: list[RouteCandidate] = []
    shapes: list[frozenset[tuple[float, float]]] = []
    duplicates = 0

    for route in routes:
        shape = _shape_key(route)
        is_duplicate = False
        for existing, existing_shape in zip(kept, shapes):
            smaller = min(len(shape), len(existing_shape))
            if smaller == 0:  # pragma: no cover - geometry always has >= 2 points
                continue
            overlap = len(shape & existing_shape) / smaller
            if overlap < GEOMETRY_OVERLAP_THRESHOLD:
                continue
            if _close(
                route.distance_miles, existing.distance_miles
            ) and _close(route.duration_seconds, existing.duration_seconds):
                is_duplicate = True
                break
        if is_duplicate:
            duplicates += 1
        else:
            kept.append(route)
            shapes.append(shape)

    return kept, duplicates


def _close(left: float, right: float, tolerance: float = SUMMARY_TOLERANCE) -> bool:
    larger = max(abs(left), abs(right))
    if larger == 0:
        return True
    return abs(left - right) / larger <= tolerance
