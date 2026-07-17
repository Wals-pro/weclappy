"""Inspect structured API errors using a read-only request."""

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
    with client_from_environment() as client:
        try:
            client.get("__weclappy_example_missing_endpoint__")
        except WeclappAPIError as exc:
            print(f"Status: {exc.status_code}")
            print(f"Not found: {exc.is_not_found}")
            print(f"Rate limited: {exc.is_rate_limited}")
            print(f"Retryable in principle: {exc.is_retryable}")

            for message in exc.get_all_messages():
                print(f"- {message}")
        else:
            raise SystemExit("The example endpoint unexpectedly exists.")


if __name__ == "__main__":
    main()
