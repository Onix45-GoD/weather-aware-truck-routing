"""Architectural guards for the provider layer.

Milestone 1 established that the domain package imports nothing but the
standard library. Adding an I/O layer is exactly the change that would erode
that, so the boundary is re-checked here from the other side, along with the
rule that credentials never escape into logs or exceptions.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import httpx
import pytest
import respx

from apps.routing.providers.errors import ProviderError
from apps.routing.providers.http import ProviderHttpClient, RetryPolicy
from apps.routing.providers.tomtom import (
    TomTomGeocodingProvider,
    TomTomRoutingProvider,
)
from apps.routing.tests.providers.conftest import (
    CHICAGO,
    DENVER,
    DEPARTURE,
    FAKE_KEY,
)

ROUTING_ROOT = Path(__file__).resolve().parents[2]
DOMAIN = ROUTING_ROOT / "domain"
PROVIDERS = ROUTING_ROOT / "providers"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


class TestDomainPurityIsPreserved:
    """The Milestone 1 boundary must survive the arrival of an I/O layer."""

    def test_domain_still_imports_no_framework_or_io_modules(self) -> None:
        forbidden = {
            "django",
            "rest_framework",
            "httpx",
            "respx",
            "requests",
            "urllib",
            "socket",
            "os",
            "random",
            "time",
        }
        offenders = [
            f"{module.name} imports {name}"
            for module in sorted(DOMAIN.glob("*.py"))
            for name in imported_modules(module)
            if name.split(".")[0] in forbidden
        ]
        assert offenders == []

    def test_domain_never_imports_from_providers(self) -> None:
        """Dependencies point inwards only."""
        offenders = [
            f"{module.name} imports {name}"
            for module in sorted(DOMAIN.glob("*.py"))
            for name in imported_modules(module)
            if "providers" in name
        ]
        assert offenders == []

    def test_domain_still_never_reads_the_clock(self) -> None:
        for module in sorted(DOMAIN.glob("*.py")):
            source = module.read_text(encoding="utf-8")
            assert "datetime.now" not in source, module.name
            assert "utcnow" not in source, module.name


class TestProviderLayerBoundaries:
    def test_providers_do_not_import_the_api_or_services_layers(self) -> None:
        offenders = [
            f"{module.name} imports {name}"
            for module in sorted(PROVIDERS.glob("*.py"))
            for name in imported_modules(module)
            if ".api" in name or ".services" in name
        ]
        assert offenders == []

    def test_only_the_factory_depends_on_django_settings(self) -> None:
        """Adapters stay usable outside a Django process.

        `http.py` imports django.core.cache, which is the one deliberate
        exception -- caching is a cross-cutting concern the project already
        owns.
        """
        allowed = {"factory.py", "http.py"}
        offenders = [
            module.name
            for module in sorted(PROVIDERS.glob("*.py"))
            if module.name not in allowed
            and any(name.startswith("django") for name in imported_modules(module))
        ]
        assert offenders == []

    def test_adapters_do_not_reimplement_risk_or_ranking(self) -> None:
        """Business logic belongs to the domain; two copies would drift."""
        forbidden = {
            "apps.routing.domain.risk",
            "apps.routing.domain.ranking",
            "apps.routing.domain.aggregation",
            "apps.routing.domain.checkpoints",
        }
        offenders = [
            f"{module.name} imports {name}"
            for module in sorted(PROVIDERS.glob("*.py"))
            for name in imported_modules(module)
            if name in forbidden
        ]
        assert offenders == []

    def test_no_provider_module_hardcodes_a_credential(self) -> None:
        suspicious = ("api_key =", "apikey =", "API_KEY =", "secret =")
        for module in sorted(PROVIDERS.glob("*.py")):
            source = module.read_text(encoding="utf-8")
            for marker in suspicious:
                index = source.find(marker)
                if index == -1:
                    continue
                remainder = source[index + len(marker) : index + len(marker) + 40]
                assert '"' not in remainder.split("\n")[0], (
                    f"{module.name} may hardcode a credential near {marker!r}"
                )


class TestCredentialsNeverLeak:
    @respx.mock
    def test_no_error_path_exposes_the_key(self, fast_client) -> None:
        """Every failure mode, checked in one sweep."""
        provider = TomTomGeocodingProvider(FAKE_KEY, client=fast_client("tomtom"))

        for response in (
            httpx.Response(401),
            httpx.Response(429),
            httpx.Response(500),
            httpx.Response(400),
            httpx.Response(200, text="not json"),
            httpx.Response(200, json={"results": []}),
        ):
            respx.get(url__startswith="https://api.tomtom.com").mock(
                return_value=response
            )
            with pytest.raises(ProviderError) as exc:
                provider.geocode("Denver")
            assert FAKE_KEY not in str(exc.value)
            assert FAKE_KEY not in repr(exc.value)

    @respx.mock
    def test_retry_log_lines_are_redacted(self, caplog, no_sleep) -> None:
        sleeper, _delays = no_sleep
        respx.get(url__startswith="https://api.tomtom.com").mock(
            return_value=httpx.Response(503)
        )
        provider = TomTomRoutingProvider(
            FAKE_KEY,
            client=ProviderHttpClient(
                provider="tomtom",
                sleep=sleeper,
                retry_policy=RetryPolicy(max_attempts=2, jitter=False),
            ),
        )

        with caplog.at_level(logging.DEBUG):
            with pytest.raises(ProviderError):
                provider.routes(DENVER, CHICAGO, DEPARTURE)

        assert caplog.records, "expected retry warnings to be logged"
        assert FAKE_KEY not in caplog.text
        assert "key=***" in caplog.text

    @respx.mock
    def test_cache_logging_is_redacted(self, caplog) -> None:
        respx.get(url__startswith="https://api.tomtom.com").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "position": {"lat": 39.7, "lon": -104.9},
                            "address": {"freeformAddress": "Denver"},
                        }
                    ]
                },
            )
        )
        provider = TomTomGeocodingProvider(
            FAKE_KEY,
            client=ProviderHttpClient(provider="tomtom", cache_ttl_seconds=600),
        )
        with caplog.at_level(logging.DEBUG):
            provider.geocode("Denver")
            provider.geocode("Denver")  # cache hit, which logs the URL

        assert FAKE_KEY not in caplog.text


SERVICES = ROUTING_ROOT / "services"
API = ROUTING_ROOT / "api"


class TestOrchestrationDoesNotBypassTheDomain:
    """The milestone's central risk: reimplementing a rule one layer up.

    Two copies of a threshold drift, and the copy nobody tests wins in
    production. These fail the build if the service or API layer starts
    deciding anything the domain already decides.
    """

    def test_services_and_api_import_no_http_client(self) -> None:
        offenders = [
            f"{module.name} imports {name}"
            for directory in (SERVICES, API)
            for module in sorted(directory.glob("*.py"))
            for name in imported_modules(module)
            if name.split(".")[0] in {"httpx", "requests", "urllib", "socket"}
        ]
        assert offenders == []

    def test_no_risk_threshold_is_restated_outside_the_domain(self) -> None:
        """The assessment's numbers must appear in exactly one place."""
        thresholds = ("24.999", "34.99", "44.99", "54.99", "0.10", "0.25", "0.50")
        offenders: list[str] = []
        for directory in (SERVICES, API):
            for module in sorted(directory.glob("*.py")):
                source = module.read_text(encoding="utf-8")
                # Strip comments and docstrings would be over-engineering;
                # these literals simply must not appear as code.
                for literal in thresholds:
                    if f"= {literal}" in source or f"> {literal}" in source:
                        offenders.append(f"{module.name} contains {literal}")
        assert offenders == []

    def test_no_layer_above_the_domain_reimplements_ranking(self) -> None:
        banned = ("severe_miles <", "severe_miles >", "sort(key=", "sorted(")
        offenders: list[str] = []
        for module in sorted(SERVICES.glob("*.py")):
            source = module.read_text(encoding="utf-8")
            for marker in banned:
                if marker in source:
                    offenders.append(f"{module.name} contains {marker!r}")
        assert offenders == []

    def test_the_service_calls_the_domain_for_every_decision(self) -> None:
        """Positive check: the real functions are actually wired in."""
        imported = imported_modules(SERVICES / "analysis.py")
        assert "apps.routing.domain.checkpoints" in imported
        assert "apps.routing.domain.aggregation" in imported
        assert "apps.routing.domain.ranking" in imported

    def test_the_api_layer_does_no_orchestration(self) -> None:
        """Views delegate; they never talk to a provider directly."""
        offenders = [
            f"{module.name} imports {name}"
            for module in sorted(API.glob("*.py"))
            for name in imported_modules(module)
            if name.startswith("apps.routing.providers")
            and not name.endswith((".errors", ".factory"))
        ]
        assert offenders == []
