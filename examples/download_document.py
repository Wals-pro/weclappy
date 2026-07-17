"""Download the PDF for one sales invoice."""

import os
from pathlib import Path

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
    output = Path(os.environ.get("WECLAPP_OUTPUT_FILE", "sales-invoice.pdf"))
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {output}")

    try:
        with client_from_environment() as client:
            invoices = client.get_all(
                "salesInvoice",
                params={"properties": "id", "sort": "id"},
                limit=1,
            )
            if not invoices:
                raise SystemExit("No sales invoice is available to download.")

            invoice = invoices[0]
            downloaded = client.download(
                "salesInvoice",
                id=invoice.id,
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
        f"({downloaded.get('content_type', 'unknown content type')})"
    )


if __name__ == "__main__":
    main()
