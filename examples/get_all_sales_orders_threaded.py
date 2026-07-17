"""Fetch a larger result set with adaptive parallel page requests."""

import os

from weclappy import Weclapp, WeclappAPIError


def client_from_environment() -> Weclapp:
    try:
        return Weclapp(
            os.environ["WECLAPP_BASE_URL"],
            os.environ["WECLAPP_API_KEY"],
        )
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc


def main() -> None:
    try:
        with client_from_environment() as client:
            orders = client.get_all(
                "salesOrder",
                params={"properties": "id,orderNumber", "sort": "id"},
                limit=5_000,
            )
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    print(f"Fetched {len(orders)} sales orders")
    for order in orders[:5]:
        print(f"- {order.get('orderNumber', order.id)}")


if __name__ == "__main__":
    main()
