"""Smoke tests for the Django scaffolding.

Milestone 1 exposes only a health probe; `/api/v1/analyze` arrives in
Milestone 3. These tests exist to prove the project boots, the URL conf
resolves and the settings are coherent -- not to test API behaviour that does
not exist yet.
"""

from __future__ import annotations

from django.test import Client


def test_health_endpoint_responds() -> None:
    response = Client().get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_reports_configured_providers() -> None:
    """Useful for confirming a deployment picked up its configuration."""
    providers = Client().get("/api/v1/health").json()["providers"]
    assert set(providers) >= {"geocoding", "routing", "weather"}


def test_health_never_exposes_a_credential() -> None:
    """It reports key *presence*, never any part of a key's value."""
    from django.test.utils import override_settings

    with override_settings(TOMTOM_API_KEY="super-secret-value-0123456789"):
        response = Client().get("/api/v1/health")

    assert "super-secret-value" not in response.content.decode()
    assert response.json()["providers"]["tomtom_key_configured"] is True


def test_project_has_no_real_database_configured() -> None:
    """Nothing is persisted, so no database backend is wired up on purpose.

    `DATABASES` is declared empty in settings. Django rewrites an empty
    `DATABASES` in place, inserting a `default` entry on the dummy backend the
    first time anything touches `connections` -- which a single request is
    enough to trigger. So the durable assertion is that no *real* engine is
    configured, not that the dict is still literally empty.
    """
    from django.conf import settings

    engines = {config.get("ENGINE") for config in settings.DATABASES.values()}
    assert engines <= {"django.db.backends.dummy"}


def test_no_authentication_or_persistence_apps_are_installed() -> None:
    from django.conf import settings

    installed = set(settings.INSTALLED_APPS)
    assert "django.contrib.auth" not in installed
    assert "django.contrib.sessions" not in installed
    assert "django.contrib.admin" not in installed


def test_system_checks_pass() -> None:
    from io import StringIO

    from django.core.management import call_command

    output = StringIO()
    call_command("check", stdout=output, stderr=output)
    assert "no issues" in output.getvalue().lower()


def test_tests_never_read_a_developer_dotenv() -> None:
    """The suite must behave identically with or without a local `.env`.

    `config.settings.base` skips `load_dotenv` under pytest. Without that,
    a developer with real credentials on disk gets different test results
    from CI -- and the "runs with no credentials" guarantee becomes untrue
    exactly where it is hardest to notice.
    """
    import os

    from django.conf import settings

    assert "PYTEST_VERSION" in os.environ
    # Defaults, not whatever the developer's .env happens to say.
    assert settings.ROUTING_PROVIDER == "fixtures"
    assert settings.GEOCODING_PROVIDER == "fixtures"
