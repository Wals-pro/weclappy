"""Attach a local file to an existing weclapp record.

This example performs a real upload and only runs after explicit opt-in.
"""

import os
from pathlib import Path

from weclappy import Weclapp, WeclappAPIError


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing environment variable: {name}")
    return value


def main() -> None:
    if os.environ.get("WECLAPP_ENABLE_WRITES") != "1":
        raise SystemExit(
            "This example uploads a real document. Set WECLAPP_ENABLE_WRITES=1 "
            "only after checking the target record."
        )

    path = Path(required_environment("WECLAPP_UPLOAD_FILE"))
    if not path.is_file():
        raise SystemExit(f"Upload file does not exist: {path}")

    entity_name = required_environment("WECLAPP_ENTITY_NAME")
    entity_id = required_environment("WECLAPP_ENTITY_ID")

    try:
        with Weclapp(
            required_environment("WECLAPP_BASE_URL"),
            required_environment("WECLAPP_API_KEY"),
        ) as client:
            result = client.upload(
                "document",
                data=path.read_bytes(),
                action="upload",
                filename=path.name,
                params={
                    "entityName": entity_name,
                    "entityId": entity_id,
                    "name": path.name,
                },
            )
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    document = result.get("result", result)
    print(f"Uploaded {path.name}; document id: {document.get('id', 'unknown')}")


if __name__ == "__main__":
    main()
