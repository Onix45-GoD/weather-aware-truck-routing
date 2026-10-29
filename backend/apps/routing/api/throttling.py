"""Rate limiting that reads its limits when a request arrives.

DRF's ``SimpleRateThrottle`` copies ``DEFAULT_THROTTLE_RATES`` into a class
attribute at import time, so a limit changed through settings afterwards --
an environment override read late, or a test lowering the rate -- is never
seen. This subclass looks the table up per request instead.
"""

from __future__ import annotations

from rest_framework.settings import api_settings
from rest_framework.throttling import ScopedRateThrottle

__all__ = ["ScopedThrottle"]


class ScopedThrottle(ScopedRateThrottle):
    """``ScopedRateThrottle`` whose rate table is live, not frozen at import."""

    @property  # type: ignore[override]
    def THROTTLE_RATES(self) -> dict[str, str]:  # noqa: N802 - DRF's name
        return api_settings.DEFAULT_THROTTLE_RATES
