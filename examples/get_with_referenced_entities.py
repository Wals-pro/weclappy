"""Resolve unitId fields through referencedEntities."""

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
                    "properties": (
                        "id,articleNumber,name,unitId,unit:id,unit:name"
                    ),
                    "includeReferencedEntities": "unitId",
                    "sort": "id",
                },
            )
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    for article in articles:
        unit = getattr(article, "unit", None)
        unit_label = unit.get("name", unit.id) if unit else article.get("unitId")
        print(f"{article.get('articleNumber', article.id)}: unit={unit_label}")


if __name__ == "__main__":
    main()
