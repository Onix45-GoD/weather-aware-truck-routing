"""Unit conversions the domain owns.

One exact constant, one direction. The routing provider wants kilograms;
the assessment speaks in pounds. Keeping the conversion here -- pure,
tested at the boundaries -- means no adapter ever does arithmetic on a
weight before handing it to a provider.
"""

from __future__ import annotations

from typing import Final

__all__ = ["KG_PER_LB", "pounds_to_kilograms"]

#: International avoirdupois pound, exact by definition (1959).
KG_PER_LB: Final = 0.45359237


def pounds_to_kilograms(pounds: float) -> float:
    """Exact-factor conversion. Rounding is the caller's decision."""
    if pounds < 0:
        raise ValueError("weight cannot be negative")
    return pounds * KG_PER_LB
