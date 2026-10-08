"""Run or serve a guarded, read-only weclapp API v2 contract check.

Direct mode prints one JSON report. ``--serve`` exposes ``GET /health`` and
``POST /run`` for a local webhook trigger. The script has no dependency beyond
weclappy and the Python standard library.
"""

import argparse
import hmac
import json
import os
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlsplit

from weclappy import Weclapp, WeclappAPIError

ARTICLE_PROPERTIES = "id,articleNumber,name,unitId,unit:id,unit:name"
ARTICLE_FILTERS = {"unitId-notnull": "true"}
BEARER_TOKEN_ENV = "WECLAPP_LIVE_CONTRACT_BEARER_TOKEN"


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing environment variable: {name}")
    return value


def add_check(
    report: dict[str, Any],
    name: str,
    condition: bool,
    **details: Any,
) -> None:
    report["checks"].append({"name": name, "ok": bool(condition), **details})
    if not condition:
        report["ok"] = False


def run_contract() -> dict[str, Any]:
    if os.environ.get("WECLAPP_RUN_LIVE_CONTRACT") != "1":
        raise RuntimeError("set WECLAPP_RUN_LIVE_CONTRACT=1 to enable the probe")

    base_url = required_environment("WECLAPP_BASE_URL")
    api_key = required_environment("WECLAPP_API_KEY")
    if "/webapp/api/v2" not in base_url.rstrip("/"):
        raise RuntimeError("WECLAPP_BASE_URL must point to /webapp/api/v2")

    sample_limit = int(os.environ.get("WECLAPP_LIVE_CONTRACT_LIMIT", "3"))
    if sample_limit < 2:
        raise RuntimeError("WECLAPP_LIVE_CONTRACT_LIMIT must be at least 2")

    query: dict[str, Any] = {
        **ARTICLE_FILTERS,
        "pageSize": 1,
        "properties": ARTICLE_PROPERTIES,
        "additionalProperties": "currentSalesPrice",
        "includeReferencedEntities": "unitId",
        "sort": "id",
    }
    report: dict[str, Any] = {
        "ok": True,
        "endpoint": "GET /article",
        "query": query,
        "checks": [],
    }

    with Weclapp(base_url, api_key) as client:
        count_response = client.request(
            "GET",
            "article/count",
            params=ARTICLE_FILTERS,
        )
        total = count_response.get("result")
        if not isinstance(total, int) or isinstance(total, bool):
            raise RuntimeError(f"unexpected count response: {count_response!r}")
        if total < 1:
            raise RuntimeError("tenant has no article with a unitId")

        limit = min(total, sample_limit)
        sequential = client.get_all(
            "article",
            params=query,
            limit=limit,
            threaded=False,
            return_weclapp_response=True,
        )
        threaded = client.get_all(
            "article",
            params=query,
            limit=limit,
            threaded=True,
            max_workers=2,
            return_weclapp_response=True,
        )

    sequential_ids = [article.id for article in sequential.result]
    threaded_ids = [article.id for article in threaded.result]
    prices: list[Any] = (sequential.additional_properties or {}).get("currentSalesPrice", [])
    raw_references = (sequential.raw_response or {}).get("referencedEntities", {})
    native_units = raw_references.get("unit", [])
    normalized_units = (sequential.referenced_entities or {}).get("unit", {})

    report["counts"] = {
        "matching_articles": total,
        "sampled_articles": len(sequential_ids),
        "page_size": 1,
    }
    add_check(
        report,
        "multiple_pages_exercised",
        len(sequential_ids) >= 2,
        pages=len(sequential_ids),
    )
    add_check(
        report,
        "sequential_threaded_order_match",
        sequential_ids == threaded_ids,
        ids=sequential_ids,
    )
    add_check(
        report,
        "stable_unique_ids",
        len(sequential_ids) == len(set(sequential_ids)) == limit,
    )
    add_check(
        report,
        "additional_property_alignment",
        len(prices) == len(sequential.result)
        and all(
            article.get("currentSalesPrice") == prices[index]
            for index, article in enumerate(sequential.result)
        ),
        values=len(prices),
    )
    add_check(
        report,
        "additional_property_is_not_in_payload",
        all("currentSalesPrice" not in article.to_payload() for article in sequential.result),
    )
    add_check(
        report,
        "native_reference_shape",
        isinstance(native_units, list)
        and bool(native_units)
        and all(isinstance(unit, dict) and unit.get("id") for unit in native_units),
        native_units=len(native_units) if isinstance(native_units, list) else None,
    )
    add_check(
        report,
        "reference_colon_projection",
        isinstance(native_units, list)
        and all(
            set(unit).issubset({"id", "name"}) and unit.get("id") and unit.get("name")
            for unit in native_units
        ),
    )
    add_check(
        report,
        "normalized_reference_shape",
        isinstance(normalized_units, dict)
        and all(
            article.unitId in normalized_units
            and article.unit.id == article.unitId
            and article.unit.get("name")
            for article in sequential.result
        ),
        normalized_units=len(normalized_units) if isinstance(normalized_units, dict) else None,
    )
    return report


def redact_known_secrets(message: str) -> str:
    """Keep credentials out of JSON reports even if an exception echoes one."""
    for name in ("WECLAPP_API_KEY", BEARER_TOKEN_ENV):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    return message


def contract_report() -> dict[str, Any]:
    """Return a JSON-safe report without raising request or contract errors."""
    try:
        return run_contract()
    except WeclappAPIError as exc:
        return {
            "ok": False,
            "error": {
                "kind": type(exc).__name__,
                "status_code": exc.status_code,
                "error_type": exc.error_type,
                "correlation_id": exc.correlation_id,
            },
        }
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        return {
            "ok": False,
            "error": {
                "kind": type(exc).__name__,
                "message": redact_known_secrets(str(exc)),
            },
        }
    except Exception as exc:
        # A webhook must return a controlled response even for transport-level
        # failures. Do not include an arbitrary exception message here because
        # third-party exceptions may contain request metadata.
        return {
            "ok": False,
            "error": {
                "kind": type(exc).__name__,
                "message": "unexpected live contract failure",
            },
        }


def make_handler(bearer_token: str) -> type[BaseHTTPRequestHandler]:
    """Build a quiet request handler that never logs headers or credentials."""

    class ContractHandler(BaseHTTPRequestHandler):
        server_version = "weclappy-live-contract/1"
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:
            # BaseHTTPRequestHandler otherwise writes request paths to stderr.
            # The two fixed routes need no access log, and headers are never
            # included in output.
            return

        def send_json(
            self,
            status: int,
            payload: dict[str, Any],
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if urlsplit(self.path).path != "/health":
                self.send_json(404, {"ok": False, "error": "not_found"})
                return
            self.send_json(
                200,
                {
                    "ok": True,
                    "service": "weclappy-live-contract",
                    "credentials_checked": False,
                },
            )

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/run":
                self.send_json(404, {"ok": False, "error": "not_found"})
                return
            authorization = self.headers.get("Authorization", "")
            if not hmac.compare_digest(
                authorization,
                "Bearer " + bearer_token,
            ):
                self.send_json(
                    401,
                    {"ok": False, "error": "unauthorized"},
                    {"WWW-Authenticate": 'Bearer realm="live-contract"'},
                )
                return

            report = contract_report()
            self.send_json(200 if report.get("ok") else 502, report)

    return ContractHandler


def serve(host: str, port: int) -> int:
    """Serve the contract webhook with mandatory bearer auth for ``/run``."""
    bearer_token = required_environment(BEARER_TOKEN_ENV)

    api_key = os.environ.get("WECLAPP_API_KEY")
    if api_key and hmac.compare_digest(bearer_token, api_key):
        raise RuntimeError(f"{BEARER_TOKEN_ENV} must be separate from WECLAPP_API_KEY")

    server = HTTPServer((host, port), make_handler(bearer_token))
    startup = {
        "ok": True,
        "mode": "serve",
        "host": host,
        "port": server.server_port,
        "authentication": "bearer",
        "routes": {"health": "GET /health", "run": "POST /run"},
    }
    print(json.dumps(startup, sort_keys=True), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def port_number(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="serve GET /health and POST /run instead of running once",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="webhook bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=port_number,
        default=8765,
        help="webhook bind port (default: 8765)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.serve:
        try:
            return serve(args.host, args.port)
        except (OSError, RuntimeError, ValueError) as exc:
            report = {
                "ok": False,
                "error": {
                    "kind": type(exc).__name__,
                    "message": redact_known_secrets(str(exc)),
                },
            }
            print(json.dumps(report, indent=2, sort_keys=True))
            return 2

    report = contract_report()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
