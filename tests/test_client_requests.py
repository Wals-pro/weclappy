"""Weclapp request pipeline: validation, headers, hooks, retries and endpoint shapes.

``client.session.request`` is a MagicMock returning real ``requests.Response``
objects. ``time.sleep`` is recorded instead of slept, and the controller runs
on a :class:`fakeserver.FakeClock`, so cooldown waits are recorded too.
"""

from __future__ import annotations

import http.client
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from urllib3.exceptions import NewConnectionError, ProtocolError

from fakeserver import FakeClock, FakeSession, FakeTenant, Reply, make_response
from weclappy import (
    BatchResult,
    ConcurrencyController,
    ConcurrencySettings,
    OutgoingRequest,
    RequestMetrics,
    RetryPolicy,
    Weclapp,
    WeclappAPIError,
    WeclappEntity,
    WeclappNotFoundError,
    WeclappRateLimitError,
    WeclappRedirectError,
    WeclappRequestTimeoutError,
    WeclappResponse,
    WeclappTransportError,
    __version__,
)

BASE = "https://acme.weclapp.com/webapp/api/v2/"
PATH_PREFIX = "/webapp/api/v2/"


def ok(body: Any = None, **headers: str) -> requests.Response:
    return make_response(200, {"result": []} if body is None else body, headers=headers)


def status(code: int, body: Any = None, **headers: str) -> requests.Response:
    return make_response(code, {} if body is None else body, headers=headers)


def untyped(content: bytes) -> requests.Response:
    response = make_response(200, content)
    del response.headers["Content-Type"]
    return response


def refused() -> requests.exceptions.ConnectionError:
    return requests.exceptions.ConnectionError(NewConnectionError(None, "refused"))  # type: ignore[arg-type]


def dropped() -> requests.exceptions.ConnectionError:
    return requests.exceptions.ConnectionError(
        ProtocolError("Connection aborted.", http.client.RemoteDisconnected("closed"))
    )


@dataclass
class Harness:
    client: Weclapp
    request: MagicMock
    clock: FakeClock

    def call(self, index: int = -1) -> tuple[str, str, dict[str, Any]]:
        recorded = self.request.call_args_list[index]
        return recorded.args[0], recorded.args[1], recorded.kwargs

    @property
    def calls(self) -> int:
        return self.request.call_count


def harness(*responses: Any, cooldown: float = 0.0, **kwargs: Any) -> Harness:
    clock = FakeClock()
    controller = ConcurrencyController(
        ConcurrencySettings(min_rate_limit_cooldown=cooldown), clock=clock
    )
    clock.attach(controller)
    kwargs.setdefault("retry_policy", RetryPolicy(jitter=False))
    client = Weclapp(BASE, "secret-token", concurrency=controller, **kwargs)
    mock = MagicMock(name="session.request", side_effect=list(responses))
    client.session.request = mock  # type: ignore[method-assign]
    return Harness(client, mock, clock)


@pytest.fixture(autouse=True)
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr("weclappy.client.time.sleep", recorded.append)
    return recorded


# ------------------------------------------------------------ construction
@pytest.mark.parametrize(
    "base_url",
    ["acme.weclapp.com", "ftp://acme.weclapp.com/", "https:///x", "https://a/?q=1", "https://a/#f"],
)
def test_constructor_rejects_bad_base_url(base_url: str) -> None:
    with pytest.raises(ValueError, match="base_url"):
        Weclapp(base_url, "k")


@pytest.mark.parametrize("api_key", ["", "   "])
def test_constructor_rejects_empty_api_key(api_key: str) -> None:
    with pytest.raises(ValueError, match="api_key"):
        Weclapp(BASE, api_key)


@pytest.mark.parametrize(
    "timeout", [0, -1, float("inf"), float("nan"), True, (1,), (1, 2, 3), (1, 0)]
)
def test_constructor_rejects_bad_timeouts(timeout: Any) -> None:
    with pytest.raises(ValueError, match="timeout"):
        Weclapp(BASE, "k", timeout=timeout)


@pytest.mark.parametrize("value", [0, -5, True, 1.5])
def test_constructor_rejects_bad_timeout_headers(value: Any) -> None:
    with pytest.raises(ValueError, match="wait_timeout_ms"):
        Weclapp(BASE, "k", wait_timeout_ms=value)


def test_default_headers() -> None:
    client = Weclapp(BASE, "secret-token")
    headers = client.session.headers
    assert headers["AuthenticationToken"] == "secret-token"
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == f"weclappy/{__version__}"
    assert headers["X-Weclapp-Wait-Timeout-Ms"] == "30000"
    assert headers["X-Weclapp-Request-Timeout-Ms"] == "110000"


def test_header_overrides_and_omission() -> None:
    client = Weclapp(BASE, "k", user_agent="me/1", wait_timeout_ms=None, request_timeout_ms=None)
    assert client.session.headers["User-Agent"] == "me/1"
    assert "X-Weclapp-Wait-Timeout-Ms" not in client.session.headers
    assert "X-Weclapp-Request-Timeout-Ms" not in client.session.headers


@pytest.mark.parametrize(
    ("timeout", "header"), [(5, "4500"), ((1, 20), "18000"), (200, "110000"), (0.0005, "1")]
)
def test_client_level_timeout_keeps_the_server_header_below_it(timeout: Any, header: str) -> None:
    """Regression: a short client timeout used to keep the 110000 ms server header."""
    client = Weclapp(BASE, "k", timeout=timeout)
    assert client.session.headers["X-Weclapp-Request-Timeout-Ms"] == header


def test_owned_session_mounts_a_non_retrying_adapter() -> None:
    client = Weclapp(BASE, "k")
    adapter = client.session.get_adapter(BASE)
    assert adapter.max_retries.total == 0  # type: ignore[attr-defined]


def test_injected_session_gets_headers_but_no_adapter_and_is_not_closed() -> None:
    session = requests.Session()
    adapters_before = dict(session.adapters)
    session.close = MagicMock()  # type: ignore[method-assign]
    client = Weclapp(BASE, "secret-token", session=session)
    assert client.session is session
    assert session.adapters == adapters_before
    assert session.headers["AuthenticationToken"] == "secret-token"
    assert session.headers["User-Agent"].startswith("weclappy/")
    client.close()
    session.close.assert_not_called()


def test_owned_session_is_closed() -> None:
    client = Weclapp(BASE, "k")
    client.session.close = MagicMock()  # type: ignore[method-assign]
    with client:
        pass
    client.session.close.assert_called_once()


@pytest.mark.parametrize(
    ("tenant", "version", "expected"),
    [
        ("acme", 2, "https://acme.weclapp.com/webapp/api/v2/"),
        ("acme", 1, "https://acme.weclapp.com/webapp/api/v1/"),
        ("acme.example.com", 2, "https://acme.example.com/webapp/api/v2/"),
    ],
)
def test_for_tenant(tenant: str, version: int, expected: str) -> None:
    client = Weclapp.for_tenant(tenant, "k", api_version=version, timeout=5)
    assert client.base_url == expected
    assert client.timeout == 5


# --------------------------------------------------------- request() input
@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.example/x",
        "//evil.example/x",
        "http:article",
        "article#frag",
        "../secret",
        "a/../../b",
        "",
        "   ",
    ],
)
def test_request_rejects_foreign_or_traversing_endpoints(endpoint: str) -> None:
    h = harness()
    with pytest.raises(ValueError, match="endpoint"):
        h.client.request("GET", endpoint)
    assert h.calls == 0


def test_request_rejects_empty_method() -> None:
    with pytest.raises(ValueError, match="method"):
        harness().client.request(" ", "article")


@pytest.mark.parametrize(("endpoint", "suffix"), [("/article", "article"), ("a/b", "a/b")])
def test_request_builds_same_origin_urls(endpoint: str, suffix: str) -> None:
    h = harness(ok())
    h.client.request("get", endpoint)
    method, url, kwargs = h.call()
    assert (method, url) == ("GET", BASE + suffix)
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == 120.0


def test_request_passes_params_json_data() -> None:
    h = harness(ok())
    h.client.request("POST", "x/query", params={"a": 1}, json={"b": 2})
    _, _, kwargs = h.call()
    assert kwargs["params"] == {"a": 1}
    assert kwargs["json"] == {"b": 2}


def test_entity_payload_is_unwrapped() -> None:
    h = harness(status(201, {"id": "1"}))
    entity = WeclappEntity({"id": "1", "name": "n"})
    h.client.post("article", entity)
    sent = h.call()[2]["json"]
    assert type(sent) is dict
    assert sent == {"id": "1", "name": "n"}


# ------------------------------------------------------------- path segments
@pytest.mark.parametrize(
    ("entity_id", "encoded"),
    [("42", "42"), ("a b", "a%20b"), ("ä%", "%C3%A4%25"), ("x:y", "x%3Ay")],
)
def test_entity_id_is_percent_encoded(entity_id: str, encoded: str) -> None:
    h = harness(ok({}))
    h.client.put("article", entity_id, {})
    assert h.call()[1] == f"{BASE}article/id/{encoded}"


BAD_SEGMENTS = ["1/2", "1?x=y", "1#f", "", "  "]


@pytest.mark.parametrize("bad", BAD_SEGMENTS)
@pytest.mark.parametrize(
    "operation",
    [
        lambda c, v: c.put("article", v, {}),
        lambda c, v: c.delete("article", v),
        lambda c, v: c.download("document", v),
        lambda c, v: c.upload("document", b"x", v),
        lambda c, v: c.call_method("salesOrder", v, "1"),
        lambda c, v: c.call_method("salesOrder", "createPdf", v),
    ],
    ids=["put", "delete", "download", "upload", "call_method-action", "call_method-id"],
)
def test_path_segments_reject_separators(
    operation: Callable[[Weclapp, str], Any], bad: str
) -> None:
    h = harness()
    with pytest.raises(ValueError, match="must"):
        operation(h.client, bad)
    assert h.calls == 0


# ------------------------------------------------------------------- timeouts
@pytest.mark.parametrize(
    ("timeout", "header"),
    [(10, "9000"), ((3, 20), "18000"), (0.5, "450"), (200, None), (122.3, None)],
)
def test_per_request_timeout_lowers_server_timeout(timeout: Any, header: str | None) -> None:
    h = harness(ok())
    h.client.request("GET", "article", timeout=timeout)
    _, _, kwargs = h.call()
    assert kwargs["timeout"] == timeout
    assert kwargs["headers"].get("X-Weclapp-Request-Timeout-Ms") == header


def test_caller_header_wins_over_derived_timeout_header() -> None:
    h = harness(ok())
    h.client.request("GET", "article", timeout=10, headers={"X-Weclapp-Request-Timeout-Ms": "1234"})
    assert h.call()[2]["headers"]["X-Weclapp-Request-Timeout-Ms"] == "1234"


def test_no_derived_header_without_request_timeout_ms() -> None:
    h = harness(ok(), request_timeout_ms=None)
    h.client.request("GET", "article", timeout=1)
    assert "X-Weclapp-Request-Timeout-Ms" not in h.call()[2]["headers"]


@pytest.mark.parametrize("timeout", [0, -1, (1,), float("nan")])
def test_per_request_timeout_is_validated(timeout: Any) -> None:
    with pytest.raises(ValueError, match="timeout"):
        harness().client.request("GET", "article", timeout=timeout)


def test_client_tuple_timeout_is_used_by_default() -> None:
    h = harness(ok(), timeout=(2, 30))
    h.client.request("GET", "article")
    assert h.call()[2]["timeout"] == (2, 30)


# ---------------------------------------------------------------------- hooks
def test_before_request_can_mutate_headers_and_params() -> None:
    seen: list[OutgoingRequest] = []

    def hook(outgoing: OutgoingRequest) -> None:
        seen.append(outgoing)
        outgoing.headers["X-Trace"] = f"t{outgoing.attempt}"
        outgoing.params = {**(outgoing.params or {}), "extra": "1"}

    h = harness(status(503), ok(), before_request=hook)
    h.client.request("GET", "article", params={"a": "b"})
    assert [item.attempt for item in seen] == [1, 2]
    assert seen[0].method == "GET"
    assert seen[0].url == BASE + "article"
    assert seen[0].path == PATH_PREFIX + "article"
    assert "AuthenticationToken" not in seen[0].headers
    _, _, kwargs = h.call()
    assert kwargs["headers"]["X-Trace"] == "t2"
    assert kwargs["params"] == {"a": "b", "extra": "1"}


def test_before_request_can_add_params_to_a_request_without_params() -> None:
    def hook(outgoing: OutgoingRequest) -> None:
        outgoing.params = {"tenant": "x"}

    h = harness(ok(), before_request=hook)
    h.client.request("GET", "article")
    assert h.call()[2]["params"] == {"tenant": "x"}


def test_on_response_sees_every_attempt() -> None:
    seen: list[RequestMetrics] = []
    h = harness(
        status(503, **{"X-Weclapp-Wait-Ms": "40", "X-Request-Id": "r1"}),
        requests.exceptions.ReadTimeout("slow"),
        ok(**{"X-Weclapp-Wait-Reason": "concurrency"}),
        on_response=seen.append,
    )
    h.client.request("GET", "article")
    assert [m.attempt for m in seen] == [1, 2, 3]
    assert [m.status_code for m in seen] == [503, None, 200]
    assert [m.will_retry for m in seen] == [True, True, False]
    assert [m.retry_delay for m in seen] == pytest.approx([0.3, 0.6, 0.0])
    assert [m.error for m in seen] == [None, "ReadTimeout", None]
    assert seen[0].wait_ms == 40.0
    assert seen[0].correlation_id == "r1"
    assert seen[2].wait_reason == "concurrency"
    assert {m.method for m in seen} == {"GET"}
    assert {m.path for m in seen} == {PATH_PREFIX + "article"}
    assert all(m.concurrency_target >= 1 for m in seen)


def test_on_response_exception_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    def broken(_: RequestMetrics) -> None:
        raise RuntimeError("hook bug")

    h = harness(ok({"result": [{"id": "1"}]}), on_response=broken)
    with caplog.at_level(logging.ERROR, logger="weclappy"):
        assert h.client.request("GET", "article") == {"result": [{"id": "1"}]}
    assert "on_response hook raised" in caplog.text


def test_logs_never_contain_token_or_query(caplog: pytest.LogCaptureFixture) -> None:
    h = harness(status(503), ok())
    with caplog.at_level(logging.DEBUG, logger="weclappy"):
        h.client.request("GET", "article", params={"name-eq": "geheim"})
    assert "secret-token" not in caplog.text
    assert "geheim" not in caplog.text
    assert "[API_RETRY]" in caplog.text


# --------------------------------------------------------------- read retries
@pytest.mark.parametrize("code", [500, 502, 503, 504])
def test_reads_retry_5xx(code: int, sleeps: list[float]) -> None:
    h = harness(status(code), ok())
    assert h.client.get("article") == []
    assert h.calls == 2
    assert sleeps == [0.3]


@pytest.mark.parametrize(
    "exc",
    [
        requests.exceptions.ReadTimeout("r"),
        requests.exceptions.ChunkedEncodingError("c"),
        requests.exceptions.ConnectTimeout("t"),
        dropped(),
        refused(),
    ],
    ids=["read-timeout", "chunked", "connect-timeout", "dropped", "refused"],
)
def test_reads_retry_transport_failures(exc: Exception) -> None:
    h = harness(exc, ok())
    assert h.client.get("article") == []
    assert h.calls == 2


def test_ssl_errors_are_never_retried() -> None:
    h = harness(requests.exceptions.SSLError("cert"))
    with pytest.raises(WeclappTransportError) as info:
        h.client.get("article")
    assert h.calls == 1
    assert isinstance(info.value.__cause__, requests.exceptions.SSLError)


def test_read_transient_budget_exhaustion(sleeps: list[float]) -> None:
    h = harness(*[status(503)] * 4)
    with pytest.raises(WeclappAPIError) as info:
        h.client.get("article")
    assert info.value.status_code == 503
    assert h.calls == 4
    assert sleeps == pytest.approx([0.3, 0.6, 1.2])


def test_read_429_uses_its_own_budget(sleeps: list[float]) -> None:
    h = harness(
        status(503),
        status(429),
        status(429),
        ok(),
        retry_policy=RetryPolicy(max_retries=1, rate_limit_retries=2, jitter=False),
    )
    assert h.client.get("article") == []
    assert h.calls == 4
    assert sleeps == pytest.approx([0.3, 2.0, 4.0])
    assert h.clock.waits, "429 also started a shared cooldown the next read waited out"


def test_read_429_exhaustion_raises_rate_limit_error() -> None:
    h = harness(
        status(429), status(429), retry_policy=RetryPolicy(rate_limit_retries=1, jitter=False)
    )
    with pytest.raises(WeclappRateLimitError):
        h.client.get("article")
    assert h.calls == 2


def test_read_problem_retry_once() -> None:
    timeout = make_response(400, {"type": "https://api.weclapp.com/errors/request_timeout"})
    h = harness(timeout, timeout)
    with pytest.raises(WeclappRequestTimeoutError):
        h.client.get("article")
    assert h.calls == 2


@pytest.mark.parametrize("endpoint", ["article/query", "article/count", "batch/query"])
def test_read_only_posts_are_retried(endpoint: str) -> None:
    h = harness(status(503), ok())
    h.client.request("POST", endpoint, json={})
    assert h.calls == 2


def test_redirect_is_surfaced_not_followed() -> None:
    h = harness(make_response(302, None, headers={"Location": "https://elsewhere.example/"}))
    with pytest.raises(WeclappRedirectError, match=r"elsewhere\.example"):
        h.client.get("article")
    assert h.calls == 1
    assert h.call()[2]["allow_redirects"] is False


# -------------------------------------------------------------- write safety
WRITES: list[tuple[str, Callable[[Weclapp], Any]]] = [
    ("post", lambda c: c.post("article", {"name": "x"})),
    ("put", lambda c: c.put("article", "1", {"name": "x"})),
    ("delete", lambda c: c.delete("article", "1")),
    ("upload", lambda c: c.upload("document", b"%PDF", action="upload", filename="a.pdf")),
    ("call_method_post", lambda c: c.call_method("salesOrder", "createPdf", "1", method="POST")),
]
WRITE_IDS = [name for name, _ in WRITES]
WRITE_OPS = [op for _, op in WRITES]


@pytest.mark.parametrize("operation", WRITE_OPS, ids=WRITE_IDS)
@pytest.mark.parametrize(
    "failure",
    [
        requests.exceptions.ReadTimeout("r"),
        requests.exceptions.ChunkedEncodingError("c"),
        dropped(),
    ],
    ids=["read-timeout", "chunked", "dropped"],
)
def test_writes_with_unknown_outcome_are_not_retried(
    operation: Callable[[Weclapp], Any], failure: Exception
) -> None:
    h = harness(failure, ok())
    with pytest.raises(WeclappTransportError, match="read the entity back") as info:
        operation(h.client)
    assert h.calls == 1
    assert info.value.request_sent is True
    assert info.value.outcome_unknown is True


@pytest.mark.parametrize("operation", WRITE_OPS, ids=WRITE_IDS)
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (status(500), WeclappAPIError),
        (status(503), WeclappAPIError),
        (status(429), WeclappRateLimitError),
        (make_response(307, None, headers={"Location": "/x"}), WeclappRedirectError),
        (
            make_response(409, {"type": "https://api.weclapp.com/errors/persistence"}),
            WeclappAPIError,
        ),
    ],
    ids=["500", "503", "429", "307", "persistence"],
)
def test_writes_never_retry_http_failures(
    operation: Callable[[Weclapp], Any], response: requests.Response, error: type[Exception]
) -> None:
    h = harness(response, ok())
    with pytest.raises(error):
        operation(h.client)
    assert h.calls == 1


@pytest.mark.parametrize("operation", WRITE_OPS, ids=WRITE_IDS)
def test_writes_retry_when_the_request_never_left(operation: Callable[[Weclapp], Any]) -> None:
    h = harness(refused(), requests.exceptions.ConnectTimeout("t"), status(201, {"id": "9"}))
    operation(h.client)
    assert h.calls == 3


def test_unsent_write_exhaustion_reports_not_sent() -> None:
    h = harness(*[refused()] * 4)
    with pytest.raises(WeclappTransportError) as info:
        h.client.post("article", {})
    assert h.calls == 4
    assert info.value.request_sent is False
    assert info.value.outcome_unknown is False
    assert "read the entity back" not in str(info.value)


def test_write_429_starts_the_shared_cooldown_for_reads() -> None:
    h = harness(status(429), ok(), cooldown=5.0)
    with pytest.raises(WeclappRateLimitError):
        h.client.post("article", {})
    assert h.client.concurrency.snapshot().cooldown_remaining == pytest.approx(5.0)
    assert h.client.concurrency.target == 1
    h.client.get("article")
    assert h.clock.waits == [pytest.approx(5.0)]


def test_write_waits_for_an_active_cooldown() -> None:
    h = harness(status(429), status(201, {"id": "1"}), cooldown=5.0)
    with pytest.raises(WeclappRateLimitError):
        h.client.post("article", {})
    h.client.post("article", {})
    assert h.clock.waits == [pytest.approx(5.0)]
    assert h.client.concurrency.active == 0


# -------------------------------------------------------------- success body
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (make_response(204), {}),
        (make_response(200, None), {}),
        (make_response(200, {"a": 1}), {"a": 1}),
        (make_response(200, {"a": 1}, content_type="application/problem+json"), {"a": 1}),
        (untyped(b'{"a": 1}'), {"a": 1}),
        (
            make_response(200, "hello", content_type="text/plain; charset=utf-8"),
            {"content": "hello", "content_type": "text/plain; charset=utf-8"},
        ),
        (
            make_response(200, "a: 1", content_type="application/yaml"),
            {"content": "a: 1", "content_type": "application/yaml"},
        ),
        (untyped(b"\x00\x01"), {"content": b"\x00\x01", "content_type": ""}),
    ],
    ids=["204", "empty", "json", "problem+json", "untyped-json", "text", "yaml", "untyped-bin"],
)
def test_success_parsing(response: requests.Response, expected: Any) -> None:
    h = harness(response)
    assert h.client.request("GET", "x") == expected


@pytest.mark.parametrize(
    ("disposition", "filename"),
    [
        ('attachment; filename="doc.pdf"', "doc.pdf"),
        ("attachment; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf", "résumé.pdf"),
        (None, None),
    ],
)
def test_binary_download_keeps_bytes_and_filename(
    disposition: str | None, filename: str | None
) -> None:
    headers = {"Content-Disposition": disposition} if disposition else {}
    response = make_response(200, b"%PDF-1.7", content_type="application/pdf", headers=headers)
    h = harness(response)
    result = h.client.download("document", "9")
    assert result["content"] == b"%PDF-1.7"
    assert result["content_type"] == "application/pdf"
    assert result.get("filename") == filename


# ---------------------------------------------------------------------- stats
def test_stats_and_reset() -> None:
    h = harness(status(503), ok())
    h.client.get("article")
    stats = h.client.stats
    assert (stats.requests, stats.retries, stats.http_errors) == (2, 1, 1)
    assert stats.by_status == {503: 1, 200: 1}
    h.client.reset_stats()
    assert h.client.stats.requests == 0


# ------------------------------------------------------------------ get / count
def test_get_by_id_uses_id_eq_and_wraps_the_row() -> None:
    h = harness(ok({"result": [{"id": "7", "name": "x"}]}))
    params = {"properties": "id,name"}
    entity = h.client.get("article", "7", params)
    method, url, kwargs = h.call()
    assert (method, url) == ("GET", BASE + "article")
    assert kwargs["params"] == {"properties": "id,name", "id-eq": "7", "page": 1, "pageSize": 1}
    assert params == {"properties": "id,name"}
    assert isinstance(entity, WeclappEntity)
    assert entity.name == "x"


def test_get_by_id_not_found_raises_synthetic_404() -> None:
    h = harness(ok({"result": []}))
    with pytest.raises(WeclappNotFoundError) as info:
        h.client.get("article", "404")
    error = info.value
    assert error.status_code == 404
    assert error.is_not_found
    assert error.url == BASE + "article"
    assert error.response is not None
    assert error.response.status_code == 404
    assert error.detail is not None
    assert "404" in error.detail
    assert h.calls == 1


def test_get_by_id_with_weclapp_response() -> None:
    body = {
        "result": [{"id": "7", "customerId": "c1"}],
        "referencedEntities": {"party": [{"id": "c1", "name": "ACME"}]},
    }
    h = harness(ok(body))
    response = h.client.get("article", "7", return_weclapp_response=True)
    assert isinstance(response, WeclappResponse)
    assert isinstance(response.result, WeclappEntity)
    assert response.referenced_entities == {"party": {"c1": {"id": "c1", "name": "ACME"}}}
    assert response.raw_response == body


def test_get_list_page() -> None:
    h = harness(ok({"result": [{"id": "1"}, {"id": "2"}]}), ok({"result": [{"id": "3"}]}))
    rows = h.client.get("article", params={"page": 2})
    assert [row["id"] for row in rows] == ["1", "2"]
    response = h.client.get("article", return_weclapp_response=True)
    assert isinstance(response, WeclappResponse)
    assert [row["id"] for row in response.result] == ["3"]  # type: ignore[index, union-attr]


def test_count_strips_pagination_and_projection_params() -> None:
    h = harness(ok({"result": 42}))
    params = {
        "name-eq": "x",
        "page": 2,
        "pageSize": 5,
        "sort": "id",
        "orderBy": "name",
        "properties": "id",
        "additionalProperties": "a",
        "includeReferencedEntities": "b",
        "serializeNulls": True,
    }
    assert h.client.count("article", params) == 42
    method, url, kwargs = h.call()
    assert (method, url) == ("GET", BASE + "article/count")
    assert kwargs["params"] == {"name-eq": "x"}


@pytest.mark.parametrize("body", [{"result": "42"}, {"result": True}, ["x"]])
def test_count_rejects_non_integer_results(body: Any) -> None:
    with pytest.raises(TypeError):
        harness(ok(body)).client.count("article")


# ------------------------------------------------------------ unofficial reads
def test_query_request_shape_and_parsing() -> None:
    h = harness(ok({"result": [{"id": "1"}], "additionalProperties": {"x": [5]}}))
    result = h.client.query(
        "article",
        filter="id in [1]",
        properties=("id", "name"),
        include_referenced_entities=["unitId"],
        additional_properties=["x"],
        order_by=["-id"],
        page=2,
        page_size=50,
        offset=3,
        serialize_nulls=True,
    )
    method, url, kwargs = h.call()
    assert (method, url) == ("POST", BASE + "article/query")
    assert kwargs["json"] == {
        "filter": "id in [1]",
        "properties": ["id", "name"],
        "includeReferencedEntities": ["unitId"],
        "additionalProperties": ["x"],
        "orderBy": ["-id"],
        "page": 2,
        "pageSize": 50,
        "offset": 3,
        "serializeNulls": True,
    }
    assert isinstance(result, list)
    assert result[0]["x"] == 5


def test_query_minimal_body_and_weclapp_response() -> None:
    h = harness(ok({"result": []}))
    response = h.client.query("article", return_weclapp_response=True)
    assert h.call()[2]["json"] == {}
    assert isinstance(response, WeclappResponse)


@pytest.mark.parametrize(("filter_", "body"), [("id > 0", {"filter": "id > 0"}), (None, {})])
def test_query_count(filter_: str | None, body: dict[str, str]) -> None:
    h = harness(ok({"result": 3}))
    assert h.client.query_count("article", filter=filter_) == 3
    method, url, kwargs = h.call()
    assert (method, url, kwargs["json"]) == ("POST", BASE + "article/count", body)


def test_batch_query_shape_and_index_ordering() -> None:
    flat = [
        1,
        7,
        {"status": 200, "body": {"result": 5}},
        0,
        "meta?",
        {"status": 400, "body": {"title": "bad"}},
    ]
    h = harness(ok(flat))
    results = h.client.batch_query(["/article?pageSize=1", "party/count"])
    method, url, kwargs = h.call()
    assert (method, url) == ("POST", BASE + "batch/query")
    assert kwargs["json"] == {"requests": ["article?pageSize=1", "party/count"]}
    assert results == [
        BatchResult(index=0, status=400, body={"title": "bad"}, meta=0),
        BatchResult(index=1, status=200, body={"result": 5}, meta=7),
    ]
    assert [r.ok for r in results] == [False, True]


def test_batch_query_limits_and_validation() -> None:
    h = harness()
    assert h.client.batch_query([]) == []
    with pytest.raises(ValueError, match="500"):
        h.client.batch_query(["article"] * 501)
    with pytest.raises(ValueError, match="endpoint"):
        h.client.batch_query(["https://evil.example/x"])
    assert h.calls == 0


def test_batch_query_accepts_exactly_500() -> None:
    h = harness(ok([]))
    assert h.client.batch_query(["article"] * 500) == []
    assert len(h.call()[2]["json"]["requests"]) == 500


@pytest.mark.parametrize("body", [[0, 0], [0, 0, "not a dict"], {"result": []}])
def test_batch_query_rejects_malformed_responses(body: Any) -> None:
    with pytest.raises(TypeError):
        harness(ok(body)).client.batch_query(["article"])


@pytest.mark.parametrize(("hidden", "params"), [(False, None), (True, {"includeHidden": "true"})])
def test_openapi_request_shape(hidden: bool, params: dict[str, str] | None) -> None:
    h = harness(make_response(200, "openapi: 3.0.1\n", content_type="application/yaml"))
    assert h.client.openapi(include_hidden=hidden) == "openapi: 3.0.1\n"
    method, url, kwargs = h.call()
    assert (method, url) == ("GET", BASE + "meta/openapi.yaml")
    assert kwargs.get("params") == params


def test_openapi_decodes_binary_content() -> None:
    h = harness(make_response(200, b"openapi: 3", content_type="application/octet-stream"))
    assert h.client.openapi() == "openapi: 3"


# ---------------------------------------------------------------------- writes
def test_put_defaults_ignore_missing_properties() -> None:
    h = harness(ok({}), ok({}))
    h.client.put("article", "5", {"name": "n"})
    method, url, kwargs = h.call()
    assert (method, url) == ("PUT", BASE + "article/id/5")
    assert kwargs["params"] == {"ignoreMissingProperties": True}
    assert kwargs["json"] == {"name": "n"}
    h.client.put("article", "5", {}, {"ignoreMissingProperties": False, "dryRun": True})
    assert h.call()[2]["params"] == {"ignoreMissingProperties": False, "dryRun": True}


def test_delete_returns_empty_dict_on_204() -> None:
    h = harness(make_response(204))
    assert h.client.delete("article", "5") == {}
    assert h.call()[:2] == ("DELETE", BASE + "article/id/5")


@pytest.mark.parametrize(
    ("kwargs", "content_type"),
    [
        ({"filename": "scan.PDF"}, "application/pdf"),
        ({"filename": "photo.jpeg"}, "image/jpeg"),
        ({"filename": "unknown.xyz"}, "application/octet-stream"),
        ({}, "application/octet-stream"),
        ({"content_type": "text/csv"}, "text/csv"),
    ],
)
def test_upload_content_type(kwargs: dict[str, str], content_type: str) -> None:
    h = harness(ok({}))
    h.client.upload("document", b"data", action="upload", params={"name": "x"}, **kwargs)
    method, url, sent = h.call()
    assert (method, url) == ("POST", BASE + "document/upload")
    assert sent["headers"]["Content-Type"] == content_type
    assert sent["data"] == b"data"
    assert sent["params"] == {"name": "x"}


def test_upload_explicit_content_type_wins_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    h = harness(ok({}))
    with caplog.at_level(logging.WARNING, logger="weclappy"):
        h.client.upload("document", b"x", "1", "upload", content_type="image/png", filename="a.pdf")
    assert h.call()[2]["headers"]["Content-Type"] == "image/png"
    assert h.call()[1] == BASE + "document/id/1/upload"
    assert "Content type mismatch" in caplog.text


@pytest.mark.parametrize(
    ("args", "suffix"),
    [
        (("document", "9"), "document/id/9/download"),
        (("document", "9", "preview"), "document/id/9/preview"),
        (("document", None, "list"), "document/list"),
        (("document",), "document"),
    ],
)
def test_download_paths(args: tuple[Any, ...], suffix: str) -> None:
    h = harness(make_response(200, b"x", content_type="application/pdf"))
    h.client.download(*args)
    assert h.call()[:2] == ("GET", BASE + suffix)


def test_call_method_validation_and_shapes() -> None:
    h = harness(ok({}), ok({}))
    with pytest.raises(ValueError, match="GET and POST"):
        h.client.call_method("salesOrder", "x", method="DELETE")  # type: ignore[arg-type]
    h.client.call_method("salesOrder", "createPdf", "3", method="post", data={"a": 1})  # type: ignore[arg-type]
    method, url, kwargs = h.call()
    assert (method, url, kwargs["json"]) == ("POST", BASE + "salesOrder/id/3/createPdf", {"a": 1})
    h.client.call_method("salesOrder", "info", params={"q": "1"})
    method, url, kwargs = h.call()
    assert (method, url, kwargs["params"]) == ("GET", BASE + "salesOrder/info", {"q": "1"})


# ------------------------------------------------------- attribute definitions
DEFINITION_PATH = "customAttributeDefinition"


def definition_tenant() -> FakeTenant:
    return FakeTenant(
        {
            "article": [
                {
                    "id": "1",
                    "customAttributes": [{"attributeDefinitionId": "100", "stringValue": "red"}],
                }
            ],
            DEFINITION_PATH: [
                {"id": "100", "attributeKey": "color", "attributeType": "STRING", "readOnly": False}
            ],
        }
    )


def definition_client(tenant: FakeTenant, **interceptor: Any) -> Weclapp:
    client = Weclapp(
        BASE,
        "k",
        concurrency=ConcurrencyController(ConcurrencySettings(min_rate_limit_cooldown=0)),
        retry_policy=RetryPolicy(jitter=False, rate_limit_backoff=0),
    )
    client.session.request = FakeSession(tenant, **interceptor)  # type: ignore[method-assign]
    return client


def test_attribute_definitions_load_once_across_threads() -> None:
    tenant = definition_tenant()
    loading, release, second_listed = threading.Event(), threading.Event(), threading.Event()
    article_calls = 0
    lock = threading.Lock()

    def interceptor(method: str, path: str, query: dict[str, str], body: Any) -> None:
        nonlocal article_calls
        if path == DEFINITION_PATH:
            loading.set()
            release.wait(timeout=2)
        elif path == "article":
            with lock:
                article_calls += 1
                if article_calls == 2:
                    second_listed.set()

    client = definition_client(tenant, interceptor=interceptor)
    results: list[Any] = []
    first = threading.Thread(target=lambda: results.append(client.get("article")))
    second = threading.Thread(target=lambda: results.append(client.get("article")))
    first.start()
    assert loading.wait(timeout=2)
    second.start()
    assert second_listed.wait(timeout=2)
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert len(tenant.hits_for("GET", DEFINITION_PATH)) == 1
    assert [rows[0]["color"] for rows in results] == ["red", "red"]


def test_rows_without_custom_attributes_never_load_definitions() -> None:
    tenant = FakeTenant({"article": [{"id": "1"}]})
    client = definition_client(tenant)
    client.get("article")
    assert tenant.hits_for("GET", DEFINITION_PATH) == []


def test_permanent_403_caches_empty_definitions_with_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant = definition_tenant()
    tenant.script("GET", DEFINITION_PATH, Reply(403, {"type": "/errors/forbidden"}))
    client = definition_client(tenant)
    with caplog.at_level(logging.WARNING, logger="weclappy"):
        first = client.get("article")
        client.get("article")
    assert len(tenant.hits_for("GET", DEFINITION_PATH)) == 1
    assert caplog.text.count("customAttributeDefinition is not readable") == 1
    assert "color" not in first[0]
    assert first[0]["customAttributes"][0]["stringValue"] == "red"


def test_transient_definition_failure_propagates_and_is_not_cached() -> None:
    tenant = definition_tenant()
    tenant.script("GET", DEFINITION_PATH, *[Reply(503, {})] * 4)
    client = definition_client(tenant)
    with pytest.raises(WeclappAPIError) as info:
        client.get("article")
    assert info.value.status_code == 503
    assert client.get("article")[0]["color"] == "red"
    assert len(tenant.hits_for("GET", DEFINITION_PATH)) == 5


def test_refresh_attribute_definitions_reloads() -> None:
    tenant = definition_tenant()
    client = definition_client(tenant)
    client.get("article")
    tenant.tables[DEFINITION_PATH][0]["attributeKey"] = "colour"
    refreshed = client.refresh_attribute_definitions()
    assert refreshed["100"]["attributeKey"] == "colour"
    assert client.get("article")[0]["colour"] == "red"
    assert len(tenant.hits_for("GET", DEFINITION_PATH)) == 2


def test_json_helper_roundtrip() -> None:
    """Guard the helper itself: make_response bodies are real JSON."""
    response = make_response(200, {"a": [1, 2]})
    assert json.loads(response.content) == {"a": [1, 2]}
    assert response.headers["Content-Type"] == "application/json"
