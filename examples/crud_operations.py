"""Create, read, update and delete a temporary party.

This example performs real writes. It runs only after explicit opt-in, uses an
optimistic-lock update, reconciles an unknown create outcome by reading back a
business key, and removes the temporary record even if a later step fails.
"""

import os
import time
from uuid import uuid4

from weclappy import (
    Weclapp,
    WeclappAPIError,
    WeclappOptimisticLockError,
    WeclappTransportError,
)

READ_BACK_DELAYS = (0, 2, 5, 10, 20, 30)


def client_from_environment() -> Weclapp:
    try:
        return Weclapp.for_tenant(os.environ["WECLAPP_TENANT"], os.environ["WECLAPP_API_KEY"])
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc


def find_party_id(client: Weclapp, customer_number: str) -> str | None:
    matches = client.get(
        "party",
        params={"customerNumber-eq": customer_number, "pageSize": 2, "properties": "id"},
    )
    return str(matches[0].id) if len(matches) == 1 else None


def create_party(client: Weclapp, customer_number: str, suffix: str) -> str | None:
    """Create once; after an unknown outcome, read back instead of posting again."""
    payload = {
        "customerNumber": customer_number,
        "partyType": "PERSON",
        "firstName": "Weclappy",
        "lastName": "Example",
        "email": f"weclappy-{suffix}@example.invalid",
    }
    try:
        created = client.post("party", payload)
        return str(created["id"])
    except WeclappTransportError as exc:
        if not exc.outcome_unknown:
            raise
        print("Create outcome unknown; reading back by customer number ...")
        for delay in READ_BACK_DELAYS:
            time.sleep(delay)
            party_id = find_party_id(client, customer_number)
            if party_id is not None:
                return party_id
        return None


def rename_party(client: Weclapp, party_id: str, last_name: str) -> None:
    """GET -> modify -> PUT with version; re-read on an optimistic-lock conflict."""
    for _attempt in range(3):
        party = client.get("party", party_id, {"properties": "id,version,lastName"})
        try:
            client.put("party", party_id, {"version": party.version, "lastName": last_name})
            return
        except WeclappOptimisticLockError:
            print("Party changed concurrently; retrying with a fresh version")
    raise SystemExit(f"Could not update party {party_id} after three attempts")


def main() -> None:
    if os.environ.get("WECLAPP_ENABLE_WRITES") != "1":
        raise SystemExit(
            "This example writes to weclapp. Set WECLAPP_ENABLE_WRITES=1 "
            "only in a tenant where creating a temporary party is safe."
        )

    suffix = uuid4().hex[:10]
    customer_number = f"WEC{suffix}"
    party_id: str | None = None

    with client_from_environment() as client:
        try:
            party_id = create_party(client, customer_number, suffix)
            if party_id is None:
                raise SystemExit(
                    f"Create outcome still unknown for {customer_number}; check it manually."
                )
            print(f"Created temporary party {party_id}")

            party = client.get("party", party_id, {"properties": "id,firstName,lastName"})
            print(f"Read party: {party.firstName} {party.lastName}")

            rename_party(client, party_id, "Example Updated")
            print("Updated party")
        except WeclappAPIError as exc:
            raise SystemExit(f"weclapp API error: {exc}") from exc
        finally:
            if party_id is not None:
                try:
                    client.delete("party", party_id)
                    print(f"Removed temporary party {party_id}")
                except WeclappAPIError as cleanup_exc:
                    print(
                        f"Cleanup failed for party {party_id}: {cleanup_exc}. Remove it manually."
                    )


if __name__ == "__main__":
    main()
