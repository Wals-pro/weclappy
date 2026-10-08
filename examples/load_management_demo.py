"""Watch the adaptive load controller during a get_all (read-only).

Prints every attempt that weclapp queued, then the client statistics and the
controller snapshot. Set WECLAPP_DEMO_ENTITY (default: article) and
WECLAPP_DEMO_LIMIT (default: 5000) to vary the load.
"""

import json
import os
import threading

from weclappy import RequestMetrics, Weclapp, WeclappAPIError


class AttemptLog:
    """Thread-safe on_response hook that remembers queue waits and retries."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.queued: list[RequestMetrics] = []
        self.retried: list[RequestMetrics] = []

    def __call__(self, metrics: RequestMetrics) -> None:
        with self._lock:
            if metrics.wait_ms:
                self.queued.append(metrics)
            if metrics.will_retry:
                self.retried.append(metrics)


def main() -> None:
    try:
        tenant, api_key = os.environ["WECLAPP_TENANT"], os.environ["WECLAPP_API_KEY"]
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc
    entity = os.environ.get("WECLAPP_DEMO_ENTITY", "article")
    limit = int(os.environ.get("WECLAPP_DEMO_LIMIT", "5000"))

    log = AttemptLog()
    try:
        with Weclapp.for_tenant(tenant, api_key, max_concurrency=10, on_response=log) as client:
            print(f"Controller before: {client.concurrency.snapshot()}")
            rows = client.get_all(entity, {"properties": "id", "pageSize": 100}, limit=limit)
            stats = client.stats
            snapshot = client.concurrency.snapshot()
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    print(f"Read {len(rows)} {entity} rows")
    for metrics in log.queued[:10]:
        print(
            f"  queued: {metrics.method} {metrics.path} attempt {metrics.attempt} "
            f"wait={metrics.wait_ms:.0f} ms reason={metrics.wait_reason} "
            f"target={metrics.concurrency_target}"
        )
    for metrics in log.retried[:10]:
        print(f"  retry: {metrics.path} status={metrics.status_code} in {metrics.retry_delay:.2f}s")
    print("Client stats:", json.dumps(stats.as_dict(), indent=2))
    print(
        f"Controller after: target={snapshot.target} ceiling={snapshot.ceiling} "
        f"active={snapshot.active} cooldown={snapshot.cooldown_remaining:.1f}s "
        f"epoch={snapshot.epoch_completed}/{snapshot.epoch_size}"
    )


if __name__ == "__main__":
    main()
