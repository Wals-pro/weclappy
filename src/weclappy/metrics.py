"""Per-request metrics and client-wide statistics.

weclapp bills API load as *request seconds* (the sum of server-side
processing time) and reports queueing through ``X-Weclapp-Wait-Ms`` and
``X-Weclapp-Wait-Reason``. :class:`RequestMetrics` captures these values for
every physical attempt and is handed to the client's ``on_response`` hook;
:class:`ClientStats` aggregates them for the lifetime of a client.

Neither type ever contains the API key, query parameters or response bodies.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

__all__ = ["ClientStats", "RequestMetrics", "StatsSnapshot"]


@dataclass(frozen=True, slots=True)
class RequestMetrics:
    """Observations for one physical HTTP attempt.

    Attributes:
        method: HTTP method, upper-cased.
        path: URL path without query string.
        status_code: HTTP status, or ``None`` when no response arrived.
        duration_ms: Wall-clock time of the attempt in milliseconds.
        wait_ms: Queue wait reported by weclapp, if the request waited.
        wait_reason: ``concurrency``, ``load`` or ``concurrency, load``.
        correlation_id: Request/correlation id header, if present.
        attempt: 1-based attempt counter within one logical request.
        will_retry: Whether the client scheduled another attempt.
        retry_delay: Seconds the client will sleep before the next attempt.
        concurrency_target: The controller's target after this attempt.
        error: Exception class name for transport failures, else ``None``.
    """

    method: str
    path: str
    status_code: int | None
    duration_ms: float
    wait_ms: float | None
    wait_reason: str | None
    correlation_id: str | None
    attempt: int
    will_retry: bool
    retry_delay: float
    concurrency_target: int
    error: str | None = None

    @property
    def processing_ms(self) -> float | None:
        """Server processing estimate: duration minus reported queue wait."""
        if self.wait_ms is None:
            return None
        return max(0.0, self.duration_ms - self.wait_ms)


@dataclass(frozen=True, slots=True)
class StatsSnapshot:
    """Immutable view of :class:`ClientStats`."""

    requests: int
    retries: int
    rate_limited: int
    transport_errors: int
    http_errors: int
    slow_requests: int
    duration_seconds: float
    """Sum of client-side attempt durations (including queue wait)."""
    request_seconds: float
    """Sum of estimated server processing time: duration minus reported queue wait.

    This approximates the *request seconds* weclapp uses to measure tenant load."""
    wait_seconds: float
    max_wait_ms: float
    by_status: dict[int, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Plain-dict form for logging or JSON serialisation."""
        return {
            "requests": self.requests,
            "retries": self.retries,
            "rate_limited": self.rate_limited,
            "transport_errors": self.transport_errors,
            "http_errors": self.http_errors,
            "slow_requests": self.slow_requests,
            "duration_seconds": round(self.duration_seconds, 3),
            "request_seconds": round(self.request_seconds, 3),
            "wait_seconds": round(self.wait_seconds, 3),
            "max_wait_ms": self.max_wait_ms,
            "by_status": dict(sorted(self.by_status.items())),
        }


class ClientStats:
    """Thread-safe aggregate of :class:`RequestMetrics` for one client."""

    __slots__ = (
        "_by_status",
        "_duration_seconds",
        "_http_errors",
        "_lock",
        "_max_wait_ms",
        "_rate_limited",
        "_request_seconds",
        "_requests",
        "_retries",
        "_slow_requests",
        "_slow_threshold_ms",
        "_transport_errors",
        "_wait_seconds",
    )

    def __init__(self, slow_threshold_ms: float) -> None:
        self._lock = threading.Lock()
        self._slow_threshold_ms = slow_threshold_ms
        self._reset_unlocked()

    def _reset_unlocked(self) -> None:
        self._requests = 0
        self._retries = 0
        self._rate_limited = 0
        self._transport_errors = 0
        self._http_errors = 0
        self._slow_requests = 0
        self._duration_seconds = 0.0
        self._request_seconds = 0.0
        self._wait_seconds = 0.0
        self._max_wait_ms = 0.0
        self._by_status: dict[int, int] = {}

    def record(self, metrics: RequestMetrics) -> None:
        """Fold one attempt into the aggregate."""
        with self._lock:
            self._requests += 1
            self._duration_seconds += metrics.duration_ms / 1000.0
            processing_ms = metrics.processing_ms
            self._request_seconds += (
                processing_ms if processing_ms is not None else metrics.duration_ms
            ) / 1000.0
            if metrics.will_retry:
                self._retries += 1
            if metrics.wait_ms is not None:
                self._wait_seconds += metrics.wait_ms / 1000.0
                self._max_wait_ms = max(self._max_wait_ms, metrics.wait_ms)
            if metrics.duration_ms >= self._slow_threshold_ms:
                self._slow_requests += 1
            if metrics.status_code is None:
                self._transport_errors += 1
            else:
                self._by_status[metrics.status_code] = (
                    self._by_status.get(metrics.status_code, 0) + 1
                )
                if metrics.status_code == 429:
                    self._rate_limited += 1
                if metrics.status_code >= 400:
                    self._http_errors += 1

    def snapshot(self) -> StatsSnapshot:
        """Return an immutable copy of the current counters."""
        with self._lock:
            return StatsSnapshot(
                requests=self._requests,
                retries=self._retries,
                rate_limited=self._rate_limited,
                transport_errors=self._transport_errors,
                http_errors=self._http_errors,
                slow_requests=self._slow_requests,
                duration_seconds=self._duration_seconds,
                request_seconds=self._request_seconds,
                wait_seconds=self._wait_seconds,
                max_wait_ms=self._max_wait_ms,
                by_status=dict(self._by_status),
            )

    def reset(self) -> None:
        """Zero every counter."""
        with self._lock:
            self._reset_unlocked()
