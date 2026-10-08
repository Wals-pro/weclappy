"""RequestMetrics and ClientStats aggregation."""

from __future__ import annotations

import dataclasses
import threading
from typing import Any

import pytest

from weclappy import ClientStats, RequestMetrics, StatsSnapshot


def metrics(**overrides: Any) -> RequestMetrics:
    values: dict[str, Any] = {
        "method": "GET",
        "path": "/webapp/api/v2/article",
        "status_code": 200,
        "duration_ms": 100.0,
        "wait_ms": None,
        "wait_reason": None,
        "correlation_id": None,
        "attempt": 1,
        "will_retry": False,
        "retry_delay": 0.0,
        "concurrency_target": 2,
    }
    values.update(overrides)
    return RequestMetrics(**values)


@pytest.mark.parametrize(
    ("duration", "wait", "expected"),
    [(100.0, None, None), (100.0, 30.0, 70.0), (100.0, 0.0, 100.0), (50.0, 80.0, 0.0)],
)
def test_processing_ms(duration: float, wait: float | None, expected: float | None) -> None:
    assert metrics(duration_ms=duration, wait_ms=wait).processing_ms == expected


def test_request_metrics_is_frozen_and_error_defaults_to_none() -> None:
    item = metrics()
    assert item.error is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.status_code = 500  # type: ignore[misc]


def test_record_aggregates_every_counter() -> None:
    stats = ClientStats(slow_threshold_ms=1000)
    stats.record(metrics(duration_ms=200, wait_ms=50))
    stats.record(metrics(status_code=429, duration_ms=1000, wait_ms=300, will_retry=True))
    stats.record(metrics(status_code=503, duration_ms=10, will_retry=True))
    stats.record(metrics(status_code=None, duration_ms=5, error="ReadTimeout"))
    stats.record(metrics(status_code=404, duration_ms=1500))
    snap = stats.snapshot()
    assert snap.requests == 5
    assert snap.retries == 2
    assert snap.rate_limited == 1
    assert snap.transport_errors == 1
    assert snap.http_errors == 3
    assert snap.slow_requests == 2
    assert snap.duration_seconds == pytest.approx(2.715)
    # server processing estimate: duration minus reported wait, else the full duration
    assert snap.request_seconds == pytest.approx(0.150 + 0.700 + 0.010 + 0.005 + 1.500)
    assert snap.wait_seconds == pytest.approx(0.35)
    assert snap.max_wait_ms == 300
    assert snap.by_status == {200: 1, 429: 1, 503: 1, 404: 1}


def test_record_is_thread_safe() -> None:
    stats = ClientStats(slow_threshold_ms=10_000)
    threads_count, per_thread = 8, 500
    start = threading.Barrier(threads_count)

    def worker(index: int) -> None:
        start.wait(timeout=5)
        status = 200 if index % 2 else 503
        for _ in range(per_thread):
            stats.record(metrics(status_code=status, duration_ms=1.0, wait_ms=2.0))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    snap = stats.snapshot()
    total = threads_count * per_thread
    assert snap.requests == total
    assert snap.by_status == {200: total // 2, 503: total // 2}
    assert snap.http_errors == total // 2
    assert snap.duration_seconds == pytest.approx(total / 1000)
    assert snap.request_seconds == 0.0  # wait exceeds duration -> processing clamps to zero
    assert snap.wait_seconds == pytest.approx(total * 2 / 1000)


def test_snapshot_is_a_detached_copy() -> None:
    stats = ClientStats(slow_threshold_ms=1000)
    stats.record(metrics())
    snap = stats.snapshot()
    snap.by_status[999] = 1
    stats.record(metrics())
    assert stats.snapshot().by_status == {200: 2}
    assert snap.requests == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.requests = 0  # type: ignore[misc]


def test_as_dict_rounds_and_sorts() -> None:
    stats = ClientStats(slow_threshold_ms=1000)
    stats.record(metrics(status_code=503, duration_ms=1.23456, wait_ms=0.4444))
    stats.record(metrics(status_code=200, duration_ms=1.0))
    data = stats.snapshot().as_dict()
    assert data == {
        "requests": 2,
        "retries": 0,
        "rate_limited": 0,
        "transport_errors": 0,
        "http_errors": 1,
        "slow_requests": 0,
        "duration_seconds": 0.002,
        "request_seconds": 0.002,
        "wait_seconds": 0.0,
        "max_wait_ms": 0.4444,
        "by_status": {200: 1, 503: 1},
    }
    assert list(data["by_status"]) == [200, 503]
    keys = list(data)
    assert keys.index("duration_seconds") == keys.index("request_seconds") - 1


def test_reset_zeroes_everything() -> None:
    stats = ClientStats(slow_threshold_ms=1)
    stats.record(metrics(status_code=429, wait_ms=5, will_retry=True))
    stats.reset()
    assert stats.snapshot() == StatsSnapshot(
        requests=0,
        retries=0,
        rate_limited=0,
        transport_errors=0,
        http_errors=0,
        slow_requests=0,
        duration_seconds=0.0,
        request_seconds=0.0,
        wait_seconds=0.0,
        max_wait_ms=0.0,
        by_status={},
    )


def test_request_seconds_without_wait_equals_duration() -> None:
    stats = ClientStats(slow_threshold_ms=1000)
    stats.record(metrics(duration_ms=250))
    stats.record(metrics(duration_ms=250, wait_ms=100))
    snap = stats.snapshot()
    assert snap.duration_seconds == pytest.approx(0.5)
    assert snap.request_seconds == pytest.approx(0.4)


def test_slow_threshold_is_inclusive() -> None:
    stats = ClientStats(slow_threshold_ms=100)
    stats.record(metrics(duration_ms=99.9))
    stats.record(metrics(duration_ms=100))
    assert stats.snapshot().slow_requests == 1
