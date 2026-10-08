"""In-process fake weclapp API for weclappy tests (stdlib + requests only).

Three layers, usable independently:

* :class:`FakeTenant` - pure request routing over in-memory tables. It
  emulates list reads (``page``/``pageSize``/``sort``/``id-eq``/``id-in``/
  ``id-gt``/``properties``/``additionalProperties``/
  ``includeReferencedEntities``), ``GET {entity}/count``, the unofficial
  ``POST {entity}/query``, ``POST {entity}/count`` and ``POST batch/query``,
  ``GET meta/openapi.yaml`` and writes. It records every request as a
  :class:`Hit` and lets tests script responses per ``(method, path)``.
* :class:`FakeWeclappServer` - a real HTTP server
  (:class:`http.server.ThreadingHTTPServer` in a daemon thread on
  ``127.0.0.1``) in front of a tenant, with a tenant-wide concurrency limit
  that queues and tags responses (``X-Weclapp-Wait-Ms``,
  ``X-Weclapp-Wait-Reason: concurrency``) and rejects with 429 above a second
  threshold, plus scripted socket closes and hangs.
* :class:`FakeSession` - a callable drop-in for ``Session.request`` that
  routes to a tenant without sockets, for fast unit tests.

:class:`FakeClock` is a monotonic clock for :class:`ConcurrencyController`
whose condition waits advance the clock instead of sleeping.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

API_ROOT = "/webapp/api/v2/"
OPENAPI_YAML = "openapi: 3.0.1\ninfo:\n  title: fake weclapp\npaths: {}\n"
OPENAPI_HIDDEN_YAML = OPENAPI_YAML + "x-hidden:\n  - /article/query\n  - /batch/query\n"
BATCH_LIMIT = 500
_FILTER_GT = re.compile(r"^\s*id\s*>\s*'?(\d+)'?\s*$")
_FILTER_IN = re.compile(r"^\s*id\s+in\s*\[(.*)\]\s*$")
_NON_FILTER_KEYS = frozenset(
    {
        "page",
        "pageSize",
        "sort",
        "orderBy",
        "properties",
        "additionalProperties",
        "includeReferencedEntities",
        "serializeNulls",
        "ignoreMissingProperties",
        "includeHidden",
    }
)


# ------------------------------------------------------------------ replies
@dataclass(frozen=True)
class Reply:
    """A scripted or computed HTTP answer.

    ``body`` is JSON-encoded for dicts/lists, sent as text for ``str`` and raw
    for ``bytes``; ``None`` sends an empty body.
    """

    status: int = 200
    body: Any = None
    headers: Mapping[str, str] = field(default_factory=dict)
    content_type: str | None = None
    delay: float = 0.0

    def encode(self) -> tuple[bytes, str | None]:
        if self.body is None or self.status == 204:
            return b"", self.content_type
        if isinstance(self.body, bytes):
            return self.body, self.content_type or "application/octet-stream"
        if isinstance(self.body, str):
            return self.body.encode("utf-8"), self.content_type or "text/plain; charset=utf-8"
        return json.dumps(self.body).encode("utf-8"), self.content_type or "application/json"


class CloseSocket:
    """Read the request, then close the connection without answering."""


class Hang:
    """Accept the request and never answer (until the server shuts down)."""


CLOSE = CloseSocket()
HANG = Hang()
type Outcome = Reply | CloseSocket | Hang


def problem(status: int, type_suffix: str, **extra: Any) -> Reply:
    """A weclapp problem document reply."""
    return Reply(status, {"type": f"https://api.weclapp.com/errors/{type_suffix}", **extra})


@dataclass(frozen=True)
class Hit:
    """One request received by the fake API."""

    method: str
    path: str
    query: dict[str, str]
    body: Any
    headers: dict[str, str]


def make_rows(count: int, start: int = 1) -> list[dict[str, Any]]:
    """``count`` plain rows with numeric string ids ``start..start+count-1``."""
    return [
        {"id": str(i), "name": f"Record {i}", "customerId": f"c{i % 5}", "version": "0"}
        for i in range(start, start + count)
    ]


# ------------------------------------------------------------------- tenant
class FakeTenant:
    """In-memory weclapp tenant: routing, filtering, scripting and hit log."""

    def __init__(self, tables: Mapping[str, Iterable[dict[str, Any]]] | None = None) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in (tables or {}).items()
        }
        self.hits: list[Hit] = []
        self._scripts: dict[tuple[str, str], deque[Outcome]] = {}
        self._lock = threading.Lock()
        self._next_id = 1_000_000

    # scripting / inspection
    def script(self, method: str, path: str, *outcomes: Outcome) -> None:
        """Queue outcomes for the next requests to ``method path`` (FIFO)."""
        with self._lock:
            self._scripts.setdefault((method.upper(), path), deque()).extend(outcomes)

    def hits_for(self, method: str, path: str) -> list[Hit]:
        with self._lock:
            return [h for h in self.hits if h.method == method.upper() and h.path == path]

    def record(self, hit: Hit) -> None:
        with self._lock:
            self.hits.append(hit)

    def handle(
        self,
        method: str,
        path: str,
        query: Mapping[str, str] | None = None,
        body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Outcome:
        """Record the request and produce its outcome."""
        self.record(Hit(method.upper(), path, dict(query or {}), body, dict(headers or {})))
        return self.dispatch(method, path, query or {}, body)

    def dispatch(self, method: str, path: str, query: Mapping[str, str], body: Any) -> Outcome:
        """Produce the outcome without recording (scripts first, then routes)."""
        method = method.upper()
        with self._lock:
            queue = self._scripts.get((method, path))
            if queue:
                return queue.popleft()
        return self._route(method, path, dict(query), body)

    # routing
    def _route(self, method: str, path: str, query: dict[str, str], body: Any) -> Reply:
        if path == "meta/openapi.yaml" and method == "GET":
            hidden = query.get("includeHidden") == "true"
            text = OPENAPI_HIDDEN_YAML if hidden else OPENAPI_YAML
            return Reply(200, text, content_type="application/yaml")
        if path == "batch/query" and method == "POST":
            return self._batch(body)
        parts = path.split("/")
        entity = parts[0]
        if len(parts) == 1:
            if method == "GET":
                return self._list(entity, query)
            if method == "POST":
                return self._create(entity, body)
        elif len(parts) == 2 and parts[1] == "count":
            if method == "GET":
                return Reply(200, {"result": len(self._filtered(entity, query))})
            if method == "POST":
                return Reply(200, {"result": len(self._body_filtered(entity, body))})
        elif len(parts) == 2 and parts[1] == "query" and method == "POST":
            return self._body_query(entity, body)
        elif len(parts) == 3 and parts[1] == "id":
            return self._by_id(method, entity, parts[2], body)
        return problem(404, "not_found", title=f"no route for {method} {path}")

    def _table(self, entity: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.tables.get(entity, []))

    def _filtered(self, entity: str, query: Mapping[str, str]) -> list[dict[str, Any]]:
        rows = self._table(entity)
        for key, value in query.items():
            if key in _NON_FILTER_KEYS:
                continue
            if key == "id-eq":
                rows = [r for r in rows if r.get("id") == value]
            elif key == "id-in":
                wanted = {str(v) for v in json.loads(value)}
                rows = [r for r in rows if r.get("id") in wanted]
            elif key == "id-gt":
                rows = [r for r in rows if int(r["id"]) > int(value)]
            elif key.endswith("-eq"):
                name = key[: -len("-eq")]
                rows = [r for r in rows if str(r.get(name)) == value]
        sort = query.get("sort")
        if sort in ("id", "-id"):
            rows.sort(key=lambda r: int(r["id"]), reverse=sort == "-id")
        return rows

    def _body_filtered(self, entity: str, body: Any) -> list[dict[str, Any]]:
        rows = self._table(entity)
        expression = body.get("filter") if isinstance(body, dict) else None
        if not expression:
            return rows
        if match := _FILTER_GT.match(expression):
            return [r for r in rows if int(r["id"]) > int(match.group(1))]
        if match := _FILTER_IN.match(expression):
            wanted = {item.strip().strip("'\"") for item in match.group(1).split(",") if item}
            return [r for r in rows if r["id"] in wanted]
        raise ValueError(f"fake tenant cannot evaluate filter {expression!r}")

    def _page(
        self,
        rows: list[dict[str, Any]],
        *,
        page: int,
        page_size: int,
        properties: list[str] | None,
        additional: list[str],
        referenced: list[str],
    ) -> dict[str, Any]:
        window = rows[(page - 1) * page_size : page * page_size]
        payload: dict[str, Any] = {
            "result": [
                {k: v for k, v in row.items() if properties is None or k in properties}
                for row in window
            ]
        }
        if additional:
            payload["additionalProperties"] = {
                name: [f"{name}:{row['id']}" for row in window] for name in additional
            }
        if referenced:
            parties = {
                row[name]: {"id": row[name], "name": f"Party {row[name]}"}
                for name in referenced
                for row in window
                if row.get(name)
            }
            payload["referencedEntities"] = {"party": list(parties.values())}
        return payload

    def _list(self, entity: str, query: Mapping[str, str]) -> Reply:
        rows = self._filtered(entity, query)
        return Reply(
            200,
            self._page(
                rows,
                page=int(query.get("page", 1)),
                page_size=int(query.get("pageSize", 100)),
                properties=_csv(query.get("properties")),
                additional=_csv(query.get("additionalProperties")) or [],
                referenced=_csv(query.get("includeReferencedEntities")) or [],
            ),
        )

    def _body_query(self, entity: str, body: Any) -> Reply:
        body = body if isinstance(body, dict) else {}
        try:
            rows = self._body_filtered(entity, body)
        except ValueError as exc:
            return problem(400, "validation", title=str(exc))
        order = body.get("orderBy") or ["id"]
        if order[0] in ("id", "-id"):
            rows.sort(key=lambda r: int(r["id"]), reverse=order[0] == "-id")
        return Reply(
            200,
            self._page(
                rows,
                page=int(body.get("page", 1)),
                page_size=int(body.get("pageSize", 100)),
                properties=body.get("properties"),
                additional=body.get("additionalProperties") or [],
                referenced=body.get("includeReferencedEntities") or [],
            ),
        )

    def _batch(self, body: Any) -> Reply:
        items = body.get("requests") if isinstance(body, dict) else None
        if not isinstance(items, list):
            return problem(400, "validation", title="requests missing")
        if len(items) > BATCH_LIMIT:
            return problem(400, "validation", title="too many requests")
        flat: list[Any] = []
        # Deliberately not in request order: weclapp does not guarantee it.
        for index in reversed(range(len(items))):
            split = urlsplit(str(items[index]))
            query = {k: v[-1] for k, v in parse_qs(split.query, keep_blank_values=True).items()}
            outcome = self._route("GET", split.path, query, None)
            assert isinstance(outcome, Reply)
            flat.extend([index, 0, {"status": outcome.status, "body": outcome.body}])
        return Reply(200, flat)

    def _create(self, entity: str, body: Any) -> Reply:
        with self._lock:
            self._next_id += 1
            row = {**(body if isinstance(body, dict) else {}), "id": str(self._next_id)}
            self.tables.setdefault(entity, []).append(row)
        return Reply(201, row)

    def _by_id(self, method: str, entity: str, entity_id: str, body: Any) -> Reply:
        with self._lock:
            rows = self.tables.get(entity, [])
            row = next((r for r in rows if r.get("id") == entity_id), None)
            if row is None:
                return problem(404, "not_found", title=f"{entity} {entity_id} not found")
            if method == "GET":
                return Reply(200, dict(row))
            if method == "PUT":
                row.update(body if isinstance(body, dict) else {})
                return Reply(200, dict(row))
            if method == "DELETE":
                rows.remove(row)
                return Reply(204)
        return problem(405, "method_not_allowed")


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


# ------------------------------------------------------------ HTTP server
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 10  # idle keep-alive connections end on their own
    server: _Server

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        split = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(split.query, keep_blank_values=True).items()}
        body: Any = raw
        if raw and "json" in (self.headers.get("Content-Type") or ""):
            body = json.loads(raw)
        elif not raw:
            body = None
        path = split.path[len(API_ROOT) :] if split.path.startswith(API_ROOT) else split.path
        self.server.fake.serve(self, self.command, path, query, body, dict(self.headers.items()))

    def send_reply(self, reply: Reply, extra_headers: Mapping[str, str]) -> None:
        if reply.delay:
            time.sleep(reply.delay)
        payload, content_type = reply.encode()
        self.send_response(reply.status)
        headers = {**extra_headers, **reply.headers}
        if content_type and payload:
            headers.setdefault("Content-Type", content_type)
        headers["Content-Length"] = str(len(payload))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if payload:
            self.wfile.write(payload)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    fake: FakeWeclappServer


class FakeWeclappServer:
    """A real HTTP fake of the weclapp API on ``127.0.0.1:<ephemeral>``.

    Args:
        tenant: Data and scripts; a fresh empty tenant by default.
        concurrency_limit: Requests processed at once. A request arriving
            while ``concurrency_limit`` others are in flight is queued until a
            slot frees, and its response carries ``X-Weclapp-Wait-Ms`` and
            ``X-Weclapp-Wait-Reason: concurrency``.
        reject_above: Requests arriving while this many are already in
            flight are answered with 429 immediately.
        processing_delay: Simulated server work per admitted request.
    """

    def __init__(
        self,
        tenant: FakeTenant | None = None,
        *,
        concurrency_limit: int | None = None,
        reject_above: int | None = None,
        processing_delay: float = 0.0,
    ) -> None:
        self.tenant = tenant or FakeTenant()
        self.concurrency_limit = concurrency_limit
        self.reject_above = reject_above
        self.processing_delay = processing_delay
        self.max_in_flight = 0
        self.queued = 0
        self.rejected = 0
        self._in_flight = 0
        self._state = threading.Lock()
        self._slots = threading.BoundedSemaphore(concurrency_limit) if concurrency_limit else None
        self._release_hangs = threading.Event()
        self._httpd = _Server(("127.0.0.1", 0), _Handler)
        self._httpd.fake = self
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="fake-weclapp",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}{API_ROOT}"

    @property
    def hits(self) -> list[Hit]:
        return self.tenant.hits

    def start(self) -> FakeWeclappServer:
        self._thread.start()
        return self

    def shutdown(self) -> None:
        self._release_hangs.set()
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> FakeWeclappServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.shutdown()

    def serve(
        self,
        handler: _Handler,
        method: str,
        path: str,
        query: dict[str, str],
        body: Any,
        headers: dict[str, str],
    ) -> None:
        self.tenant.record(Hit(method, path, query, body, headers))
        with self._state:
            self._in_flight += 1
            arrived_with = self._in_flight
            self.max_in_flight = max(self.max_in_flight, arrived_with)
        holding_slot = False
        try:
            if self.reject_above is not None and arrived_with > self.reject_above:
                with self._state:
                    self.rejected += 1
                handler.send_reply(
                    problem(429, "too_many_requests"),
                    {"X-Weclapp-Wait-Ms": "0", "X-Weclapp-Wait-Reason": "concurrency"},
                )
                return
            extra: dict[str, str] = {}
            if self._slots is not None:
                started = time.monotonic()
                holding_slot = self._slots.acquire(timeout=5)
                if not holding_slot:
                    handler.send_reply(problem(429, "too_many_requests"), {})
                    return
                waited_ms = (time.monotonic() - started) * 1000
                if self.concurrency_limit is not None and arrived_with > self.concurrency_limit:
                    with self._state:
                        self.queued += 1
                    extra = {
                        "X-Weclapp-Wait-Ms": str(int(waited_ms)),
                        "X-Weclapp-Wait-Reason": "concurrency",
                    }
            if self.processing_delay:
                time.sleep(self.processing_delay)
            outcome = self.tenant.dispatch(method, path, query, body)
            if isinstance(outcome, CloseSocket):
                handler.close_connection = True
                return
            if isinstance(outcome, Hang):
                self._release_hangs.wait(timeout=30)
                handler.close_connection = True
                return
            handler.send_reply(outcome, extra)
        finally:
            if holding_slot and self._slots is not None:
                self._slots.release()
            with self._state:
                self._in_flight -= 1


def closed_port() -> int:
    """A localhost port with nothing listening (connection refused)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ------------------------------------------------------- socket-free layer
def make_response(
    status: int = 200,
    body: Any = None,
    *,
    headers: Mapping[str, str] | None = None,
    content_type: str | None = None,
    url: str = "https://acme.weclapp.com/webapp/api/v2/",
) -> requests.Response:
    """A real :class:`requests.Response` with the given status/body/headers."""
    payload, inferred = Reply(status, body, content_type=content_type).encode()
    response = requests.Response()
    response.status_code = status
    response.url = url
    response._content = payload
    response.encoding = "utf-8"
    if inferred and payload:
        response.headers["Content-Type"] = inferred
    response.headers.update(headers or {})
    return response


type Interceptor = Callable[[str, str, dict[str, str], Any], Outcome | None]


class FakeSession:
    """Callable replacement for ``Session.request`` backed by a :class:`FakeTenant`.

    ``interceptor(method, path, query, json_body)`` may return an outcome to
    override routing for one call (it can also block to stage interleavings).
    Every call is recorded in ``tenant.hits``.
    """

    def __init__(self, tenant: FakeTenant, interceptor: Interceptor | None = None) -> None:
        self.tenant = tenant
        self.interceptor = interceptor

    def __call__(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        split = urlsplit(url)
        path = split.path[len(API_ROOT) :] if split.path.startswith(API_ROOT) else split.path
        query = {
            key: _query_value(value)
            for key, value in (kwargs.get("params") or {}).items()
            if value is not None  # requests drops None-valued params
        }
        body = kwargs.get("json")
        if body is None:
            body = kwargs.get("data")
        headers = dict(kwargs.get("headers") or {})
        outcome: Outcome | None = None
        if self.interceptor is not None:
            outcome = self.interceptor(method, path, query, body)
        if outcome is None:
            outcome = self.tenant.handle(method, path, query, body, headers)
        else:
            self.tenant.record(Hit(method, path, query, body, headers))
        if isinstance(outcome, CloseSocket):
            raise requests.exceptions.ConnectionError("fake: connection closed")
        if isinstance(outcome, Hang):
            raise requests.exceptions.ReadTimeout("fake: read timed out")
        return make_response(
            outcome.status,
            outcome.body,
            headers=outcome.headers,
            content_type=outcome.content_type,
            url=url,
        )


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# --------------------------------------------------------------- fake clock
class FakeClock:
    """Monotonic clock for :class:`~weclappy.ConcurrencyController` tests.

    :meth:`attach` replaces the controller's ``Condition.wait`` so a timed
    wait advances this clock instantly and is recorded in :attr:`waits`.
    An untimed wait would block forever in a single-threaded test and fails
    loudly instead.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def attach(self, controller: Any) -> None:
        def fake_wait(timeout: float | None = None) -> bool:
            if timeout is None:
                raise AssertionError("untimed Condition.wait in a single-threaded test")
            self.waits.append(timeout)
            self.now += timeout
            return False

        controller._condition.wait = fake_wait
