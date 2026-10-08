"""Combine additionalProperties and referenced entities in a WeclappResponse (read-only)."""

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
            response = client.get(
                "article",
                params={
                    "pageSize": 3,
                    "properties": "id,articleNumber,name,unitId,unit:id,unit:name",
                    "additionalProperties": "currentSalesPrice",
                    "includeReferencedEntities": "unitId",
                    "sort": "id",
                },
                return_weclapp_response=True,
            )
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    articles = response.result if isinstance(response.result, list) else [response.result]
    for article in articles:
        unit = getattr(article, "unit", None)
        print(f"{article.get('articleNumber', article.get('id'))}: {article.get('name', '')}")
        print(f"  unit: {unit.get('name') if unit else article.get('unitId')}")
        print(f"  current sales price: {article.get('currentSalesPrice')}")

    native_units = (response.raw_referenced_entities or {}).get("unit", [])
    normalized_units = (response.referenced_entities or {}).get("unit", {})
    print(f"Native unit references (list): {len(native_units)}")
    print(f"Normalized unit references (id map): {len(normalized_units)}")
    print(f"additionalProperties columns: {sorted(response.additional_properties or {})}")


if __name__ == "__main__":
    main()
