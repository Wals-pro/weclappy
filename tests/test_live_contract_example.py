"""Offline contracts for the optional live-contract webhook example."""

import importlib.util
import json
from email.message import Message
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type

import pytest


EXAMPLE_PATH = Path(__file__).parents[1] / "examples" / "live_contract.py"
SPEC = importlib.util.spec_from_file_location("live_contract_example", EXAMPLE_PATH)
assert SPEC is not None and SPEC.loader is not None
live_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live_contract)


def call_handler(
    handler_type: Type[Any],
    method: str,
    path: str,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, Dict[str, str], Any]:
    """Exercise a BaseHTTPRequestHandler without opening a network socket."""
    handler = handler_type.__new__(handler_type)
    handler.command = method
    handler.path = path
    handler.request_version = "HTTP/1.1"
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.headers = Message()
    for name, value in (headers or {}).items():
        handler.headers[name] = value
    handler.wfile = BytesIO()

    getattr(handler, f"do_{method}")()

    header_bytes, body = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    header_lines = header_bytes.decode("iso-8859-1").split("\r\n")
    status = int(header_lines[0].split()[1])
    response_headers = dict(
        line.split(": ", 1) for line in header_lines[1:] if ": " in line
    )
    return status, response_headers, json.loads(body.decode("utf-8"))


def test_health_needs_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WECLAPP_BASE_URL", raising=False)
    monkeypatch.delenv("WECLAPP_API_KEY", raising=False)

    status, _, payload = call_handler(
        live_contract.make_handler("unused-health-token"),
        "GET",
        "/health",
    )

    assert status == 200
    assert payload == {
        "credentials_checked": False,
        "ok": True,
        "service": "weclappy-live-contract",
    }


def test_run_rejects_missing_bearer_token() -> None:
    status, headers, payload = call_handler(
        live_contract.make_handler("webhook-secret"),
        "POST",
        "/run",
    )

    assert status == 401
    assert headers["WWW-Authenticate"] == 'Bearer realm="live-contract"'
    assert payload == {"error": "unauthorized", "ok": False}


def test_run_accepts_valid_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        live_contract,
        "contract_report",
        lambda: {"ok": True, "checks": []},
    )

    status, _, payload = call_handler(
        live_contract.make_handler("webhook-secret"),
        "POST",
        "/run",
        {"Authorization": "Bearer webhook-secret"},
    )

    assert status == 200
    assert payload == {"checks": [], "ok": True}


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_serve_requires_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    monkeypatch.delenv(live_contract.BEARER_TOKEN_ENV, raising=False)

    with pytest.raises(RuntimeError, match=f"missing environment variable: {live_contract.BEARER_TOKEN_ENV}"):
        live_contract.serve(host, 8765)


def test_contract_report_stops_before_live_call_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WECLAPP_RUN_LIVE_CONTRACT", raising=False)
    monkeypatch.delenv("WECLAPP_BASE_URL", raising=False)
    monkeypatch.delenv("WECLAPP_API_KEY", raising=False)

    report = live_contract.contract_report()

    assert report == {
        "error": {
            "kind": "RuntimeError",
            "message": "set WECLAPP_RUN_LIVE_CONTRACT=1 to enable the probe",
        },
        "ok": False,
    }


def test_contract_report_redacts_known_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "never-include-this-value"
    monkeypatch.setenv("WECLAPP_API_KEY", secret)

    def fail_without_request() -> Any:
        raise RuntimeError(f"credential was {secret}")

    monkeypatch.setattr(live_contract, "run_contract", fail_without_request)
    report = live_contract.contract_report()

    rendered = json.dumps(report)
    assert secret not in rendered
    assert "[redacted]" in rendered
