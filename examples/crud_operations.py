"""Create, read, update, and remove a temporary party.

This example performs real writes. It only runs after explicit opt-in and tries
to remove the temporary record even if a later step fails.
"""

import os
from typing import Optional
from uuid import uuid4

from weclappy import Weclapp, WeclappAPIError


def client_from_environment() -> Weclapp:
    try:
        return Weclapp(
            os.environ["WECLAPP_BASE_URL"],
            os.environ["WECLAPP_API_KEY"],
        )
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc


def find_temporary_party(client: Weclapp, customer_number: str) -> Optional[str]:
    matches = client.get(
        "party",
        params={
            "customerNumber-eq": customer_number,
            "pageSize": 2,
            "properties": "id",
            "sort": "id",
        },
    )
    return matches[0].id if len(matches) == 1 else None


def main() -> None:
    if os.environ.get("WECLAPP_ENABLE_WRITES") != "1":
        raise SystemExit(
            "This example writes to weclapp. Set WECLAPP_ENABLE_WRITES=1 "
            "only in a tenant where creating a temporary party is safe."
        )

    suffix = uuid4().hex[:10]
    customer_number = f"WEC{suffix}"
    party_id = None
    create_attempted = False

    with client_from_environment() as client:
        try:
            create_attempted = True
            created = client.post(
                "party",
                {
                    "customerNumber": customer_number,
                    "partyType": "PERSON",
                    "firstName": "Weclappy",
                    "lastName": "Example",
                    "email": f"weclappy-{suffix}@example.invalid",
                },
            )
            party_id = created["id"]
            print(f"Created temporary party {party_id}")

            party = client.get(
                "party",
                id=party_id,
                params={"properties": "id,firstName,lastName"},
            )
            print(f"Read party: {party.firstName} {party.lastName}")

            updated = client.put(
                "party",
                id=party_id,
                data={"lastName": "Example Updated"},
            )
            print(f"Updated party: {updated.get('lastName', 'ok')}")
        except WeclappAPIError as exc:
            raise SystemExit(f"weclapp API error: {exc}") from exc
        finally:
            if create_attempted and party_id is None:
                try:
                    party_id = find_temporary_party(client, customer_number)
                except WeclappAPIError as lookup_exc:
                    print(
                        f"Could not reconcile temporary party {customer_number}: "
                        f"{lookup_exc}"
                    )
            if party_id is not None:
                try:
                    client.delete("party", id=party_id)
                    print(f"Removed temporary party {party_id}")
                except WeclappAPIError as cleanup_exc:
                    print(
                        f"Cleanup failed for party {party_id}: {cleanup_exc}. "
                        "Please remove it manually."
                    )
            elif create_attempted:
                print(
                    f"No unique temporary party found for {customer_number}. "
                    "Check this customer number manually if creation was ambiguous."
                )


if __name__ == "__main__":
    main()
