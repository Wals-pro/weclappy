"""Retry policy: what weclappy repeats, how often, and how long it waits.

The rules follow weclapp's load-management guidance and the retry boundaries
established in production use:

* **Reads** (``GET``, ``HEAD``, ``OPTIONS`` and the read-only ``POST``
  query endpoints) are retried on transport failures, on 5xx, on 429 with a
  separate and much slower budget, and once on the transient weclapp problem
  types ``request_timeout`` (400) and ``persistence`` (409).
* **Writes** are retried **only** when the request provably never left the
  client (DNS failure, connection refused, connect timeout). A write whose
  outcome is unknown (read timeout, connection dropped after sending, 5xx,
  429) is never repeated; the caller is told via
  :class:`~weclappy.errors.WeclappTransportError.outcome_unknown` or the
  typed HTTP error and decides after reading the entity back.
* ``Retry-After`` is honoured when present but capped, because weclapp does
  not document it and intermediaries may send absurd values.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import requests
from urllib3.exceptions import (
    ConnectTimeoutError,
    MaxRetryError,
    NameResolutionError,
    NewConnectionError,
)

from .errors import TRANSIENT_STATUS_CODES, problem_type_suffix

if TYPE_CHECKING:
    from requests import Response

__all__ = [
    "RetryDecision",
    "RetryKind",
    "RetryPolicy",
    "RetryState",
    "TransportOutcome",
    "classify_transport_error",
    "retry_after_seconds",
]


class RetryKind(StrEnum):
    """Which budget a retry is charged to."""

    TRANSIENT = "transient"
    """5xx responses and transport failures (shared budget)."""
    RATE_LIMIT = "rate_limit"
    """HTTP 429 (own, slower budget)."""
    PROBLEM = "problem"
    """weclapp ``request_timeout`` / ``persistence`` problem types."""


class TransportOutcome(StrEnum):
    """Whether a failed transport attempt may have reached the server."""

    NOT_SENT = "not_sent"
    """The connection was never established; the request cannot have been processed."""
    UNKNOWN = "unknown"
    """The request may have been processed; a response never arrived."""
    NOT_RETRYABLE = "not_retryable"
    """Configuration-class failure such as TLS; retrying cannot help."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Immutable retry configuration.

    Attributes:
        max_retries: Retries for 5xx and transport failures on reads, and for
            provably unsent writes.
        backoff_factor: Base of the exponential backoff for those retries
            (``factor * 2**attempt`` plus jitter).
        rate_limit_retries: Retries after 429 on reads.
        rate_limit_backoff: Base delay after the first 429 (doubles per attempt).
        problem_retries: Extra retries for transient weclapp problem types.
        max_backoff: Upper bound for every computed delay, including
            ``Retry-After``.
        jitter: Add uniform random jitter of up to one base unit.
    """

    max_retries: int = 3
    backoff_factor: float = 0.3
    rate_limit_retries: int = 5
    rate_limit_backoff: float = 2.0
    problem_retries: int = 1
    max_backoff: float = 60.0
    jitter: bool = True

    def __post_init__(self) -> None:
        for name in ("max_retries", "rate_limit_retries", "problem_retries"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        for name in ("backoff_factor", "rate_limit_backoff", "max_backoff"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")

    def budget(self, kind: RetryKind) -> int:
        """Retry budget for ``kind``."""
        match kind:
            case RetryKind.TRANSIENT:
                return self.max_retries
            case RetryKind.RATE_LIMIT:
                return self.rate_limit_retries
            case RetryKind.PROBLEM:
                return self.problem_retries

    def delay(self, kind: RetryKind, attempt: int) -> float:
        """Backoff before retry number ``attempt`` (0-based) of ``kind``."""
        base = self.rate_limit_backoff if kind is RetryKind.RATE_LIMIT else self.backoff_factor
        delay = base * (2.0**attempt)
        if self.jitter and base:
            delay += random.uniform(0, base)
        return min(delay, self.max_backoff)

    def cap(self, seconds: float | None) -> float | None:
        """Clamp an externally supplied delay (``Retry-After``) to ``max_backoff``."""
        if seconds is None or not math.isfinite(seconds):
            return None
        return min(max(0.0, seconds), self.max_backoff)


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """Result of classifying one failed attempt."""

    retry: bool
    delay: float = 0.0
    kind: RetryKind | None = None
    reason: str = ""


_NO_RETRY: Final = RetryDecision(retry=False)


@dataclass(slots=True)
class RetryState:
    """Mutable per-request counters, one per logical request."""

    attempts: dict[RetryKind, int] = field(default_factory=dict)

    def used(self, kind: RetryKind) -> int:
        return self.attempts.get(kind, 0)

    def charge(self, kind: RetryKind) -> int:
        """Consume one retry of ``kind`` and return the 0-based attempt index."""
        attempt = self.used(kind)
        self.attempts[kind] = attempt + 1
        return attempt

    @property
    def total(self) -> int:
        return sum(self.attempts.values())


def retry_after_seconds(response: Response) -> float | None:
    """Parse ``Retry-After`` (delta-seconds or HTTP-date); ``None`` if absent/invalid."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = None
    if seconds is not None:
        return max(0.0, seconds) if math.isfinite(seconds) else None
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0.0, retry_at.timestamp() - time.time())


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield ``exc``, its ``args`` that are exceptions, causes and contexts."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for arg in current.args:
            if isinstance(arg, BaseException):
                stack.append(arg)
        reason = getattr(current, "reason", None)
        if isinstance(reason, BaseException):
            stack.append(reason)
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                stack.append(linked)


def classify_transport_error(exc: requests.RequestException) -> TransportOutcome:
    """Decide whether a failed attempt can have reached weclapp.

    Only failures that happen *before* a connection carries request bytes
    are :attr:`TransportOutcome.NOT_SENT`: name resolution, connection
    refused/unreachable and connect timeouts. Everything after that point,
    including a dropped connection and read timeouts, is
    :attr:`TransportOutcome.UNKNOWN` because the server may have processed
    the request.
    """
    if isinstance(exc, requests.exceptions.SSLError):
        return TransportOutcome.NOT_RETRYABLE
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return TransportOutcome.NOT_SENT
    if isinstance(exc, requests.exceptions.ReadTimeout | requests.exceptions.ChunkedEncodingError):
        return TransportOutcome.UNKNOWN
    if isinstance(exc, requests.exceptions.ConnectionError):
        for linked in _exception_chain(exc):
            if isinstance(linked, NameResolutionError | NewConnectionError | ConnectTimeoutError):
                return TransportOutcome.NOT_SENT
            if isinstance(linked, MaxRetryError):
                continue
        return TransportOutcome.UNKNOWN
    return TransportOutcome.UNKNOWN


def decide_for_exception(
    policy: RetryPolicy,
    state: RetryState,
    exc: requests.RequestException,
    *,
    is_read: bool,
) -> RetryDecision:
    """Retry decision for a transport failure."""
    outcome = classify_transport_error(exc)
    if outcome is TransportOutcome.NOT_RETRYABLE:
        return _NO_RETRY
    if outcome is TransportOutcome.UNKNOWN and not is_read:
        return _NO_RETRY
    if state.used(RetryKind.TRANSIENT) >= policy.budget(RetryKind.TRANSIENT):
        return _NO_RETRY
    attempt = state.charge(RetryKind.TRANSIENT)
    return RetryDecision(
        retry=True,
        delay=policy.delay(RetryKind.TRANSIENT, attempt),
        kind=RetryKind.TRANSIENT,
        reason=f"{type(exc).__name__} ({outcome.value})",
    )


def decide_for_response(
    policy: RetryPolicy,
    state: RetryState,
    response: Response,
    *,
    is_read: bool,
) -> RetryDecision:
    """Retry decision for an HTTP response that is not a success."""
    status = response.status_code
    if not is_read:
        return _NO_RETRY
    if status == 429:
        kind = RetryKind.RATE_LIMIT
        if state.used(kind) >= policy.budget(kind):
            return _NO_RETRY
        attempt = state.charge(kind)
        delay = policy.cap(retry_after_seconds(response))
        if delay is None:
            delay = policy.delay(kind, attempt)
        return RetryDecision(retry=True, delay=delay, kind=kind, reason="429")
    if status in TRANSIENT_STATUS_CODES:
        kind = RetryKind.TRANSIENT
        if state.used(kind) >= policy.budget(kind):
            return _NO_RETRY
        attempt = state.charge(kind)
        delay = policy.cap(retry_after_seconds(response))
        if delay is None:
            delay = policy.delay(kind, attempt)
        return RetryDecision(retry=True, delay=delay, kind=kind, reason=str(status))
    suffix = _problem_suffix(response)
    if (status == 400 and suffix == "request_timeout") or (
        status == 409 and suffix == "persistence"
    ):
        kind = RetryKind.PROBLEM
        if state.used(kind) >= policy.budget(kind):
            return _NO_RETRY
        attempt = state.charge(kind)
        return RetryDecision(
            retry=True,
            delay=policy.delay(RetryKind.TRANSIENT, attempt),
            kind=kind,
            reason=f"{status}/{suffix}",
        )
    return _NO_RETRY


def rate_limit_cooldown(policy: RetryPolicy, response: Response, state: RetryState) -> float:
    """Shared cooldown to start after a 429, whether or not this request retries."""
    capped = policy.cap(retry_after_seconds(response))
    if capped is not None:
        return capped
    return policy.delay(RetryKind.RATE_LIMIT, state.used(RetryKind.RATE_LIMIT))


def _problem_suffix(response: Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return problem_type_suffix(payload.get("type"))
