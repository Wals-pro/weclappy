"""Resolve *Id fields through referencedEntities, then re-read rows with get_by_ids."""

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
                    "properties": "id,articleNumber,name,unitId,unit:id,unit:name",
                    "includeReferencedEntities": "unitId",
                    "sort": "id",
                },
            )
            for article in articles:
                unit = getattr(article, "unit", None)
                unit_label = unit.get("name", unit.id) if unit else article.get("unitId")
                print(f"{article.get('articleNumber', article.id)}: unit={unit_label}")

            # get_by_ids keeps the input order and drops ids weclapp no longer knows.
            ids = [str(article.id) for article in reversed(articles)]
            rows = client.get_by_ids("article", ids, {"properties": "id,articleNumber"})
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    if isinstance(rows, list):
        print("Re-read in reverse order:", [row.get("articleNumber") for row in rows])


if __name__ == "__main__":
    main()
