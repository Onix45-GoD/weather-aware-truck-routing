"""Shared helpers for provider contract tests.

No test in this package touches the network. Every HTTP interaction is mocked
with ``respx``, and every payload comes from ``tests/fixtures`` -- whose
provenance (genuine capture vs. synthetic) is documented in
``tests/fixtures/PROVENANCE.md``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache as django_cache

from apps.routing.domain.models import Coordinate
from apps.routing.providers.http import ProviderHttpClient, RetryPolicy

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures"

DENVER = Coordinate(latitude=39.7392, longitude=-104.9903)
CHICAGO = Coordinate(latitude=41.8781, longitude=-87.6298)
DEPARTURE = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)

#: A key-shaped string used only to prove it never escapes into a log, an
#: exception, a cache key or a repr. It is not a credential.
FAKE_KEY = "test-key-NEVER-REAL-0123456789"


def load_fixture(provider: str, name: str) -> Any:
    """Read a fixture payload by provider directory and filename."""
    path = FIXTURE_ROOT / provider / name
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def clear_cache():
    """Isolate every test from cached provider responses.

    Without this, a test asserting a cache *miss* would pass or fail depending
    on which tests ran before it.
    """
    django_cache.clear()
    yield
    django_cache.clear()


@pytest.fixture
def no_sleep():
    """Collect retry delays instead of waiting them out.

    Keeps the retry tests instant while still letting them assert that backoff
    actually happened and how many times.
    """
    delays: list[float] = []
    return delays.append, delays


@pytest.fixture
def fast_client(no_sleep):
    """A client whose retries are immediate and whose cache is off."""
    sleeper, _delays = no_sleep

    def build(provider: str = "test", **kwargs: Any) -> ProviderHttpClient:
        kwargs.setdefault(
            "retry_policy", RetryPolicy(max_attempts=3, base_delay_seconds=0.01, jitter=False)
        )
        kwargs.setdefault("cache_ttl_seconds", 0)
        return ProviderHttpClient(provider=provider, sleep=sleeper, **kwargs)

    return build
