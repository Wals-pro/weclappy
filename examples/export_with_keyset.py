"""Export a large entity with keyset pagination, resumable by id (read-only).

iter_keyset() pages with sort=id and id-gt=<last id>, so rows are never skipped
or repeated while other users create or delete records. Set
WECLAPP_START_AFTER to an id printed by an earlier run to resume.
"""

import csv
import os
import sys

from weclappy import Weclapp, WeclappAPIError


def main() -> None:
    try:
        tenant, api_key = os.environ["WECLAPP_TENANT"], os.environ["WECLAPP_API_KEY"]
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc
    start_after = os.environ.get("WECLAPP_START_AFTER") or None

    writer = csv.writer(sys.stdout)
    writer.writerow(["id", "customerNumber", "company"])
    last_id = start_after
    try:
        with Weclapp.for_tenant(tenant, api_key) as client:
            for party in client.iter_keyset(
                "party",
                {"partyType-eq": "CUSTOMER", "properties": "id,customerNumber,company"},
                start_after=start_after,
                limit=int(os.environ.get("WECLAPP_EXPORT_LIMIT", "1000")),
            ):
                writer.writerow([party.id, party.get("customerNumber"), party.get("company")])
                last_id = party.id
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error after id {last_id}: {exc}") from exc
    print(f"Done; resume with WECLAPP_START_AFTER={last_id}", file=sys.stderr)


if __name__ == "__main__":
    main()
