"""Value objects shared by the domain core.

Every type here is a frozen, slotted dataclass or an enum. Domain functions
transform these values and never mutate them, which keeps the whole pipeline
referentially transparent and trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum

__all__ = [
    "AssessedCheckpoint",
    "Checkpoint",
    "CheckpointInterval",
    "Coordinate",
    "RISK_LEVEL_ORDER",
    "RiskAssessment",
    "RiskLevel",
    "RouteCandidate",
    "RouteMetrics",
    "WeatherSample",
]


class RiskLevel(Enum):
    """Weather risk classification for a single condition or checkpoint.

    ``UNKNOWN`` is deliberately *not* ordered alongside the other members. It
    means "we have no forecast here", which is categorically different from
    "conditions are fine". Treating it as ``LOW`` would make a provider outage
    look like good weather -- the most dangerous failure mode in this
    application -- so ``UNKNOWN`` carries no severity score and is excluded
    from severity comparisons and from the distance-weighted average risk.
    """

    UNKNOWN = "UNKNOWN"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"
    NO_TRAVEL = "NO_TRAVEL"

    @property
    def is_known(self) -> bool:
        """True for every member except :attr:`UNKNOWN`."""
        return self is not RiskLevel.UNKNOWN

    @property
    def score(self) -> int | None:
        """Ordinal severity 0..4, or ``None`` for :attr:`UNKNOWN`.

        This is the per-mile value used by the distance-weighted average risk.
        """
        return _RISK_SCORES.get(self)


_RISK_SCORES: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MODERATE: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.SEVERE: 3,
    RiskLevel.NO_TRAVEL: 4,
}

#: Severity order, used for display and for deterministic iteration.
RISK_LEVEL_ORDER: tuple[RiskLevel, ...] = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.HIGH,
    RiskLevel.SEVERE,
    RiskLevel.NO_TRAVEL,
    RiskLevel.UNKNOWN,
)


class CheckpointInterval(IntEnum):
    """Checkpoint spacings offered by the assessment."""

    TEN = 10
    TWENTY_FIVE = 25
    FIFTY = 50


@dataclass(frozen=True, slots=True)
class Coordinate:
    """A WGS84 point in decimal degrees."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90.0 <= self.latitude <= 90.0:
            raise ValueError("latitude out of range: " + repr(self.latitude))
        if not -180.0 <= self.longitude <= 180.0:
            raise ValueError("longitude out of range: " + repr(self.longitude))


@dataclass(frozen=True, slots=True)
class WeatherSample:
    """Hourly forecast at one point and time, in assessment units.

    Units are requested from the weather provider directly in imperial form
    (mph, inches per hour) so the domain never performs a unit conversion. Unit
    math immediately before a threshold comparison is a classic source of
    off-by-a-category bugs, and this removes the opportunity entirely.

    A ``None`` field means the provider returned no value for that variable;
    it classifies as :attr:`RiskLevel.UNKNOWN`, never as ``LOW``.

    ``wind_gust_mph`` is carried for presentation only. Per the approved
    assumptions, classification uses sustained wind exclusively.
    """

    wind_mph: float | None
    rain_in_hr: float | None
    snow_in_hr: float | None
    wind_gust_mph: float | None = None
    forecast_time: datetime | None = None


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Outcome of classifying one checkpoint, with its full justification.

    The per-condition levels are retained alongside the combined ``level`` so
    the UI -- and, later, the AI rationale feature -- can explain *why* a
    checkpoint scored the way it did without re-deriving anything.
    """

    level: RiskLevel
    driver: str | None
    base_level: RiskLevel
    wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel
    load_override_applied: bool
    partial_data: bool
    explanation: str


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """A sampling point at a known cumulative distance along a route."""

    index: int
    coordinate: Coordinate
    distance_from_origin_miles: float
    eta: datetime
    is_origin: bool = False
    is_destination: bool = False


@dataclass(frozen=True, slots=True)
class AssessedCheckpoint:
    """A checkpoint joined to its forecast, its risk and the miles it governs.

    ``segment_miles`` is the forward-attributed distance this checkpoint owns:
    the stretch from this checkpoint up to the next one. See
    :mod:`apps.routing.domain.aggregation` for the convention and its rationale.
    """

    checkpoint: Checkpoint
    weather: WeatherSample | None
    risk: RiskAssessment
    segment_miles: float


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    """One route alternative returned by a routing provider.

    ``segment_durations`` holds travel time in seconds for each geometry
    segment, so it has exactly ``len(geometry) - 1`` entries when present. When
    a provider supplies it, checkpoint ETAs follow the real time profile of the
    road. When it is ``None``, ETAs fall back to distance-proportional
    interpolation across ``duration_seconds``.

    ``provider_index`` preserves the provider's original ordering and serves as
    the final tie-break that makes ranking a total order.
    """

    id: str
    label: str
    geometry: tuple[Coordinate, ...]
    distance_miles: float
    duration_seconds: float
    provider_index: int = 0
    segment_durations: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if len(self.geometry) < 2:
            raise ValueError("route geometry needs at least two coordinates")
        if self.distance_miles <= 0:
            raise ValueError("route distance must be positive")
        if self.duration_seconds <= 0:
            raise ValueError("route duration must be positive")
        if self.segment_durations is not None:
            expected = len(self.geometry) - 1
            if len(self.segment_durations) != expected:
                raise ValueError(
                    "segment_durations must have "
                    + str(expected)
                    + " entries, got "
                    + str(len(self.segment_durations))
                )
            if any(d < 0 for d in self.segment_durations):
                raise ValueError("segment durations must be non-negative")


@dataclass(frozen=True, slots=True)
class RouteMetrics:
    """Aggregated, distance-weighted risk profile for one route."""

    route_id: str
    distance_miles: float
    duration_seconds: float
    low_miles: float
    moderate_miles: float
    high_miles: float
    severe_miles: float
    no_travel_miles: float
    unknown_miles: float
    average_risk: float | None
    max_risk: RiskLevel
    coverage_pct: float
    no_travel_checkpoints: int = 0

    @property
    def blocked(self) -> bool:
        """True when this route encounters any No Travel condition.

        Normally that means ``no_travel_miles > 0``. The checkpoint count is
        also consulted so a No Travel condition at the **destination** still
        blocks the route: the destination owns zero forward miles under the
        attribution convention, so a mileage-only test would silently miss a
        driver arriving into a 60 mph windstorm.

        This is a statement of fact about the weather. What it *means* for the
        recommendation is policy, and lives in
        :mod:`apps.routing.domain.ranking`.
        """
        return self.no_travel_miles > 0.0 or self.no_travel_checkpoints > 0

    @property
    def known_miles(self) -> float:
        """Miles that have a usable forecast behind them."""
        return (
            self.low_miles
            + self.moderate_miles
            + self.high_miles
            + self.severe_miles
            + self.no_travel_miles
        )

    @property
    def miles_by_level(self) -> dict[RiskLevel, float]:
        """Risk-mile breakdown keyed by level, for presentation."""
        return {
            RiskLevel.LOW: self.low_miles,
            RiskLevel.MODERATE: self.moderate_miles,
            RiskLevel.HIGH: self.high_miles,
            RiskLevel.SEVERE: self.severe_miles,
            RiskLevel.NO_TRAVEL: self.no_travel_miles,
            RiskLevel.UNKNOWN: self.unknown_miles,
        }
