"""Adaptive concurrency control for weclapp reads.

weclapp enforces a tenant-wide limit of concurrently active requests. Excess
requests are queued (currently for up to about 30 seconds) and then rejected
with HTTP 429. Each response reports how long it waited in that queue
(``X-Weclapp-Wait-Ms``) and why (``X-Weclapp-Wait-Reason`` is ``concurrency``,
``load`` or both). The documented client strategy is to throttle proactively
as soon as wait times rise, instead of waiting for 429s.

:class:`ConcurrencyController` implements that as additive-increase,
multiplicative-decrease (AIMD) **per epoch**:

* An *epoch* is one window of ``target`` completed responses.
* ``concurrency`` feedback (or a wait above the concurrency threshold)
  lowers the target by one, ``load`` feedback (or a wait above the load
  threshold) halves it, and 429 drops it to one and starts a shared cooldown.
  At most one decrease is applied per epoch, so a burst of in-flight
  responses that all carry the same signal cannot cascade the target to one.
* The target grows by one after a full, clean epoch in which the window was
  actually saturated. Growth therefore happens only when the extra slot would
  be used, and it works at every target, including one.

The controller is thread-safe. It is per client by default; pass the same
instance to several clients that talk to the same tenant so they share one
budget.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Self

from .errors import WeclappConcurrencyTimeoutError

__all__ = [
    "ConcurrencyController",
    "ConcurrencySettings",
    "ConcurrencySnapshot",
    "Permit",
    "Signal",
]

_LOAD_REASON = "load"
_CONCURRENCY_REASON = "concurrency"


class Signal(StrEnum):
    """Feedback derived from one response, fed into :meth:`ConcurrencyController.observe`."""

    OK = "ok"
    """Prompt 2xx/4xx answer without a throttling hint: counts toward growth."""
    CONCURRENCY = "concurrency"
    """weclapp queued the request because too many were active: target minus one."""
    LOAD = "load"
    """weclapp queued the request because overall load was high: target halved."""
    RATE_LIMITED = "rate_limited"
    """HTTP 429: target drops to the floor and a shared cooldown starts."""
    ERROR = "error"
    """5xx or transport failure: neutral, but blocks growth for this epoch."""


@dataclass(frozen=True, slots=True)
class ConcurrencySettings:
    """Tunable parameters of :class:`ConcurrencyController`.

    Attributes:
        max_concurrency: Hard ceiling for concurrently active reads.
        initial_concurrency: Target when the controller starts.
        concurrency_wait_threshold_ms: A reported wait at or above this value
            is treated like a ``concurrency`` reason.
        load_wait_threshold_ms: A reported wait at or above this value is
            treated like a ``load`` reason.
        min_rate_limit_cooldown: Minimum shared cooldown after a 429, in seconds.
    """

    max_concurrency: int = 10
    initial_concurrency: int = 2
    concurrency_wait_threshold_ms: float = 250.0
    load_wait_threshold_ms: float = 2000.0
    min_rate_limit_cooldown: float = 2.0

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if self.initial_concurrency < 1:
            raise ValueError("initial_concurrency must be at least 1")
        if self.load_wait_threshold_ms < self.concurrency_wait_threshold_ms:
            raise ValueError("load_wait_threshold_ms must not be below concurrency threshold")
        if self.min_rate_limit_cooldown < 0:
            raise ValueError("min_rate_limit_cooldown must be non-negative")


@dataclass(frozen=True, slots=True)
class ConcurrencySnapshot:
    """Point-in-time view of the controller state."""

    target: int
    active: int
    ceiling: int
    cooldown_remaining: float
    epoch_size: int
    epoch_completed: int


class Permit:
    """A held read slot; release it by leaving the ``with`` block."""

    __slots__ = ("_controller", "_released")

    def __init__(self, controller: ConcurrencyController) -> None:
        self._controller = controller
        self._released = False

    def release(self) -> None:
        """Return the slot. Safe to call more than once."""
        if not self._released:
            self._released = True
            self._controller._release()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


class ConcurrencyController:
    """Thread-safe AIMD controller for concurrent weclapp reads.

    Args:
        settings: Tunables; see :class:`ConcurrencySettings`.
        clock: Monotonic time source, injectable for tests.
    """

    def __init__(
        self,
        settings: ConcurrencySettings | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or ConcurrencySettings()
        self._clock = clock
        self._condition = threading.Condition()
        self._target = min(self.settings.initial_concurrency, self.settings.max_concurrency)
        self._active = 0
        self._cooldown_until = 0.0
        self._closed = False
        self._start_epoch_unlocked()

    # ----------------------------------------------------------------- public
    @property
    def ceiling(self) -> int:
        """Hard upper bound for the target."""
        return self.settings.max_concurrency

    @property
    def target(self) -> int:
        """Current number of reads the controller allows in flight."""
        with self._condition:
            return self._target

    @property
    def active(self) -> int:
        """Reads currently holding a permit."""
        with self._condition:
            return self._active

    def snapshot(self) -> ConcurrencySnapshot:
        """Return an immutable copy of the state."""
        with self._condition:
            return ConcurrencySnapshot(
                target=self._target,
                active=self._active,
                ceiling=self.ceiling,
                cooldown_remaining=max(0.0, self._cooldown_until - self._clock()),
                epoch_size=self._epoch_size,
                epoch_completed=self._epoch_completed,
            )

    def acquire(self, timeout: float | None = None) -> Permit:
        """Block until a read slot is free and no cooldown is active.

        Raises:
            WeclappConcurrencyTimeoutError: when ``timeout`` elapses first.
            RuntimeError: when the controller was closed.
        """
        deadline = None if timeout is None else self._clock() + timeout
        with self._condition:
            while True:
                self._raise_if_closed()
                remaining_cooldown = self._cooldown_until - self._clock()
                if remaining_cooldown > 0:
                    self._wait_unlocked(remaining_cooldown, deadline, "cooldown")
                    continue
                if self._active < self._target:
                    self._active += 1
                    if self._active >= self._target:
                        self._epoch_saturated = True
                    return Permit(self)
                self._wait_unlocked(None, deadline, "read slot")

    def wait_for_cooldown(self, timeout: float | None = None) -> None:
        """Block while a rate-limit cooldown is active (used for writes).

        Writes never take a read slot and are never retried by the library,
        but sending them into a queue that just answered 429 only produces
        more 429s. Waiting out the shared cooldown is the polite option.
        """
        deadline = None if timeout is None else self._clock() + timeout
        with self._condition:
            while True:
                self._raise_if_closed()
                remaining = self._cooldown_until - self._clock()
                if remaining <= 0:
                    return
                self._wait_unlocked(remaining, deadline, "cooldown")

    def observe(self, signal: Signal, *, cooldown: float | None = None) -> None:
        """Apply feedback from one completed attempt.

        Args:
            signal: What the response told us; see :class:`Signal`.
            cooldown: Seconds of shared cooldown to start for
                :attr:`Signal.RATE_LIMITED`. The configured minimum applies
                when this is lower or omitted.
        """
        with self._condition:
            match signal:
                case Signal.RATE_LIMITED:
                    self._target = 1
                    requested = (
                        cooldown if cooldown is not None and math.isfinite(cooldown) else 0.0
                    )
                    delay = max(self.settings.min_rate_limit_cooldown, requested)
                    self._cooldown_until = max(self._cooldown_until, self._clock() + delay)
                    self._epoch_decreased = True
                case Signal.LOAD:
                    self._decrease_unlocked(max(1, math.ceil(self._target / 2)))
                case Signal.CONCURRENCY:
                    self._decrease_unlocked(max(1, self._target - 1))
                case Signal.ERROR:
                    self._epoch_blocked = True
                case Signal.OK:
                    pass
            self._epoch_completed += 1
            if self._epoch_completed >= self._epoch_size:
                if (
                    self._epoch_saturated
                    and not self._epoch_decreased
                    and not self._epoch_blocked
                    and self._target < self.ceiling
                ):
                    self._target += 1
                self._start_epoch_unlocked()
            self._condition.notify_all()

    def close(self) -> None:
        """Wake every waiter and refuse further permits."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    @classmethod
    def signal_from_response(
        cls,
        status_code: int,
        headers: Mapping[str, str],
        settings: ConcurrencySettings | None = None,
    ) -> Signal:
        """Translate an HTTP response into a :class:`Signal`.

        The explicit ``X-Weclapp-Wait-Reason`` wins over wait-time
        thresholds; both can appear on successful and on 429 responses.
        """
        settings = settings or ConcurrencySettings()
        if status_code == 429:
            return Signal.RATE_LIMITED
        reasons = {
            item.strip().lower()
            for item in str(headers.get("X-Weclapp-Wait-Reason", "")).split(",")
            if item.strip()
        }
        wait_ms = cls.wait_ms_from_headers(headers)
        if _LOAD_REASON in reasons or (
            wait_ms is not None and wait_ms >= settings.load_wait_threshold_ms
        ):
            return Signal.LOAD
        if _CONCURRENCY_REASON in reasons or (
            wait_ms is not None and wait_ms >= settings.concurrency_wait_threshold_ms
        ):
            return Signal.CONCURRENCY
        if status_code >= 500:
            return Signal.ERROR
        return Signal.OK

    @staticmethod
    def wait_ms_from_headers(headers: Mapping[str, str]) -> float | None:
        """Parse ``X-Weclapp-Wait-Ms``; invalid or negative values yield ``None``."""
        value = headers.get("X-Weclapp-Wait-Ms")
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) and parsed >= 0 else None

    # --------------------------------------------------------------- internals
    def _release(self) -> None:
        with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    def _decrease_unlocked(self, new_target: int) -> None:
        if self._epoch_decreased:
            return
        self._epoch_decreased = True
        self._target = min(self._target, new_target)

    def _start_epoch_unlocked(self) -> None:
        self._epoch_size = self._target
        self._epoch_completed = 0
        self._epoch_decreased = False
        self._epoch_blocked = False
        self._epoch_saturated = self._active >= self._target

    def _raise_if_closed(self) -> None:
        if self._closed:
            raise RuntimeError("weclapp concurrency controller is closed")

    def _wait_unlocked(self, wanted: float | None, deadline: float | None, what: str) -> None:
        """Wait on the condition, bounded by ``wanted`` seconds and ``deadline``."""
        timeout = wanted
        if deadline is not None:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise WeclappConcurrencyTimeoutError(
                    f"timed out waiting for weclapp {what}; "
                    f"target={self._target} active={self._active}"
                )
            timeout = remaining if timeout is None else min(timeout, remaining)
        self._condition.wait(timeout)
