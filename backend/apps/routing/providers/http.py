"""Shared HTTP transport for provider adapters.

One place for the concerns every adapter would otherwise reimplement: explicit
timeouts, a bounded retry policy, response caching, and -- most importantly --
making sure an API key never reaches a log line, an exception message or a
cache key.

**Why synchronous.** The project runs under WSGI with ordinary synchronous DRF
views. An async client would force either an ASGI migration or
``async_to_sync`` bridging, and would buy very little: the Open-Meteo adapter
collapses every checkpoint into one or two bulk calls, so a full analysis is
roughly four outbound requests. Where genuine parallelism helps -- the two
independent geocode calls -- :func:`run_bounded` provides it with a small
thread pool. That is a far smaller change than making the whole stack async,
and it keeps ``respx`` mocking and stack traces simple.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime
from typing import Any, TypeVar

import httpx
from django.core.cache import cache as django_cache

from .errors import (
    InvalidProviderResponseError,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

__all__ = [
    "DEFAULT_RETRY_POLICY",
    "DEFAULT_TIMEOUT",
    "ProviderHttpClient",
    "RetryPolicy",
    "redact",
    "run_bounded",
]

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: Query parameters whose values must never be logged, cached or echoed back.
SECRET_PARAM_NAMES = frozenset({"key", "apikey", "api_key", "token", "access_token"})

_SECRET_QUERY_RE = re.compile(
    r"(?i)\b(" + "|".join(sorted(SECRET_PARAM_NAMES)) + r")=[^&\s]*"
)

#: Separate connect and read budgets. A slow DNS or TCP handshake is a
#: different failure from a provider that accepted the connection and then
#: thought about it for a minute.
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)

#: Status codes worth trying again. Everything else is a permanent answer:
#: retrying a 400 or a 401 only burns quota and delays the error.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def redact(text: str) -> str:
    """Strip credential values out of a URL or message.

    Applied to everything that could reach a log, an exception or a cache key.
    """
    return _SECRET_QUERY_RE.sub(lambda m: f"{m.group(1)}=***", text)


class RedactingFilter(logging.Filter):
    """Scrubs credential values from log records before they are emitted.

    Our own log calls redact their arguments already. This exists for the
    libraries underneath us: httpx logs every request at INFO as
    ``HTTP Request: GET https://...?key=SECRET "HTTP/1.1 200 OK"``, which
    would publish the API key to any log aggregator the moment INFO logging
    is switched on.

    The URL arrives in ``record.args``, not in the format string, so both are
    scrubbed. Arguments are not necessarily strings either -- httpx passes an
    ``httpx.URL`` object -- so each argument is rendered before being checked,
    and replaced with its redacted text only when it actually contains a
    credential.
    """

    @staticmethod
    def _scrub(value: object) -> object:
        if isinstance(value, str):
            return redact(value) if "=" in value else value
        # Non-string arguments (httpx.URL, yarl, ...) still format into the
        # message, so render and inspect them too.
        try:
            rendered = str(value)
        except Exception:  # pragma: no cover - defensive
            return value
        if "=" not in rendered:
            return value
        scrubbed = redact(rendered)
        return scrubbed if scrubbed != rendered else value

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and "=" in record.msg:
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: self._scrub(value) for key, value in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(self._scrub(value) for value in record.args)
        return True


def install_log_redaction(*logger_names: str) -> None:
    """Attach :class:`RedactingFilter` to the loggers that handle our URLs.

    Idempotent, and called on import of this module so the protection is
    active for anything that can make a provider request -- there is no
    opt-in step to forget.
    """
    for name in logger_names or ("httpx", "httpcore", __name__):
        target = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in target.filters):
            target.addFilter(RedactingFilter())


install_log_redaction()


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """A bounded retry policy. It always terminates."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 4.0
    jitter: bool = True
    #: Cap on how long we will honour a provider's ``Retry-After``. Without
    #: this, a provider could park a web request for an hour.
    max_retry_after_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    def backoff_for(self, attempt: int) -> float:
        """Exponential backoff for a zero-based attempt number."""
        delay = min(self.max_delay_seconds, self.base_delay_seconds * (2**attempt))
        if self.jitter:
            # Full jitter: spreads a thundering herd without ever exceeding
            # the computed ceiling.
            delay *= random.random()
        return delay


DEFAULT_RETRY_POLICY = RetryPolicy()


def run_bounded(
    tasks: Sequence[Callable[[], T]], *, max_workers: int = 4
) -> list[T]:
    """Run independent callables concurrently, preserving input order.

    Used for genuinely parallel work such as geocoding an origin and a
    destination. Exceptions propagate from the first failing task.
    """
    if not tasks:
        return []
    if len(tasks) == 1:
        return [tasks[0]()]

    with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as pool:
        futures = [pool.submit(task) for task in tasks]
        return [future.result() for future in futures]


def _cache_key(provider: str, url: str, params: Mapping[str, Any]) -> str:
    """Stable cache key that cannot contain a credential.

    Secret parameters are dropped entirely rather than hashed, so a key can
    never be recovered from cache storage even in principle.
    """
    safe = {
        name: value
        for name, value in sorted(params.items())
        if name.lower() not in SECRET_PARAM_NAMES
    }
    payload = json.dumps([url, safe], sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"provider:{provider}:{digest}"


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header in either documented form."""
    if not value:
        return None
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:  # pragma: no cover - parsedate_to_datetime raises instead
        return None
    if when.tzinfo is None:
        # RFC 9110 requires an explicit zone, but a header without one is
        # common enough to handle; UTC is the only safe reading.
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


@dataclass
class ProviderHttpClient:
    """A thin, retrying, caching JSON client scoped to one provider."""

    provider: str
    base_url: str = ""
    # httpx.Timeout is mutable, so it needs a factory rather than a shared
    # default instance.
    timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY
    cache_ttl_seconds: int = 0
    client: httpx.Client | None = None
    sleep: Callable[[float], None] = time.sleep
    _owns_client: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers={"Accept": "application/json"},
            )
            self._owns_client = True

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    def __enter__(self) -> ProviderHttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_json(
        self,
        url: str,
        params: Mapping[str, Any],
        *,
        cache_ttl_seconds: int | None = None,
    ) -> Any:
        """GET a JSON document, with caching and bounded retries.

        Raises a typed :class:`~apps.routing.providers.errors.ProviderError`
        subclass for every failure mode; no bare httpx exception escapes.
        """
        full_url = url if url.startswith("http") else f"{self.base_url}{url}"
        ttl = self.cache_ttl_seconds if cache_ttl_seconds is None else cache_ttl_seconds

        key = _cache_key(self.provider, full_url, params) if ttl > 0 else None
        if key is not None:
            cached = django_cache.get(key)
            if cached is not None:
                logger.debug("provider cache hit: %s", redact(full_url))
                return cached

        payload = self._request_with_retries(full_url, params)

        if key is not None:
            django_cache.set(key, payload, ttl)
        return payload

    def _request_with_retries(self, url: str, params: Mapping[str, Any]) -> Any:
        assert self.client is not None  # set in __post_init__
        safe_url = redact(url)
        last_error: Exception | None = None

        for attempt in range(self.retry_policy.max_attempts):
            is_last = attempt == self.retry_policy.max_attempts - 1
            try:
                response = self.client.get(url, params=dict(params))
            except httpx.TimeoutException as exc:
                last_error = exc
                if is_last:
                    raise ProviderTimeoutError(
                        f"{self.provider} did not respond within the timeout "
                        f"({self.timeout.read}s read).",
                        provider=self.provider,
                    ) from exc
                self._wait(self.retry_policy.backoff_for(attempt), safe_url, "timeout")
                continue
            except httpx.HTTPError as exc:
                last_error = exc
                if is_last:
                    raise ProviderUnavailableError(
                        f"Could not reach {self.provider}: {type(exc).__name__}.",
                        provider=self.provider,
                    ) from exc
                self._wait(
                    self.retry_policy.backoff_for(attempt), safe_url, "transport error"
                )
                continue

            status = response.status_code

            if status in (401, 403):
                # Permanent: never retried, and the key is never echoed.
                raise ProviderAuthError(
                    f"{self.provider} rejected our credentials (HTTP {status}). "
                    "Check the configured API key.",
                    provider=self.provider,
                )

            if status == 429:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                if is_last:
                    raise ProviderRateLimitError(
                        f"{self.provider} rate limit reached (HTTP 429).",
                        provider=self.provider,
                        retry_after_seconds=retry_after,
                    )
                delay = self.retry_policy.backoff_for(attempt)
                if retry_after is not None:
                    delay = min(retry_after, self.retry_policy.max_retry_after_seconds)
                self._wait(delay, safe_url, "rate limited")
                continue

            if status in RETRYABLE_STATUS:
                if is_last:
                    raise ProviderUnavailableError(
                        f"{self.provider} returned HTTP {status}.",
                        provider=self.provider,
                    )
                self._wait(
                    self.retry_policy.backoff_for(attempt), safe_url, f"HTTP {status}"
                )
                continue

            if status >= 400:
                # 4xx other than auth/rate-limit is our mistake: a bad
                # parameter or an unroutable request. Retrying cannot help.
                raise InvalidProviderResponseError(
                    f"{self.provider} rejected the request (HTTP {status}).",
                    provider=self.provider,
                )

            try:
                return response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise InvalidProviderResponseError(
                    f"{self.provider} returned a body that is not valid JSON.",
                    provider=self.provider,
                ) from exc

        # Unreachable: every branch above either returns or raises on the
        # final attempt.
        raise ProviderUnavailableError(  # pragma: no cover - defensive
            f"{self.provider} request failed after "
            f"{self.retry_policy.max_attempts} attempts.",
            provider=self.provider,
        ) from last_error

    def _wait(self, delay: float, safe_url: str, reason: str) -> None:
        logger.warning(
            "provider %s retrying after %s: %s (sleeping %.2fs)",
            self.provider,
            reason,
            safe_url,
            delay,
        )
        if delay > 0:
            self.sleep(delay)
