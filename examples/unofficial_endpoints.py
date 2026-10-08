"""Use weclapp's unofficial read endpoints, always with an official fallback.

UNOFFICIAL: POST {entity}/query, POST {entity}/count, POST batch/query and
meta/openapi.yaml?includeHidden=true are listed only in weclapp's hidden
OpenAPI document. weclapp does not announce changes to them. This example is
read-only and runs only with WECLAPP_ENABLE_UNOFFICIAL=1.
"""

import os

from weclappy import Weclapp, WeclappAPIError, WeclappEntity


def query_by_ids(client: Weclapp, ids: list[str]) -> list[WeclappEntity]:
    """Body-based id filter (no URL limit), falling back to get_by_ids."""
    try:
        rows = client.query(
            "article",
            filter=f"id in [{','.join(ids)}]",
            properties=["id", "articleNumber"],
            order_by=["id"],
            page_size=len(ids),
        )
    except WeclappAPIError as exc:
        print(f"query() failed ({exc.status_code}); using the official get_by_ids()")
        rows = client.get_by_ids("article", ids, {"properties": "id,articleNumber"})
    return rows if isinstance(rows, list) else []


def main() -> None:
    if os.environ.get("WECLAPP_ENABLE_UNOFFICIAL") != "1":
        raise SystemExit(
            "This example calls unofficial weclapp endpoints. "
            "Set WECLAPP_ENABLE_UNOFFICIAL=1 to run it against a test tenant."
        )
    try:
        tenant, api_key = os.environ["WECLAPP_TENANT"], os.environ["WECLAPP_API_KEY"]
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc

    with Weclapp.for_tenant(tenant, api_key) as client:
        ids = [str(row.id) for row in client.get("article", params={"properties": "id"})[:5]]
        rows = query_by_ids(client, ids)
        print(f"query(): {[row.get('articleNumber') for row in rows]}")

        try:
            active = client.query_count("article", filter="active = true")
        except WeclappAPIError:
            active = client.count("article", {"active-eq": "true"})
        print(f"Active articles: {active}")

        try:
            results = client.batch_query(
                ["article/count", "party/count?partyType-eq=CUSTOMER", "unitX?pageSize=1"]
            )
        except WeclappAPIError as exc:
            print(f"batch_query() unavailable: {exc.status_code}")
        else:
            for result in results:  # ordered by request index; failures do not fail the batch
                print(f"  batch[{result.index}] ok={result.ok} status={result.status}")

        hidden = client.openapi(include_hidden=True)
        print(f"Hidden OpenAPI document: {len(hidden)} characters")


if __name__ == "__main__":
    main()
