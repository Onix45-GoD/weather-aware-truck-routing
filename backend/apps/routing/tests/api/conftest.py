"""API test setup.

Every test in this package runs fully offline: the providers are forced to
the deterministic fixture implementations, so no test can reach the network
even by accident.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache as django_cache


@pytest.fixture(autouse=True)
def offline_providers(settings):
    """Force fixture providers for the whole package.

    The project default for weather is Open-Meteo, which is a real network
    call. Without this, the API tests would silently depend on an external
    service being up -- and would be slow, flaky and quietly non-offline.
    """
    settings.GEOCODING_PROVIDER = "fixtures"
    settings.ROUTING_PROVIDER = "fixtures"
    settings.WEATHER_PROVIDER = "fixtures"


@pytest.fixture(autouse=True)
def clear_provider_cache():
    django_cache.clear()
    yield
    django_cache.clear()


@pytest.fixture
def valid_payload() -> dict:
    return {
        "origin": "Denver",
        "destination": "Chicago",
        "departure_at": "2026-11-02T12:00:00Z",
        "load_weight_lb": 42000,
        "checkpoint_interval_miles": 50,
    }
