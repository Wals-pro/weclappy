"""Download the PDF of one sales invoice (read-only)."""

import os
from pathlib import Path

from weclappy import Weclapp, WeclappAPIError


def client_from_environment() -> Weclapp:
    try:
        return Weclapp.for_tenant(os.environ["WECLAPP_TENANT"], os.environ["WECLAPP_API_KEY"])
    except KeyError as exc:
        raise SystemExit(f"Missing environment variable: {exc.args[0]}") from exc


def main() -> None:
    output = Path(os.environ.get("WECLAPP_OUTPUT_FILE", "sales-invoice.pdf"))
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {output}")

    try:
        with client_from_environment() as client:
            invoices = client.get_all("salesInvoice", {"properties": "id"}, limit=1)
            if not invoices:
                raise SystemExit("No sales invoice is available to download.")

            downloaded = client.download(
                "salesInvoice",
                entity_id=invoices[0].id,
                action="downloadLatestSalesInvoicePdf",
            )
    except WeclappAPIError as exc:
        raise SystemExit(f"weclapp API error: {exc}") from exc

    content = downloaded.get("content")
    if not isinstance(content, bytes):
        raise SystemExit(f"Unexpected download response: {downloaded!r}")

    output.write_bytes(content)
    print(
        f"Saved {len(content)} bytes to {output} "
        f"({downloaded.get('content_type', 'unknown content type')}, "
        f"server filename: {downloaded.get('filename', '-')})"
    )


if __name__ == "__main__":
    main()
