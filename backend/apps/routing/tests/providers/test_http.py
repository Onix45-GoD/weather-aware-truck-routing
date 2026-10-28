"""Contract tests for the shared HTTP transport."""

from __future__ import annotations

import logging

import httpx
import pytest
import respx
from django.core.cache import cache as django_cache

from apps.routing.providers.errors import (
    InvalidProviderResponseError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from apps.routing.providers.http import (
    ProviderHttpClient,
    RedactingFilter,
    RetryPolicy,
    _cache_key,
    _parse_retry_after,
    install_log_redaction,
    redact,
    run_bounded,
)
from apps.routing.tests.providers.conftest import FAKE_KEY

URL = "https://example.test/api"


class TestRedaction:
    @pytest.mark.parametrize(
        "raw",
        [
            "https://api.tomtom.com/x?key=SECRET123&limit=1",
            "https://api.tomtom.com/x?apiKey=SECRET123",
            "https://api.tomtom.com/x?api_key=SECRET123",
            "https://api.tomtom.com/x?token=SECRET123",
            "https://api.tomtom.com/x?access_token=SECRET123",
            "https://tile.openweathermap.org/map/x/1/2/3.png?appid=SECRET123",
        ],
    )
    def test_credential_values_are_masked(self, raw: str) -> None:
        assert "SECRET123" not in redact(raw)
        assert "***" in redact(raw)

    def test_non_secret_parameters_survive(self) -> None:
        assert "limit=1" in redact("https://x.test/y?key=SECRET&limit=1")

    def test_is_case_insensitive(self) -> None:
        assert "SECRET" not in redact("https://x.test/y?KEY=SECRET")


class TestLogRedactionFilter:
    """Protects against credentials leaking through libraries beneath us.

    httpx logs every request at INFO including the full URL, so without this
    the API key would reach any log aggregator the moment INFO is enabled.
    """

    @staticmethod
    def record(msg: str, args: object) -> logging.LogRecord:
        return logging.LogRecord(
            name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
            msg=msg, args=args, exc_info=None,
        )

    def test_redacts_a_string_argument(self) -> None:
        entry = self.record("HTTP Request: %s", (f"https://x.test/y?key={FAKE_KEY}",))
        RedactingFilter().filter(entry)
        assert FAKE_KEY not in entry.getMessage()

    def test_redacts_a_non_string_argument(self) -> None:
        """httpx passes an httpx.URL object, not a str."""
        url = httpx.URL(f"https://x.test/y?key={FAKE_KEY}&limit=1")
        entry = self.record('HTTP Request: %s %s "%s"', ("GET", url, "200 OK"))
        RedactingFilter().filter(entry)
        message = entry.getMessage()
        assert FAKE_KEY not in message
        assert "limit=1" in message

    def test_redacts_the_format_string_itself(self) -> None:
        entry = self.record(f"fetching https://x.test/y?key={FAKE_KEY}", None)
        RedactingFilter().filter(entry)
        assert FAKE_KEY not in entry.getMessage()

    def test_redacts_mapping_arguments(self) -> None:
        """`logger.info("%(url)s", {...})` delivers the mapping inside a tuple,
        which LogRecord then unwraps into `record.args`."""
        entry = self.record("%(url)s", ({"url": f"https://x.test?key={FAKE_KEY}"},))
        assert isinstance(entry.args, dict)  # unwrapped by LogRecord
        RedactingFilter().filter(entry)
        assert FAKE_KEY not in entry.getMessage()

    def test_leaves_innocent_records_untouched(self) -> None:
        entry = self.record("plain message %s", ("no secrets here",))
        RedactingFilter().filter(entry)
        assert entry.getMessage() == "plain message no secrets here"

    def test_always_passes_the_record_through(self) -> None:
        """A redaction filter must never swallow log lines."""
        entry = self.record("anything", None)
        assert RedactingFilter().filter(entry) is True

    def test_installation_is_idempotent(self) -> None:
        logger = logging.getLogger("httpx")
        before = sum(isinstance(f, RedactingFilter) for f in logger.filters)
        install_log_redaction("httpx")
        install_log_redaction("httpx")
        after = sum(isinstance(f, RedactingFilter) for f in logger.filters)
        assert before == after == 1

    def test_the_filter_is_installed_on_import(self) -> None:
        """No opt-in step to forget."""
        assert any(
            isinstance(f, RedactingFilter)
            for f in logging.getLogger("httpx").filters
        )


class TestCacheKey:
    def test_secrets_are_excluded_entirely(self) -> None:
        with_key = _cache_key("p", URL, {"key": FAKE_KEY, "q": "denver"})
        without = _cache_key("p", URL, {"q": "denver"})
        assert with_key == without
        assert FAKE_KEY not in with_key

    def test_differs_by_non_secret_parameters(self) -> None:
        assert _cache_key("p", URL, {"q": "a"}) != _cache_key("p", URL, {"q": "b"})

    def test_differs_by_url(self) -> None:
        assert _cache_key("p", URL, {}) != _cache_key("p", URL + "/other", {})

    def test_differs_by_provider(self) -> None:
        assert _cache_key("a", URL, {}) != _cache_key("b", URL, {})

    def test_is_order_independent(self) -> None:
        assert _cache_key("p", URL, {"a": 1, "b": 2}) == _cache_key(
            "p", URL, {"b": 2, "a": 1}
        )


class TestRetryAfterParsing:
    def test_seconds_form(self) -> None:
        assert _parse_retry_after("30") == 30.0

    def test_http_date_form(self) -> None:
        value = _parse_retry_after("Wed, 21 Oct 2099 07:28:00 GMT")
        assert value is not None and value > 0

    @pytest.mark.parametrize("raw", [None, "", "not-a-date"])
    def test_unparseable_values_return_none(self, raw: str | None) -> None:
        assert _parse_retry_after(raw) is None

    def test_negative_values_clamp_to_zero(self) -> None:
        assert _parse_retry_after("-5") == 0.0


class TestSuccessPath:
    @respx.mock
    def test_returns_decoded_json(self, fast_client) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": True}))
        assert fast_client().get_json(URL, {}) == {"ok": True}

    @respx.mock
    def test_sends_the_given_query_parameters(self, fast_client) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json=[]))
        fast_client().get_json(URL, {"q": "denver", "limit": 1})
        request = route.calls.last.request
        assert request.url.params["q"] == "denver"
        assert request.url.params["limit"] == "1"

    @respx.mock
    def test_invalid_json_raises_typed_error(self, fast_client) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, text="<html>nope"))
        with pytest.raises(InvalidProviderResponseError, match="not valid JSON"):
            fast_client().get_json(URL, {})


class TestPermanentFailures:
    """Never retried: retrying cannot change the answer."""

    @respx.mock
    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_failures_raise_immediately(
        self, fast_client, no_sleep, status: int
    ) -> None:
        _sleeper, delays = no_sleep
        route = respx.get(URL).mock(return_value=httpx.Response(status))
        with pytest.raises(ProviderAuthError):
            fast_client().get_json(URL, {"key": FAKE_KEY})
        assert route.call_count == 1
        assert delays == []

    @respx.mock
    def test_auth_error_never_contains_the_key(self, fast_client) -> None:
        respx.get(URL).mock(return_value=httpx.Response(401))
        with pytest.raises(ProviderAuthError) as exc:
            fast_client().get_json(URL, {"key": FAKE_KEY})
        assert FAKE_KEY not in str(exc.value)

    @respx.mock
    @pytest.mark.parametrize("status", [400, 404, 422])
    def test_client_errors_are_not_retried(
        self, fast_client, no_sleep, status: int
    ) -> None:
        _sleeper, delays = no_sleep
        route = respx.get(URL).mock(return_value=httpx.Response(status))
        with pytest.raises(InvalidProviderResponseError):
            fast_client().get_json(URL, {})
        assert route.call_count == 1
        assert delays == []


class TestTransientFailures:
    @respx.mock
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_server_errors_are_retried_then_raise(
        self, fast_client, no_sleep, status: int
    ) -> None:
        _sleeper, delays = no_sleep
        route = respx.get(URL).mock(return_value=httpx.Response(status))
        with pytest.raises(ProviderUnavailableError, match=str(status)):
            fast_client().get_json(URL, {})
        assert route.call_count == 3
        assert len(delays) == 2  # slept between attempts, not after the last

    @respx.mock
    def test_recovers_when_a_retry_succeeds(self, fast_client) -> None:
        respx.get(URL).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json={"recovered": True}),
            ]
        )
        assert fast_client().get_json(URL, {}) == {"recovered": True}

    @respx.mock
    def test_timeouts_are_retried_then_raise_typed_error(
        self, fast_client, no_sleep
    ) -> None:
        _sleeper, delays = no_sleep
        route = respx.get(URL).mock(side_effect=httpx.ReadTimeout("too slow"))
        with pytest.raises(ProviderTimeoutError):
            fast_client().get_json(URL, {})
        assert route.call_count == 3
        assert len(delays) == 2

    @respx.mock
    def test_connection_errors_are_retried_then_raise(self, fast_client) -> None:
        route = respx.get(URL).mock(side_effect=httpx.ConnectError("no route"))
        with pytest.raises(ProviderUnavailableError):
            fast_client().get_json(URL, {})
        assert route.call_count == 3

    @respx.mock
    def test_retry_count_is_bounded_by_policy(self, no_sleep) -> None:
        sleeper, _delays = no_sleep
        route = respx.get(URL).mock(return_value=httpx.Response(503))
        client = ProviderHttpClient(
            provider="test",
            sleep=sleeper,
            retry_policy=RetryPolicy(max_attempts=5, base_delay_seconds=0, jitter=False),
        )
        with pytest.raises(ProviderUnavailableError):
            client.get_json(URL, {})
        assert route.call_count == 5

    @respx.mock
    def test_a_single_attempt_policy_does_not_retry(self, no_sleep) -> None:
        sleeper, _delays = no_sleep
        route = respx.get(URL).mock(return_value=httpx.Response(503))
        client = ProviderHttpClient(
            provider="test", sleep=sleeper, retry_policy=RetryPolicy(max_attempts=1)
        )
        with pytest.raises(ProviderUnavailableError):
            client.get_json(URL, {})
        assert route.call_count == 1


class TestRateLimiting:
    @respx.mock
    def test_429_is_retried_then_raises_rate_limit_error(
        self, fast_client, no_sleep
    ) -> None:
        _sleeper, delays = no_sleep
        route = respx.get(URL).mock(return_value=httpx.Response(429))
        with pytest.raises(ProviderRateLimitError):
            fast_client().get_json(URL, {})
        assert route.call_count == 3
        assert len(delays) == 2

    @respx.mock
    def test_retry_after_header_drives_the_delay(self, fast_client, no_sleep) -> None:
        _sleeper, delays = no_sleep
        respx.get(URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "2"}),
                httpx.Response(200, json={}),
            ]
        )
        fast_client().get_json(URL, {})
        assert delays == [2.0]

    @respx.mock
    def test_retry_after_is_capped(self, no_sleep) -> None:
        """A provider cannot park a web request for an hour."""
        sleeper, delays = no_sleep
        respx.get(URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "3600"}),
                httpx.Response(200, json={}),
            ]
        )
        client = ProviderHttpClient(
            provider="test",
            sleep=sleeper,
            retry_policy=RetryPolicy(
                max_attempts=2, jitter=False, max_retry_after_seconds=5.0
            ),
        )
        client.get_json(URL, {})
        assert delays == [5.0]

    @respx.mock
    def test_retry_after_is_reported_on_the_exception(self, fast_client) -> None:
        respx.get(URL).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "45"})
        )
        with pytest.raises(ProviderRateLimitError) as exc:
            fast_client().get_json(URL, {})
        assert exc.value.retry_after_seconds == 45.0


class TestCaching:
    @respx.mock
    def test_second_identical_request_is_served_from_cache(self) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={"n": 1}))
        client = ProviderHttpClient(provider="test", cache_ttl_seconds=60)

        assert client.get_json(URL, {"q": "a"}) == {"n": 1}
        assert client.get_json(URL, {"q": "a"}) == {"n": 1}
        assert route.call_count == 1

    @respx.mock
    def test_different_parameters_miss_the_cache(self) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
        client = ProviderHttpClient(provider="test", cache_ttl_seconds=60)
        client.get_json(URL, {"q": "a"})
        client.get_json(URL, {"q": "b"})
        assert route.call_count == 2

    @respx.mock
    def test_zero_ttl_disables_caching(self) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
        client = ProviderHttpClient(provider="test", cache_ttl_seconds=0)
        client.get_json(URL, {"q": "a"})
        client.get_json(URL, {"q": "a"})
        assert route.call_count == 2

    @respx.mock
    def test_per_call_ttl_overrides_the_default(self) -> None:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
        client = ProviderHttpClient(provider="test", cache_ttl_seconds=0)
        client.get_json(URL, {"q": "a"}, cache_ttl_seconds=60)
        client.get_json(URL, {"q": "a"}, cache_ttl_seconds=60)
        assert route.call_count == 1

    @respx.mock
    def test_a_differing_key_still_hits_the_same_cache_entry(self) -> None:
        """Rotating a credential must not invalidate every cached response."""
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={}))
        client = ProviderHttpClient(provider="test", cache_ttl_seconds=60)
        client.get_json(URL, {"key": "first", "q": "a"})
        client.get_json(URL, {"key": "second", "q": "a"})
        assert route.call_count == 1

    @respx.mock
    def test_no_cached_value_contains_a_credential(self) -> None:
        respx.get(URL).mock(return_value=httpx.Response(200, json={"ok": 1}))
        client = ProviderHttpClient(provider="test", cache_ttl_seconds=60)
        client.get_json(URL, {"key": FAKE_KEY, "q": "a"})
        # LocMemCache keys are hashed, so inspect the whole backing store.
        store = getattr(django_cache, "_cache", {})
        assert all(FAKE_KEY not in str(k) for k in store)

    @respx.mock
    def test_failures_are_not_cached(self, no_sleep) -> None:
        sleeper, _delays = no_sleep
        route = respx.get(URL).mock(return_value=httpx.Response(500))
        client = ProviderHttpClient(
            provider="test",
            cache_ttl_seconds=60,
            sleep=sleeper,
            retry_policy=RetryPolicy(max_attempts=1),
        )
        for _ in range(2):
            with pytest.raises(ProviderUnavailableError):
                client.get_json(URL, {"q": "a"})
        assert route.call_count == 2


class TestBackoffPolicy:
    def test_backoff_grows_and_is_capped(self) -> None:
        policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=4.0, jitter=False)
        assert [policy.backoff_for(n) for n in range(5)] == [1.0, 2.0, 4.0, 4.0, 4.0]

    def test_jitter_never_exceeds_the_ceiling(self) -> None:
        policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=4.0, jitter=True)
        assert all(0.0 <= policy.backoff_for(2) <= 4.0 for _ in range(200))

    def test_rejects_a_policy_that_would_never_run(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            RetryPolicy(max_attempts=0)


class TestBoundedConcurrency:
    def test_preserves_input_order(self) -> None:
        tasks = [(lambda n=n: n) for n in range(8)]
        assert run_bounded(tasks, max_workers=3) == list(range(8))

    def test_empty_input(self) -> None:
        assert run_bounded([]) == []

    def test_single_task_runs_inline(self) -> None:
        assert run_bounded([lambda: "only"]) == ["only"]

    def test_exceptions_propagate(self) -> None:
        def boom() -> None:
            raise RuntimeError("task failed")

        with pytest.raises(RuntimeError, match="task failed"):
            run_bounded([lambda: 1, boom])


class TestClientLifecycle:
    def test_context_manager_closes_an_owned_client(self) -> None:
        with ProviderHttpClient(provider="test") as client:
            inner = client.client
        assert inner is not None and inner.is_closed

    def test_an_injected_client_is_not_closed(self) -> None:
        injected = httpx.Client()
        with ProviderHttpClient(provider="test", client=injected):
            pass
        assert not injected.is_closed
        injected.close()


class TestRetryAfterEdgeCases:
    def test_a_date_without_a_timezone_is_read_as_utc(self) -> None:
        """RFC 9110 requires a zone, but headers without one are common."""
        value = _parse_retry_after("Wed, 21 Oct 2099 07:28:00")
        assert value is not None and value > 0

    def test_a_date_already_in_the_past_clamps_to_zero(self) -> None:
        assert _parse_retry_after("Wed, 21 Oct 1999 07:28:00 GMT") == 0.0
