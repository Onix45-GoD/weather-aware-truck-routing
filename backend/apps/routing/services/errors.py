"""Errors raised by the orchestration layer itself.

Distinct from :mod:`apps.routing.providers.errors`, which covers failures
*outside* our process. These represent a request that reached us intact but
cannot produce a trustworthy answer -- usually a user-input problem, which is
why they map to 4xx rather than 502.
"""

from __future__ import annotations

__all__ = [
    "AmbiguousLocationError",
    "AnalysisError",
]


class AnalysisError(Exception):
    """Base class for orchestration failures."""

    code = "ANALYSIS_FAILED"

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.message = message
        #: Request field responsible, when one is. Lets the API return a
        #: field-level error the form can attach to the right input.
        self.field = field
        super().__init__(message)


class AmbiguousLocationError(AnalysisError):
    """A location resolved, but not confidently enough to route from.

    Routing from the wrong "Springfield" would produce a complete, plausible
    and entirely wrong analysis -- worse than an error, because nothing
    downstream would look suspicious. When the provider reports a confidence
    below the configured floor we stop and say so.

    See ``docs/decisions.md`` D29 for the policy and why a *missing*
    confidence is treated differently from a *low* one.
    """

    code = "LOCATION_AMBIGUOUS"

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        query: str = "",
        confidence: float | None = None,
    ) -> None:
        self.query = query
        self.confidence = confidence
        super().__init__(message, field=field)
