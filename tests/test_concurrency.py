"""ConcurrencyController: AIMD per epoch, cooldowns, permits, signals.

Single-threaded tests use :class:`fakeserver.FakeClock`, whose attached
``Condition.wait`` advances the clock instead of sleeping. Threaded tests
coordinate with events and joins; nothing here sleeps.
"""

from __future__ import annotations

import dataclasses
import threading
from typing import Any
from unittest.mock import MagicMock

import pytest

from fakeserver import FakeClock, make_response
from weclappy import (
    ConcurrencyController,
    ConcurrencySettings,
    Signal,
    Weclapp,
    WeclappConcurrencyTimeoutError,
    WeclappRateLimitError,
)

BASE = "https://acme.weclapp.com/webapp/api/v2/"


def make(**settings: Any) -> tuple[ConcurrencyController, FakeClock]:
    clock = FakeClock()
    controller = ConcurrencyController(ConcurrencySettings(**settings), clock=clock)
    clock.attach(controller)
    return controller, clock


def run_epoch(controller: ConcurrencyController, *signals: Signal, saturate: bool = True) -> None:
    """Complete one epoch: optionally saturate the window, then observe ``target`` signals."""
    size = controller.snapshot().epoch_size
    held = size if saturate else max(0, size - 1)
    permits = [controller.acquire() for _ in range(held)]
    for permit in permits:
        permit.release()
    padded = list(signals) + [Signal.OK] * (size - len(signals))
    for signal in padded:
        controller.observe(signal)


# ----------------------------------------------------------------- settings
def test_defaults_start_at_two_below_ceiling() -> None:
    controller = ConcurrencyController()
    assert controller.target == 2
    assert controller.ceiling == 10
    assert controller.active == 0


def test_initial_target_is_clamped_to_ceiling() -> None:
    controller, _ = make(max_concurrency=1, initial_concurrency=5)
    assert controller.target == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_concurrency": 0},
        {"initial_concurrency": 0},
        {"concurrency_wait_threshold_ms": 500, "load_wait_threshold_ms": 400},
        {"min_rate_limit_cooldown": -0.1},
    ],
)
def test_settings_validation(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="must"):
        ConcurrencySettings(**kwargs)


def test_settings_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        ConcurrencySettings().max_concurrency = 3  # type: ignore[misc]


# ------------------------------------------------------------------- growth
def test_growth_after_saturated_clean_epoch() -> None:
    controller, _ = make()
    run_epoch(controller)
    assert controller.target == 3
    run_epoch(controller)
    assert controller.target == 4


def test_growth_works_from_target_one() -> None:
    """0.7.0 P0: a target of one could never grow again."""
    controller, _ = make(initial_concurrency=1)
    run_epoch(controller)
    assert controller.target == 2


def test_growth_after_rate_limit_recovers_from_one() -> None:
    controller, clock = make(initial_concurrency=4)
    controller.observe(Signal.RATE_LIMITED)
    assert controller.target == 1
    clock.advance(10)
    # finish the epoch that saw the 429, then grow from one
    while controller.snapshot().epoch_completed:
        controller.observe(Signal.OK)
    run_epoch(controller)
    assert controller.target == 2


def test_no_growth_without_saturation() -> None:
    controller, _ = make()
    run_epoch(controller, saturate=False)
    assert controller.target == 2


def test_no_growth_beyond_ceiling() -> None:
    controller, _ = make(max_concurrency=2)
    run_epoch(controller)
    run_epoch(controller)
    assert controller.target == 2


def test_error_blocks_growth_for_the_epoch() -> None:
    controller, _ = make()
    run_epoch(controller, Signal.ERROR)
    assert controller.target == 2
    run_epoch(controller)
    assert controller.target == 3


# ----------------------------------------------------------------- decrease
def test_concurrency_signal_decrements_by_one() -> None:
    controller, _ = make(initial_concurrency=4)
    controller.observe(Signal.CONCURRENCY)
    assert controller.target == 3


@pytest.mark.parametrize(("initial", "expected"), [(9, 5), (8, 4), (2, 1), (1, 1)])
def test_load_signal_halves_rounding_up(initial: int, expected: int) -> None:
    controller, _ = make(initial_concurrency=initial)
    controller.observe(Signal.LOAD)
    assert controller.target == expected


def test_concurrency_signal_never_drops_below_one() -> None:
    controller, _ = make(initial_concurrency=1)
    controller.observe(Signal.CONCURRENCY)
    assert controller.target == 1


@pytest.mark.parametrize(("signal", "expected"), [(Signal.LOAD, 5), (Signal.CONCURRENCY, 9)])
def test_at_most_one_decrease_per_epoch(signal: Signal, expected: int) -> None:
    controller, _ = make(initial_concurrency=10)
    permits = [controller.acquire() for _ in range(10)]
    for permit in permits:
        permit.release()
    for _ in range(10):  # ten in-flight responses all carry the same signal
        controller.observe(signal)
    assert controller.target == expected
    snapshot = controller.snapshot()
    assert snapshot.epoch_size == expected
    assert snapshot.epoch_completed == 0


def test_next_epoch_may_decrease_again() -> None:
    controller, _ = make(initial_concurrency=10)
    run_epoch(controller, *[Signal.LOAD] * 10)
    assert controller.target == 5
    run_epoch(controller, Signal.LOAD)
    assert controller.target == 3


def test_rate_limit_overrides_an_earlier_decrease_in_the_epoch() -> None:
    controller, _ = make(initial_concurrency=8)
    controller.observe(Signal.LOAD)
    controller.observe(Signal.RATE_LIMITED)
    assert controller.target == 1


# ----------------------------------------------------------------- cooldown
def test_rate_limit_drops_to_one_and_starts_default_cooldown() -> None:
    controller, _ = make(initial_concurrency=6)
    controller.observe(Signal.RATE_LIMITED)
    snapshot = controller.snapshot()
    assert snapshot.target == 1
    assert snapshot.cooldown_remaining == pytest.approx(2.0)


@pytest.mark.parametrize(("cooldown", "expected"), [(None, 2.0), (0.5, 2.0), (7.5, 7.5)])
def test_rate_limit_cooldown_is_at_least_the_minimum(
    cooldown: float | None, expected: float
) -> None:
    controller, _ = make()
    controller.observe(Signal.RATE_LIMITED, cooldown=cooldown)
    assert controller.snapshot().cooldown_remaining == pytest.approx(expected)


@pytest.mark.parametrize("cooldown", [float("inf"), float("nan"), float("-inf")])
def test_non_finite_cooldown_still_applies_the_minimum(cooldown: float) -> None:
    """Regression: an infinite cooldown used to skip the cooldown entirely."""
    controller, _ = make()
    controller.observe(Signal.RATE_LIMITED, cooldown=cooldown)
    assert controller.snapshot().cooldown_remaining == pytest.approx(2.0)


def test_cooldown_never_shrinks() -> None:
    controller, _ = make()
    controller.observe(Signal.RATE_LIMITED, cooldown=10)
    controller.observe(Signal.RATE_LIMITED, cooldown=3)
    assert controller.snapshot().cooldown_remaining == pytest.approx(10)


def test_acquire_waits_out_the_cooldown() -> None:
    controller, clock = make()
    controller.observe(Signal.RATE_LIMITED)
    with controller.acquire():
        assert controller.active == 1
    assert clock.waits == [pytest.approx(2.0)]
    assert controller.snapshot().cooldown_remaining == 0


def test_wait_for_cooldown_for_writes_takes_no_permit() -> None:
    controller, clock = make()
    controller.wait_for_cooldown()
    assert clock.waits == []
    controller.observe(Signal.RATE_LIMITED, cooldown=4)
    controller.wait_for_cooldown()
    assert clock.waits == [pytest.approx(4)]
    assert controller.active == 0


def test_wait_for_cooldown_times_out() -> None:
    controller, clock = make()
    controller.observe(Signal.RATE_LIMITED)
    with pytest.raises(WeclappConcurrencyTimeoutError, match="cooldown"):
        controller.wait_for_cooldown(timeout=0.5)
    assert clock.waits == [pytest.approx(0.5)]


def test_acquire_times_out_when_slots_are_full() -> None:
    controller, clock = make(max_concurrency=1, initial_concurrency=1)
    held = controller.acquire()
    with pytest.raises(WeclappConcurrencyTimeoutError, match="read slot"):
        controller.acquire(timeout=0.25)
    assert clock.waits == [pytest.approx(0.25)]
    held.release()
    assert controller.acquire(timeout=0.25) is not None


def test_acquire_times_out_during_cooldown() -> None:
    controller, _ = make()
    controller.observe(Signal.RATE_LIMITED, cooldown=30)
    with pytest.raises(WeclappConcurrencyTimeoutError, match="cooldown"):
        controller.acquire(timeout=1)


def test_concurrency_timeout_error_is_a_weclapp_error_not_api_error() -> None:
    from weclappy import WeclappAPIError, WeclappError

    assert issubclass(WeclappConcurrencyTimeoutError, WeclappError)
    assert not issubclass(WeclappConcurrencyTimeoutError, WeclappAPIError)


# ------------------------------------------------------------------- permits
def test_permit_double_release_is_safe() -> None:
    controller, _ = make()
    first = controller.acquire()
    controller.acquire()
    first.release()
    first.release()
    assert controller.active == 1


def test_permit_context_manager_releases_on_error() -> None:
    controller, _ = make()

    def use() -> None:
        with controller.acquire():
            assert controller.active == 1
            raise KeyError("boom")

    with pytest.raises(KeyError):
        use()
    assert controller.active == 0


def test_release_wakes_a_blocked_acquirer() -> None:
    controller = ConcurrencyController(ConcurrencySettings(initial_concurrency=1))
    held = controller.acquire()
    acquired = threading.Event()

    def worker() -> None:
        with controller.acquire(timeout=5):
            acquired.set()

    thread = threading.Thread(target=worker)
    thread.start()
    assert not acquired.is_set()
    held.release()
    thread.join(timeout=2)
    assert acquired.is_set()


def test_threads_never_exceed_the_ceiling() -> None:
    controller = ConcurrencyController(ConcurrencySettings(max_concurrency=3))
    peak = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal peak
        for _ in range(50):
            with controller.acquire(timeout=5), lock:
                peak = max(peak, controller.active)
            controller.observe(Signal.OK)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert 1 <= peak <= 3
    assert controller.active == 0
    assert 2 <= controller.target <= 3


# --------------------------------------------------------------------- close
def test_close_wakes_waiters_and_refuses_new_permits() -> None:
    controller = ConcurrencyController(ConcurrencySettings(initial_concurrency=1))
    controller.acquire()
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            controller.acquire(timeout=5)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    controller.close()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    with pytest.raises(RuntimeError, match="closed"):
        controller.acquire()
    with pytest.raises(RuntimeError, match="closed"):
        controller.wait_for_cooldown()


# ------------------------------------------------------------------ snapshot
def test_snapshot_reflects_state() -> None:
    controller, clock = make(max_concurrency=5, initial_concurrency=3)
    permit = controller.acquire()
    controller.observe(Signal.OK)
    controller.observe(Signal.RATE_LIMITED, cooldown=6)
    clock.advance(1)
    snapshot = controller.snapshot()
    assert snapshot.target == 1
    assert snapshot.active == 1
    assert snapshot.ceiling == 5
    assert snapshot.cooldown_remaining == pytest.approx(5)
    assert snapshot.epoch_size == 3
    assert snapshot.epoch_completed == 2
    permit.release()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.target = 9  # type: ignore[misc]


# --------------------------------------------------------------- signal map
_REASON = "X-Weclapp-Wait-Reason"
_WAIT = "X-Weclapp-Wait-Ms"


@pytest.mark.parametrize(
    ("status", "headers", "expected"),
    [
        (200, {}, Signal.OK),
        (404, {}, Signal.OK),
        (429, {}, Signal.RATE_LIMITED),
        (429, {_REASON: "load", _WAIT: "30000"}, Signal.RATE_LIMITED),
        (500, {}, Signal.ERROR),
        (503, {}, Signal.ERROR),
        (503, {_REASON: "concurrency"}, Signal.CONCURRENCY),
        (200, {_REASON: "concurrency"}, Signal.CONCURRENCY),
        (200, {_REASON: "concurrency", _WAIT: "0"}, Signal.CONCURRENCY),
        (200, {_REASON: "load", _WAIT: "300"}, Signal.LOAD),
        (200, {_REASON: "load"}, Signal.LOAD),
        (200, {_REASON: "concurrency, load"}, Signal.LOAD),
        (200, {_REASON: " LOAD "}, Signal.LOAD),
        (200, {_REASON: "concurrency", _WAIT: "5000"}, Signal.LOAD),
        (200, {_WAIT: "249"}, Signal.OK),
        (200, {_WAIT: "250"}, Signal.CONCURRENCY),
        (200, {_WAIT: "1999.9"}, Signal.CONCURRENCY),
        (200, {_WAIT: "2000"}, Signal.LOAD),
        (200, {_WAIT: "abc"}, Signal.OK),
        (200, {_WAIT: "-5000"}, Signal.OK),
        (200, {_WAIT: "nan"}, Signal.OK),
        (200, {_WAIT: "inf"}, Signal.OK),
        (200, {_REASON: ""}, Signal.OK),
        (200, {_REASON: "unknown"}, Signal.OK),
        (200, {_REASON: ",,"}, Signal.OK),
    ],
)
def test_signal_from_response(status: int, headers: dict[str, str], expected: Signal) -> None:
    assert ConcurrencyController.signal_from_response(status, headers) is expected


def test_signal_from_response_uses_given_thresholds() -> None:
    settings = ConcurrencySettings(concurrency_wait_threshold_ms=10, load_wait_threshold_ms=20)
    signal = ConcurrencyController.signal_from_response(200, {_WAIT: "15"}, settings)
    assert signal is Signal.CONCURRENCY
    signal = ConcurrencyController.signal_from_response(200, {_WAIT: "20"}, settings)
    assert signal is Signal.LOAD


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("0", 0.0), ("12.5", 12.5), ("x", None), ("-1", None), ("inf", None)],
)
def test_wait_ms_from_headers(value: str | None, expected: float | None) -> None:
    headers = {} if value is None else {_WAIT: value}
    assert ConcurrencyController.wait_ms_from_headers(headers) == expected


# ------------------------------------------------------- shared controller
def _client(controller: ConcurrencyController) -> Weclapp:
    return Weclapp(BASE, "secret", concurrency=controller, max_concurrency=3)


def test_one_controller_shared_by_two_clients() -> None:
    controller, clock = make(max_concurrency=4)
    first, second = _client(controller), _client(controller)
    assert first.concurrency is controller
    assert second.concurrency is controller
    assert first.concurrency.ceiling == 4  # the injected controller wins over max_concurrency

    first.session.request = MagicMock(return_value=make_response(429, {}))  # type: ignore[method-assign]
    with pytest.raises(WeclappRateLimitError):
        first.post("article", {"name": "x"})
    assert second.concurrency.snapshot().cooldown_remaining >= 2.0

    second.session.request = MagicMock(return_value=make_response(200, {"result": []}))  # type: ignore[method-assign]
    assert second.get("article") == []
    assert clock.waits, "the second client's read waited out the first client's 429 cooldown"


def test_closing_one_client_keeps_a_shared_controller_open() -> None:
    controller = ConcurrencyController()
    first, second = _client(controller), _client(controller)
    first.close()
    with controller.acquire(timeout=1):
        pass
    second.close()


def test_closing_a_client_closes_its_own_controller() -> None:
    client = Weclapp(BASE, "secret")
    client.close()
    with pytest.raises(RuntimeError):
        client.concurrency.acquire(timeout=1)


def test_max_concurrency_sets_the_ceiling_of_an_owned_controller() -> None:
    client = Weclapp(BASE, "secret", max_concurrency=7)
    assert client.concurrency.ceiling == 7
    assert client.concurrency.target == 2
