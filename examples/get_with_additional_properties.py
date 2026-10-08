"""Read additionalProperties merged onto wrapped entities (read-only)."""

import os

from weclappy import Weclapp, WeclappAPIError


def client_from_environment() -> Weclapp:
    try:
        return Weclapp.for_tenant(os.environ["WECLAPP_TENANT"], os.environ["WECLAPP_API_KEY"])
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
        print(f"  merged additional properties: {sorted(article.additional_properties)}")
        print(f"  dropped by to_payload(): {'currentSalesPrice' not in article.to_payload()}")


if __name__ == "__main__":
    main()
