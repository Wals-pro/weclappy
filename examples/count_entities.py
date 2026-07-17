"""Count articles without downloading every record."""

import os
from typing import Dict, Optional

from weclappy import Weclapp, WeclappAPIError


def client_from_environment() -> Weclapp:
    try:
        return Weclapp(
            os.environ["WECLAPP_BASE_URL"],
            os.environ["WECLAPP_API_KEY"],
        )
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc


def count_articles(
    client: Weclapp,
    filters: Optional[Dict[str, str]] = None,
) -> int:
    response = client.call_method("article", "count", params=filters)
    count = response.get("result")
    if not isinstance(count, int):
        raise RuntimeError(f"Unexpected count response: {response!r}")
    return count


def main() -> None:
    try:
        with client_from_environment() as client:
            total = count_articles(client)
            active = count_articles(client, {"filter": "active = true"})
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    print(f"Articles: {total}")
    print(f"Active articles: {active}")


if __name__ == "__main__":
    main()
