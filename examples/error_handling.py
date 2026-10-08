"""Handle typed weclappy errors using read-only requests."""

import os

from weclappy import (
    Weclapp,
    WeclappAPIError,
    WeclappAuthenticationError,
    WeclappConcurrencyTimeoutError,
    WeclappError,
    WeclappNotFoundError,
    WeclappRateLimitError,
    WeclappTransportError,
    WeclappValidationError,
)


def client_from_environment() -> Weclapp:
    try:
        return Weclapp.for_tenant(os.environ["WECLAPP_TENANT"], os.environ["WECLAPP_API_KEY"])
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc


def describe(exc: WeclappAPIError) -> None:
    print(f"  type: {type(exc).__name__}")
    print(f"  status: {exc.status_code}, problem type: {exc.error_type}")
    print(f"  correlation id: {exc.correlation_id}, queue wait: {exc.wait_ms} ms")
    print(f"  retryable in principle: {exc.is_retryable}")
    for message in exc.get_all_messages():
        print(f"  - {message}")


def main() -> None:
    with client_from_environment() as client:
        print("1. A record that does not exist:")
        try:
            client.get("article", "0")
        except WeclappNotFoundError as exc:
            describe(exc)

        print("2. An endpoint that does not exist:")
        try:
            client.get("__weclappy_example_missing_endpoint__")
        except WeclappAPIError as exc:
            describe(exc)

        print("3. An invalid filter value:")
        try:
            client.get("article", params={"pageSize": 1, "createdDate-gt": "not-a-number"})
        except WeclappValidationError as exc:
            print("  validation messages:", exc.get_validation_messages())
        except WeclappAPIError as exc:
            describe(exc)

        print("4. The full hierarchy in one handler:")
        try:
            client.count("article")
            print("  count succeeded")
        except WeclappAuthenticationError:
            print("  the API key is invalid or lacks permission")
        except WeclappRateLimitError:
            print("  still rate limited after the read retry budget")
        except WeclappTransportError as exc:
            print(f"  no response; request may have been processed: {exc.outcome_unknown}")
        except WeclappConcurrencyTimeoutError:
            print("  no read permit became available in time")
        except WeclappError as exc:
            print(f"  other weclappy error: {exc}")


if __name__ == "__main__":
    main()
