"""Count records without downloading them (read-only)."""

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
            total = client.count("article")
            active = client.count("article", {"active-eq": "true"})
            # Projection and pagination keys are ignored by count().
            customers = client.count("party", {"partyType-eq": "CUSTOMER", "pageSize": 5})
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    print(f"Articles: {total}")
    print(f"Active articles: {active}")
    print(f"Customers: {customers}")


if __name__ == "__main__":
    main()
