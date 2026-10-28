"""Tests for provider selection from settings."""

from __future__ import annotations

import pytest
from django.test import override_settings

from apps.routing.providers.errors import ProviderConfigurationError
from apps.routing.providers.factory import (
    get_geocoding_provider,
    get_routing_provider,
    get_weather_provider,
    provider_status,
)
from apps.routing.providers.fixtures import (
    FixtureGeocodingProvider,
    FixtureRoutingProvider,
    FixtureWeatherProvider,
)
from apps.routing.providers.openmeteo import OpenMeteoWeatherProvider
from apps.routing.providers.tomtom import (
    TomTomGeocodingProvider,
    TomTomRoutingProvider,
)
from apps.routing.tests.providers.conftest import FAKE_KEY


class TestDefaults:
    def test_everything_defaults_to_running_without_credentials(self) -> None:
        """The project must be runnable and testable with no keys at all."""
        assert isinstance(get_geocoding_provider(), FixtureGeocodingProvider)
        assert isinstance(get_routing_provider(), FixtureRoutingProvider)
        assert isinstance(get_weather_provider(), OpenMeteoWeatherProvider)


class TestSelection:
    @override_settings(GEOCODING_PROVIDER="tomtom", TOMTOM_API_KEY=FAKE_KEY)
    def test_selects_tomtom_geocoding(self) -> None:
        assert isinstance(get_geocoding_provider(), TomTomGeocodingProvider)

    @override_settings(ROUTING_PROVIDER="tomtom", TOMTOM_API_KEY=FAKE_KEY)
    def test_selects_tomtom_routing(self) -> None:
        assert isinstance(get_routing_provider(), TomTomRoutingProvider)

    @override_settings(WEATHER_PROVIDER="fixtures")
    def test_selects_fixture_weather(self) -> None:
        assert isinstance(get_weather_provider(), FixtureWeatherProvider)

    @pytest.mark.parametrize("name", ["open-meteo", "openmeteo", "OPEN-METEO"])
    def test_weather_provider_name_is_case_and_spelling_tolerant(self, name) -> None:
        assert isinstance(get_weather_provider(name), OpenMeteoWeatherProvider)

    def test_an_explicit_name_overrides_settings(self) -> None:
        assert isinstance(get_weather_provider("fixtures"), FixtureWeatherProvider)


class TestMisconfiguration:
    @override_settings(GEOCODING_PROVIDER="tomtom", TOMTOM_API_KEY="")
    def test_selecting_tomtom_without_a_key_fails_loudly(self) -> None:
        with pytest.raises(ProviderConfigurationError, match="TOMTOM_API_KEY"):
            get_geocoding_provider()

    @override_settings(ROUTING_PROVIDER="tomtom", TOMTOM_API_KEY="   ")
    def test_a_whitespace_key_counts_as_missing(self) -> None:
        with pytest.raises(ProviderConfigurationError):
            get_routing_provider()

    @pytest.mark.parametrize(
        "getter", [get_geocoding_provider, get_routing_provider, get_weather_provider]
    )
    def test_unknown_provider_names_are_rejected(self, getter) -> None:
        with pytest.raises(ProviderConfigurationError, match="Unknown"):
            getter("magic-8-ball")


class TestProviderStatus:
    @override_settings(TOMTOM_API_KEY="")
    def test_reports_a_missing_key_as_absent(self) -> None:
        assert provider_status()["tomtom_key_configured"] is False

    @override_settings(TOMTOM_API_KEY=FAKE_KEY)
    def test_reports_a_present_key_without_revealing_it(self) -> None:
        """Safe to expose on a health endpoint and safe to log."""
        status = provider_status()
        assert status["tomtom_key_configured"] is True
        assert FAKE_KEY not in str(status)
        assert all(FAKE_KEY not in str(value) for value in status.values())

    def test_reports_the_selected_providers(self) -> None:
        status = provider_status()
        assert set(status) >= {"geocoding", "routing", "weather"}

    def test_records_that_open_meteo_needs_no_key(self) -> None:
        assert provider_status()["open_meteo_requires_key"] is False
