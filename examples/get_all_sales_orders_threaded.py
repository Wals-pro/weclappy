"""Read a larger result set with threaded="auto" and adaptive concurrency (read-only)."""

import os

from weclappy import RequestMetrics, Weclapp, WeclappAPIError, WeclappPaginationError


def print_queue_waits(metrics: RequestMetrics) -> None:
    if metrics.wait_ms:
        print(
            f"  queued {metrics.wait_ms:.0f} ms ({metrics.wait_reason}) on {metrics.path}, "
            f"concurrency target now {metrics.concurrency_target}"
        )


def main() -> None:
    try:
        tenant, api_key = os.environ["WECLAPP_TENANT"], os.environ["WECLAPP_API_KEY"]
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc

    try:
        with Weclapp.for_tenant(tenant, api_key, on_response=print_queue_waits) as client:
            # Page 1 is read first; only a full page triggers /count and parallel pages.
            # sort=id is added automatically because params has no sort/orderBy.
            orders = client.get_all(
                "salesOrder",
                {"properties": "id,orderNumber,status"},
                limit=5_000,
                max_records=100_000,
            )
            stats = client.stats
    except WeclappPaginationError as exc:
        raise SystemExit(f"Inconsistent read, retry it: {exc}") from exc
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    print(f"Fetched {len(orders)} sales orders in {stats.requests} requests")
    for order in orders[:5]:
        print(f"- {order.get('orderNumber', order.id)} ({order.get('status')})")


if __name__ == "__main__":
    main()
