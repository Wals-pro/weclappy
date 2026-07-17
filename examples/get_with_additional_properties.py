"""Read additionalProperties directly from wrapped entities."""

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
            articles = client.get(
                "article",
                params={
                    "pageSize": 3,
                    "properties": "id,articleNumber,name",
                    "additionalProperties": "currentSalesPrice",
                    "sort": "id",
                },
            )
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    for article in articles:
        print(f"{article.get('articleNumber', article.id)}: {article.get('name', '')}")
        print(f"  current sales price: {article.get('currentSalesPrice')}")


if __name__ == "__main__":
    main()
