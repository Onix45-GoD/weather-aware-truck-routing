"""Weather risk classification, cargo-weight overrides and risk combination.

Threshold conventions
---------------------
The assessment table mixes explicit operators (``<25``, ``>=55``, ``>1.00``)
with bare ranges (``25-34``, ``0.10-0.25``). Read literally that leaves gaps
(what is 34.6 mph?) and shared endpoints (0.25 in/hr appears in both the
Moderate and High columns). The approved convention closes both:

* Bands are **lower-bound inclusive**, so each listed lower bound belongs to
  its own band and every real value falls in exactly one band. A shared
  interior boundary therefore resolves **upward**, to the more severe band --
  the safety-conservative reading.
* The topmost cut honours the table's literal operator: wind is No Travel at
  ``>= 55`` mph, while rain and snow are No Travel only **strictly above**
  1.00 in/hr and 3.0 in/hr respectively. Rain of exactly 1.00 in/hr is Severe,
  and snow of exactly 3.0 in/hr is Severe.

This reproduces the published table exactly on every value the table states,
and is total over the reals.

Measurements are **never rounded before classification**. Values arrive from
the provider already in assessment units (mph, in/hr), so no conversion
precedes the comparison; rounding happens only when formatting explanations
for display.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from .models import RiskAssessment, RiskLevel, WeatherSample

__all__ = [
    "LOAD_NO_TRAVEL_ABOVE_LB",
    "LOAD_SEVERE_ABOVE_LB",
    "RAIN_NO_TRAVEL_ABOVE_IN_HR",
    "RAIN_THRESHOLDS",
    "SNOW_NO_TRAVEL_ABOVE_IN_HR",
    "SNOW_THRESHOLDS",
    "WIND_THRESHOLDS",
    "apply_load_override",
    "assess_checkpoint",
    "classify_rain",
    "classify_snow",
    "classify_wind",
    "combine_levels",
]

#: Ascending ``(lower_bound, level)`` cuts. A value at or above a bound takes
#: that level; the highest matching bound wins.
WIND_THRESHOLDS: tuple[tuple[float, RiskLevel], ...] = (
    (25.0, RiskLevel.MODERATE),
    (35.0, RiskLevel.HIGH),
    (45.0, RiskLevel.SEVERE),
    (55.0, RiskLevel.NO_TRAVEL),
)

RAIN_THRESHOLDS: tuple[tuple[float, RiskLevel], ...] = (
    (0.10, RiskLevel.MODERATE),
    (0.25, RiskLevel.HIGH),
    (0.50, RiskLevel.SEVERE),
)
#: Rain is No Travel only *strictly above* this value (table reads ">1.00").
RAIN_NO_TRAVEL_ABOVE_IN_HR = 1.00

SNOW_THRESHOLDS: tuple[tuple[float, RiskLevel], ...] = (
    (0.5, RiskLevel.MODERATE),
    (1.0, RiskLevel.HIGH),
    (2.0, RiskLevel.SEVERE),
)
#: Snow is No Travel only *strictly above* this value (table reads ">3.0").
SNOW_NO_TRAVEL_ABOVE_IN_HR = 3.0

# --- Cargo-weight override bands (wind only) -------------------------------
WIND_NO_TRAVEL_MPH = 55.0
WIND_SEVERE_BAND_FLOOR_MPH = 45.0
WIND_HIGH_BAND_FLOOR_MPH = 35.0
#: 45-54 mph with a load strictly above this becomes No Travel.
LOAD_NO_TRAVEL_ABOVE_LB = 30_000.0
#: 35-44 mph with a load strictly above this becomes Severe.
LOAD_SEVERE_ABOVE_LB = 40_000.0


def _classify(
    value: float | None,
    thresholds: Sequence[tuple[float, RiskLevel]],
    label: str,
    no_travel_above: float | None = None,
) -> RiskLevel:
    """Classify one measurement against ascending lower-bound cuts."""
    if value is None:
        return RiskLevel.UNKNOWN
    if value != value:  # NaN: provider returned a non-value
        return RiskLevel.UNKNOWN
    if value < 0.0:
        raise ValueError(label + " cannot be negative: " + repr(value))

    level = RiskLevel.LOW
    for lower_bound, candidate in thresholds:
        if value >= lower_bound:
            level = candidate

    if no_travel_above is not None and value > no_travel_above:
        level = RiskLevel.NO_TRAVEL

    return level


def classify_wind(wind_mph: float | None) -> RiskLevel:
    """Classify sustained wind speed in mph.

    Per the approved assumptions this uses sustained wind, not gusts. The
    25/35/45/55 ladder matches the National Weather Service sustained-wind
    advisory scale; gusts are carried through to the UI for driver awareness
    but never affect classification.
    """
    return _classify(wind_mph, WIND_THRESHOLDS, "wind speed")


def classify_rain(rain_in_hr: float | None) -> RiskLevel:
    """Classify liquid precipitation rate in inches per hour."""
    return _classify(
        rain_in_hr,
        RAIN_THRESHOLDS,
        "rain rate",
        no_travel_above=RAIN_NO_TRAVEL_ABOVE_IN_HR,
    )


def classify_snow(snow_in_hr: float | None) -> RiskLevel:
    """Classify snowfall rate in inches of snow depth per hour."""
    return _classify(
        snow_in_hr,
        SNOW_THRESHOLDS,
        "snow rate",
        no_travel_above=SNOW_NO_TRAVEL_ABOVE_IN_HR,
    )


def combine_levels(levels: Iterable[RiskLevel]) -> RiskLevel:
    """Most severe of the given levels, ignoring ``UNKNOWN``.

    Returns ``UNKNOWN`` only when nothing known was supplied. ``UNKNOWN`` is
    never allowed to read as ``LOW``.
    """
    worst = RiskLevel.UNKNOWN
    worst_score = -1
    for level in levels:
        score = level.score
        if score is not None and score > worst_score:
            worst = level
            worst_score = score
    return worst


def apply_load_override(
    wind_mph: float | None,
    base_level: RiskLevel,
    load_weight_lb: float,
) -> tuple[RiskLevel, bool, str | None]:
    """Apply the cargo-weight rules to a wind classification.

    The assessment's load rules, with the strict ``>`` comparisons exactly as
    written:

    * ``>= 55 mph`` -> No Travel for any load (already the base classification;
      restated here so the rule set is complete and auditable in one place).
    * ``45-54 mph`` with load ``> 30,000 lb`` -> No Travel.
    * ``35-44 mph`` with load ``> 40,000 lb`` -> Severe.

    Overrides only ever escalate -- the result is the more severe of the base
    level and the override -- so a rule can never make a route look safer.

    Returns ``(level, escalated, reason)`` where ``reason`` is a
    presentation-ready explanation, present only when a load-dependent rule
    matched.
    """
    if load_weight_lb < 0:
        raise ValueError("load weight cannot be negative: " + repr(load_weight_lb))
    if wind_mph is None or not base_level.is_known:
        return base_level, False, None

    override: RiskLevel | None = None
    reason: str | None = None

    if wind_mph >= WIND_NO_TRAVEL_MPH:
        # Unconditional on load; the base table already says No Travel.
        override = RiskLevel.NO_TRAVEL
    elif (
        wind_mph >= WIND_SEVERE_BAND_FLOOR_MPH
        and load_weight_lb > LOAD_NO_TRAVEL_ABOVE_LB
    ):
        override = RiskLevel.NO_TRAVEL
        reason = (
            "wind "
            + _format_wind(wind_mph)
            + " in the 45-54 mph band with load "
            + _format_pounds(load_weight_lb)
            + " (> 30,000 lb) -> No Travel"
        )
    elif (
        wind_mph >= WIND_HIGH_BAND_FLOOR_MPH
        and load_weight_lb > LOAD_SEVERE_ABOVE_LB
    ):
        override = RiskLevel.SEVERE
        reason = (
            "wind "
            + _format_wind(wind_mph)
            + " in the 35-44 mph band with load "
            + _format_pounds(load_weight_lb)
            + " (> 40,000 lb) -> Severe"
        )

    if override is None:
        return base_level, False, None

    final = combine_levels((base_level, override))
    escalated = final is not base_level
    return final, escalated, (reason if escalated else None)


def assess_checkpoint(
    sample: WeatherSample | None,
    load_weight_lb: float,
) -> RiskAssessment:
    """Classify one checkpoint's weather into a single risk level.

    Wind, rain and snow are classified independently; the cargo-weight override
    is applied to wind; the checkpoint level is then the **maximum severity**
    across the three. Conditions are not compounded additively -- the
    assessment specifies no compounding rule, and inventing one would make
    results uncalibrated and unexplainable.

    When every condition is missing the checkpoint is ``UNKNOWN``. When only
    some are missing, the known conditions still decide the level and
    ``partial_data`` is set so the gap is visible rather than silent.
    """
    wind_value = sample.wind_mph if sample else None
    rain_value = sample.rain_in_hr if sample else None
    snow_value = sample.snow_in_hr if sample else None

    wind_base = classify_wind(wind_value)
    rain_level = classify_rain(rain_value)
    snow_level = classify_snow(snow_value)

    wind_level, escalated, override_reason = apply_load_override(
        wind_value, wind_base, load_weight_lb
    )

    base_level = combine_levels((wind_base, rain_level, snow_level))
    components: tuple[tuple[str, RiskLevel], ...] = (
        ("wind", wind_level),
        ("rain", rain_level),
        ("snow", snow_level),
    )
    level = combine_levels(level for _, level in components)

    driver: str | None = None
    if level.is_known:
        # `level` is by construction one of the component levels, so this is
        # never empty. First match wins, giving a deterministic
        # wind > rain > snow priority when two conditions tie at the same
        # severity.
        matches = [name for name, component in components if component is level]
        driver = matches[0]

    partial_data = level.is_known and any(
        not component.is_known for _, component in components
    )

    return RiskAssessment(
        level=level,
        driver=driver,
        base_level=base_level,
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        load_override_applied=escalated,
        partial_data=partial_data,
        explanation=_build_explanation(
            wind_value,
            rain_value,
            snow_value,
            wind_level,
            rain_level,
            snow_level,
            level,
            driver,
            override_reason,
        ),
    )


# --- Presentation helpers ---------------------------------------------------
# Formatting happens here and only here. Classification above always uses the
# raw measurement.


def _format_wind(value: float) -> str:
    return "{0:.1f} mph".format(value)


def _format_rate(value: float) -> str:
    return "{0:.2f} in/hr".format(value)


def _format_pounds(value: float) -> str:
    return "{0:,.0f} lb".format(value)


def _title(level: RiskLevel) -> str:
    return level.value.replace("_", " ").title()


def _build_explanation(
    wind_value: float | None,
    rain_value: float | None,
    snow_value: float | None,
    wind_level: RiskLevel,
    rain_level: RiskLevel,
    snow_level: RiskLevel,
    level: RiskLevel,
    driver: str | None,
    override_reason: str | None,
) -> str:
    """Build a human-readable justification for one checkpoint assessment."""
    parts = [
        _describe("Wind", wind_value, wind_level, _format_wind),
        _describe("Rain", rain_value, rain_level, _format_rate),
        _describe("Snow", snow_value, snow_level, _format_rate),
    ]
    text = "; ".join(parts) + "."

    if override_reason:
        text += " Load override: " + override_reason + "."

    if level.is_known and driver:
        text += " Overall " + _title(level) + " (driven by " + driver + ")."
    else:
        text += " Overall Unknown: no forecast available at this checkpoint."

    return text


def _describe(
    name: str,
    value: float | None,
    level: RiskLevel,
    formatter: Callable[[float], str],
) -> str:
    if value is None or value != value:
        return name + " unavailable (Unknown)"
    return name + " " + formatter(value) + " (" + _title(level) + ")"
