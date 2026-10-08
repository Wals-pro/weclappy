"""The :class:`Weclapp` client."""

from __future__ import annotations

import json as json_module
import logging
import math
import re
import threading
import time
import warnings
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import nullcontext
from dataclasses import dataclass, field
from email.message import Message
from functools import partial
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version
from typing import Any, Literal, overload
from urllib.parse import quote, urlencode, urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter

from .concurrency import ConcurrencyController, ConcurrencySettings, Signal
from .entity import JsonDict, WeclappEntity, WeclappResponse
from .errors import (
    WeclappAPIError,
    WeclappNotFoundError,
    WeclappPaginationError,
    WeclappTransportError,
)
from .metrics import ClientStats, RequestMetrics, StatsSnapshot
from .mime import infer_content_type
from .retry import (
    RetryDecision,
    RetryPolicy,
    RetryState,
    TransportOutcome,
    classify_transport_error,
    decide_for_exception,
    decide_for_response,
    rate_limit_cooldown,
)

__all__ = [
    "DEFAULT_API_REQUEST_TIMEOUT_MS",
    "DEFAULT_ID_CHUNK_SIZE",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_MAX_URL_LENGTH",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_WAIT_TIMEOUT_MS",
    "SLOW_REQUEST_THRESHOLD_MS",
    "BatchResult",
    "OutgoingRequest",
    "Weclapp",
]

logger = logging.getLogger("weclappy")

try:
    __version__ = _package_version("weclappy")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0"

DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_CONCURRENCY = 10
DEFAULT_REQUEST_TIMEOUT: float = 120.0
"""Client-side timeout in seconds. weclapp queues requests for up to ~30 s."""
DEFAULT_WAIT_TIMEOUT_MS = 30_000
"""Default ``X-Weclapp-Wait-Timeout-Ms``: maximum server-side queue wait."""
DEFAULT_API_REQUEST_TIMEOUT_MS = 110_000
"""Default ``X-Weclapp-Request-Timeout-Ms``; kept below the client timeout so the
server answers with a definitive ``request_timeout`` problem instead of the client
giving up first."""
SLOW_REQUEST_THRESHOLD_MS = 2000
MAX_ERROR_MESSAGE_BODY_CHARS = 4000
DEFAULT_ID_CHUNK_SIZE = 500
"""``id-in`` chunk size. Measured on the weclapp sandbox: 640 ids fit the ~8.9 KB
URL limit of the Akamai edge in front of weclapp; 500 leaves headroom."""
DEFAULT_MAX_URL_LENGTH = 8000
"""Conservative ceiling for request URLs; the edge rejects ~8.9 KB with HTTP 400."""
BATCH_QUERY_MAX_REQUESTS = 500

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_READ_POST_SUFFIXES = ("/query", "/count")
_PAGINATION_KEYS = ("page", "pageSize")
_PROJECTION_KEYS = (
    "sort",
    "orderBy",
    "properties",
    "additionalProperties",
    "includeReferencedEntities",
    "serializeNulls",
)
_TEXTUAL_APPLICATION_TYPES = frozenset(
    {
        "application/javascript",
        "application/xml",
        "application/xhtml+xml",
        "application/x-www-form-urlencoded",
        "application/yaml",
        "application/x-yaml",
    }
)
_API_ROOT = re.compile(r"/webapp/api/v\d+/?$")
_CORRELATION_HEADERS = ("X-Correlation-ID", "X-Correlation-Id", "X-Request-ID", "X-Request-Id")

type Timeout = float | tuple[float, float]
type ThreadedMode = bool | Literal["auto"]
type Strategy = Literal["pages", "ids"]
type BeforeRequestHook = Callable[["OutgoingRequest"], None]
type OnResponseHook = Callable[[RequestMetrics], None]


@dataclass(slots=True)
class OutgoingRequest:
    """What the ``before_request`` hook sees for every physical attempt.

    ``headers`` and ``params`` are the mutable per-request values; changing
    them changes the request. The API key lives in the session headers and is
    not part of this object.
    """

    method: str
    url: str
    path: str
    attempt: int
    headers: dict[str, str]
    params: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class BatchResult:
    """One entry of a ``POST batch/query`` response (unofficial endpoint).

    Attributes:
        index: Position of the originating request in the submitted list.
        status: HTTP status weclapp reports for that sub-request.
        body: Parsed JSON body of the sub-request.
        meta: Undocumented integer weclapp returns next to each entry.
    """

    index: int
    status: int
    body: Any
    meta: int

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class _WeclappSession(requests.Session):
    """Session that never forwards ``AuthenticationToken`` to another origin.

    weclappy never follows redirects, so this cannot trigger in normal
    operation. It is kept as defence in depth for callers that use the session
    directly.
    """

    def rebuild_auth(self, prepared_request: Any, response: Any) -> None:
        super().rebuild_auth(prepared_request, response)  # type: ignore[no-untyped-call]
        previous = urlsplit(response.request.url)
        current = urlsplit(prepared_request.url)
        if (previous.scheme.lower(), previous.netloc.lower()) != (
            current.scheme.lower(),
            current.netloc.lower(),
        ):
            prepared_request.headers.pop("AuthenticationToken", None)


@dataclass(slots=True)
class _Collector:
    """Accumulates pages of a list read in page order."""

    results: list[JsonDict] = field(default_factory=list)
    additional_properties: dict[str, list[Any]] = field(default_factory=dict)
    referenced_entities: dict[str, list[JsonDict]] = field(default_factory=dict)
    seen_ids: set[Any] = field(default_factory=set)


class Weclapp:
    """Client for the weclapp REST API.

    Args:
        base_url: Absolute API root, e.g. ``https://acme.weclapp.com/webapp/api/v2/``.
        api_key: weclapp API token; sent as ``AuthenticationToken``.
        timeout: Client-side timeout in seconds, or a ``(connect, read)`` tuple.
        max_retries: Retries for 5xx and transport failures on reads (and for
            writes that provably never left the client).
        backoff_factor: Base of the exponential backoff for those retries.
        rate_limit_retries: Retries after 429 on reads.
        rate_limit_backoff: Base delay after a 429 (doubles per attempt).
        problem_retries: Extra retries for weclapp's transient problem types.
        max_backoff: Cap for every retry delay including ``Retry-After``.
        retry_policy: A complete :class:`~weclappy.retry.RetryPolicy`; overrides
            the individual retry arguments when given.
        wait_timeout_ms: ``X-Weclapp-Wait-Timeout-Ms`` default header; ``None`` omits it.
        request_timeout_ms: ``X-Weclapp-Request-Timeout-Ms`` default header;
            ``None`` omits it. Lowered automatically for per-request timeouts.
        max_concurrency: Hard ceiling for concurrent reads.
        concurrency: A shared :class:`~weclappy.concurrency.ConcurrencyController`.
            Pass the same instance to every client of one tenant; overrides
            ``max_concurrency``.
        session: A pre-configured :class:`requests.Session`. weclappy sets its
            default headers on it but mounts no adapter; the session's own
            adapters must not retry (``max_retries=0``).
        before_request: Hook called with an :class:`OutgoingRequest` before
            every physical attempt.
        on_response: Hook called with :class:`~weclappy.metrics.RequestMetrics`
            after every physical attempt, including failed ones.
        user_agent: ``User-Agent`` header; defaults to ``weclappy/<version>``.
        pool_connections: Connection pools kept by the default adapter.
        pool_maxsize: Connections per pool kept by the default adapter.
        slow_threshold_ms: Successful requests at or above this duration log as slow.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: Timeout = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = 3,
        backoff_factor: float = 0.3,
        rate_limit_retries: int = 5,
        rate_limit_backoff: float = 2.0,
        problem_retries: int = 1,
        max_backoff: float = 60.0,
        retry_policy: RetryPolicy | None = None,
        wait_timeout_ms: int | None = DEFAULT_WAIT_TIMEOUT_MS,
        request_timeout_ms: int | None = DEFAULT_API_REQUEST_TIMEOUT_MS,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        concurrency: ConcurrencyController | None = None,
        session: requests.Session | None = None,
        before_request: BeforeRequestHook | None = None,
        on_response: OnResponseHook | None = None,
        user_agent: str | None = None,
        pool_connections: int = 100,
        pool_maxsize: int = 100,
        slow_threshold_ms: float = SLOW_REQUEST_THRESHOLD_MS,
    ) -> None:
        if not isinstance(base_url, str):
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        parsed_base = urlsplit(base_url)
        if parsed_base.scheme.lower() not in {"http", "https"} or not parsed_base.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed_base.query or parsed_base.fragment:
            raise ValueError("base_url must not contain a query string or fragment")
        if not _API_ROOT.search(parsed_base.path):
            raise ValueError(
                "base_url must be the API root, e.g. https://acme.weclapp.com/webapp/api/v2/ "
                "(a bare tenant host answers every request with a redirect)"
            )
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a non-empty string")
        self.timeout = _validate_timeout(timeout)
        for header_name, header_value in (
            ("wait_timeout_ms", wait_timeout_ms),
            ("request_timeout_ms", request_timeout_ms),
        ):
            if header_value is not None and (
                isinstance(header_value, bool)
                or not isinstance(header_value, int)
                or header_value <= 0
            ):
                raise ValueError(f"{header_name} must be a positive integer or None")
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise ValueError("max_concurrency must be a positive integer")

        self.base_url = base_url.rstrip("/") + "/"
        normalized_base = urlsplit(self.base_url)
        self._base_origin = (normalized_base.scheme.lower(), normalized_base.netloc.lower())
        self.retry_policy = retry_policy or RetryPolicy(
            max_retries=max_retries,
            backoff_factor=backoff_factor,
            rate_limit_retries=rate_limit_retries,
            rate_limit_backoff=rate_limit_backoff,
            problem_retries=problem_retries,
            max_backoff=max_backoff,
        )
        self._owns_controller = concurrency is None
        self.concurrency = concurrency or ConcurrencyController(
            ConcurrencySettings(max_concurrency=max_concurrency)
        )
        self.wait_timeout_ms = wait_timeout_ms
        # Keep the server-side timeout below the client timeout so weclapp
        # answers with a definitive request_timeout problem first.
        self.request_timeout_ms = (
            _server_timeout_for(self.timeout, request_timeout_ms)
            if request_timeout_ms is not None
            else None
        )
        self.slow_threshold_ms = slow_threshold_ms
        self.before_request = before_request
        self.on_response = on_response
        self._stats = ClientStats(slow_threshold_ms)
        self._definitions_lock = threading.Lock()
        self._attribute_definitions: dict[str, JsonDict] | None = None

        self._owns_session = session is None
        self.session: requests.Session = session if session is not None else _WeclappSession()
        default_headers = {
            "Content-Type": "application/json",
            "AuthenticationToken": api_key,
            "User-Agent": user_agent or f"weclappy/{__version__}",
        }
        if wait_timeout_ms is not None:
            default_headers["X-Weclapp-Wait-Timeout-Ms"] = str(wait_timeout_ms)
        if self.request_timeout_ms is not None:
            default_headers["X-Weclapp-Request-Timeout-Ms"] = str(self.request_timeout_ms)
        self.session.headers.update(default_headers)
        if self._owns_session:
            # The adapter never retries: urllib3 cannot see the HTTP method's
            # semantics, so every retry decision lives in _send().
            adapter = HTTPAdapter(
                max_retries=0,
                pool_connections=pool_connections,
                pool_maxsize=pool_maxsize,
                pool_block=True,
            )
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    # ------------------------------------------------------------ constructors
    @classmethod
    def for_tenant(
        cls, tenant: str, api_key: str, *, api_version: int = 2, **kwargs: Any
    ) -> Weclapp:
        """Build a client from a tenant name (``acme``) or host (``acme.weclapp.com``)."""
        host = tenant if "." in tenant else f"{tenant}.weclapp.com"
        return cls(f"https://{host}/webapp/api/v{api_version}/", api_key, **kwargs)

    # --------------------------------------------------------------- lifecycle
    def close(self) -> None:
        """Release pooled connections and, for an owned controller, wake its waiters."""
        if self._owns_session:
            self.session.close()
        if self._owns_controller:
            self.concurrency.close()

    def __enter__(self) -> Weclapp:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    @property
    def stats(self) -> StatsSnapshot:
        """Immutable snapshot of request statistics since creation or :meth:`reset_stats`."""
        return self._stats.snapshot()

    def reset_stats(self) -> None:
        self._stats.reset()

    # ----------------------------------------------------------- URL building
    def _build_url(self, endpoint: str) -> str:
        """Build a same-origin API URL from a relative endpoint path."""
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint must be a non-empty relative path")
        parsed_endpoint = urlsplit(endpoint)
        if parsed_endpoint.scheme or parsed_endpoint.netloc:
            raise ValueError("endpoint must be relative to base_url")
        if parsed_endpoint.fragment:
            raise ValueError("endpoint must not contain a URL fragment")
        if ".." in parsed_endpoint.path.split("/"):
            raise ValueError("endpoint must not traverse outside base_url")
        url = urljoin(self.base_url, endpoint.lstrip("/"))
        parsed_url = urlsplit(url)
        if (parsed_url.scheme.lower(), parsed_url.netloc.lower()) != self._base_origin:
            raise ValueError("endpoint resolved outside base_url origin")
        return url

    @staticmethod
    def _path(entity: str, entity_id: str | None = None, action: str | None = None) -> str:
        """``entity[/id/{id}][/{action}]`` with every segment percent-encoded."""
        if not isinstance(entity, str) or not entity.strip():
            raise ValueError("entity must be a non-empty string")
        parts = [entity.strip("/")]
        if entity_id is not None:
            parts.append(f"id/{_segment(entity_id, 'entity_id')}")
        if action is not None:
            parts.append(_segment(action, "action"))
        return "/".join(parts)

    # ------------------------------------------------------------- raw request
    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        timeout: Timeout | None = None,
    ) -> Any:
        """Send one same-origin request through the client's retry and load control.

        Returns the parsed body: a dict for JSON, ``{"content": str, ...}`` for
        text, ``{"content": bytes, "content_type": ..., "filename": ...}`` for
        binary media, and ``{}`` for empty responses.
        """
        if not isinstance(method, str) or not method.strip():
            raise ValueError("method must be a non-empty string")
        method = method.strip().upper()
        url = self._build_url(endpoint)
        request_kwargs: dict[str, Any] = {}
        if params is not None:
            request_kwargs["params"] = dict(params)
        if json is not None:
            request_kwargs["json"] = WeclappEntity.unwrap(json)
        if data is not None:
            request_kwargs["data"] = data
        if timeout is not None:
            request_kwargs["timeout"] = _validate_timeout(timeout)
        request_headers = dict(headers) if headers else {}
        server_timeout = self._request_timeout_header(request_kwargs.get("timeout"))
        if server_timeout is not None:
            request_headers.setdefault("X-Weclapp-Request-Timeout-Ms", str(server_timeout))
        if request_headers:
            request_kwargs["headers"] = request_headers
        return self._send(method, url, **request_kwargs)

    def _request_timeout_header(self, timeout: Timeout | None) -> int | None:
        """Lower the server-side timeout header for a shorter per-request timeout."""
        if timeout is None or self.request_timeout_ms is None:
            return None
        derived = _server_timeout_for(timeout, self.request_timeout_ms)
        return derived if derived < self.request_timeout_ms else None

    @staticmethod
    def _is_read(method: str, path: str) -> bool:
        if method in SAFE_METHODS:
            return True
        if method == "POST":
            return path.endswith(_READ_POST_SUFFIXES) or path.endswith("batch/query")
        return False

    def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        """Execute one logical request: permits, retries, metrics, parsing."""
        kwargs.setdefault("timeout", self.timeout)
        # 307/308 would replay a write body; redirects are surfaced instead.
        kwargs.setdefault("allow_redirects", False)
        path = urlsplit(url).path
        is_read = self._is_read(method, path)
        state = RetryState()
        attempt = 0
        while True:
            attempt += 1
            started = time.monotonic()
            response: requests.Response | None = None
            decision: RetryDecision = RetryDecision(retry=False)
            error_name: str | None = None
            try:
                outgoing = OutgoingRequest(
                    method=method,
                    url=url,
                    path=path,
                    attempt=attempt,
                    headers=dict(kwargs.get("headers") or {}),
                    params=kwargs.get("params"),
                )
                if self.before_request is not None:
                    self.before_request(outgoing)
                kwargs["headers"] = outgoing.headers
                if outgoing.params is not None:
                    kwargs["params"] = outgoing.params
                permit = (
                    self.concurrency.acquire(timeout=_read_timeout(kwargs["timeout"]))
                    if is_read
                    else nullcontext()
                )
                if not is_read:
                    self.concurrency.wait_for_cooldown(timeout=_read_timeout(kwargs["timeout"]))
                with permit:
                    response = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                error_name = type(exc).__name__
                decision = decide_for_exception(self.retry_policy, state, exc, is_read=is_read)
                self.concurrency.observe(Signal.ERROR)
                self._record(method, path, None, started, attempt, decision, error_name)
                if decision.retry:
                    self._log_retry(method, path, decision, state.total)
                    time.sleep(decision.delay)
                    continue
                raise self._transport_error(method, path, exc) from exc

            signal = ConcurrencyController.signal_from_response(
                response.status_code, response.headers, self.concurrency.settings
            )
            if 200 <= response.status_code < 300:
                self.concurrency.observe(signal)
                self._record(method, path, response, started, attempt, decision, None)
                return self._parse_success_response(response)

            decision = decide_for_response(self.retry_policy, state, response, is_read=is_read)
            cooldown = None
            if response.status_code == 429:
                # A retrying read pauses everyone for exactly its own delay; a
                # write or an exhausted budget still starts the shared cooldown.
                cooldown = (
                    decision.delay
                    if decision.retry
                    else rate_limit_cooldown(self.retry_policy, response, state)
                )
            self.concurrency.observe(signal, cooldown=cooldown)
            self._record(method, path, response, started, attempt, decision, None)
            if decision.retry:
                self._log_retry(method, path, decision, state.total)
                time.sleep(decision.delay)
                continue
            raise self._http_error(method, path, response)

    # ------------------------------------------------------------- diagnostics
    def _record(
        self,
        method: str,
        path: str,
        response: requests.Response | None,
        started: float,
        attempt: int,
        decision: RetryDecision,
        error_name: str | None,
    ) -> None:
        duration_ms = (time.monotonic() - started) * 1000
        headers: Mapping[str, str] = response.headers if response is not None else {}
        wait_ms = ConcurrencyController.wait_ms_from_headers(headers)
        correlation_id = next((headers[h] for h in _CORRELATION_HEADERS if headers.get(h)), None)
        metrics = RequestMetrics(
            method=method,
            path=path,
            status_code=response.status_code if response is not None else None,
            duration_ms=duration_ms,
            wait_ms=wait_ms,
            wait_reason=headers.get("X-Weclapp-Wait-Reason") or None,
            correlation_id=correlation_id,
            attempt=attempt,
            will_retry=decision.retry,
            retry_delay=decision.delay,
            concurrency_target=self.concurrency.target,
            error=error_name,
        )
        self._stats.record(metrics)
        if self.on_response is not None:
            try:
                self.on_response(metrics)
            except Exception:
                logger.exception("on_response hook raised")
        if wait_ms is not None or metrics.wait_reason or correlation_id:
            logger.info(
                "[API_QUEUE] Weclapp %s %s wait_ms=%s reason=%s correlation_id=%s",
                method,
                path,
                "-" if wait_ms is None else f"{wait_ms:.0f}",
                metrics.wait_reason or "-",
                correlation_id or "-",
            )
        if error_name is not None:
            logger.warning(
                "[API] Weclapp %s %s -> ERROR (%.0fms) %s", method, path, duration_ms, error_name
            )
        elif duration_ms >= self.slow_threshold_ms:
            logger.warning(
                "[API_SLOW] Weclapp %s %s -> %s (%.0fms)",
                method,
                path,
                metrics.status_code,
                duration_ms,
            )
        else:
            logger.info(
                "[API] Weclapp %s %s -> %s (%.0fms)", method, path, metrics.status_code, duration_ms
            )

    @staticmethod
    def _log_retry(method: str, path: str, decision: RetryDecision, retry_number: int) -> None:
        logger.warning(
            "[API_RETRY] Weclapp %s %s -> %s; retry %d (%s) in %.2fs",
            method,
            path,
            decision.reason,
            retry_number,
            decision.kind.value if decision.kind else "-",
            decision.delay,
        )

    @staticmethod
    def _transport_error(
        method: str, path: str, exc: requests.RequestException
    ) -> WeclappTransportError:
        outcome = classify_transport_error(exc)
        sent = outcome is TransportOutcome.UNKNOWN
        hint = (
            "; the request may have been processed, read the entity back before repeating it"
            if sent and method not in SAFE_METHODS
            else ""
        )
        return WeclappTransportError(
            f"HTTP {method} request failed for {path}: {type(exc).__name__}{hint}",
            request_sent=sent,
            cause=exc,
        )

    @staticmethod
    def _http_error(method: str, path: str, response: requests.Response) -> WeclappAPIError:
        response_text = response.text
        message = f"HTTP {response.status_code} for {method} {path}"
        if 300 <= response.status_code < 400:
            message = f"{message}: redirect responses are not followed"
            location = response.headers.get("Location")
            if location:
                message = f"{message}; Location: {location}"
        else:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict) and payload.get("error"):
                message = f"{message} - {payload['error']}"
            if response_text:
                preview = response_text[:MAX_ERROR_MESSAGE_BODY_CHARS]
                if len(response_text) > MAX_ERROR_MESSAGE_BODY_CHARS:
                    preview = f"{preview}…"
                message = f"{message}\nResponse body: {preview}"
        return WeclappAPIError.from_response(message, response, response_text)

    # ----------------------------------------------------------- response body
    @classmethod
    def _parse_success_response(cls, response: requests.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return {}
        content_type = response.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type == "application/json" or media_type.endswith("+json"):
            return response.json()
        if media_type.startswith("text/") or media_type in _TEXTUAL_APPLICATION_TYPES:
            return {"content": response.text, "content_type": content_type}
        if not media_type:
            try:
                return response.json()
            except ValueError:
                pass
        result: dict[str, Any] = {"content": response.content, "content_type": content_type}
        filename = cls._extract_filename(response)
        if filename:
            result["filename"] = filename
        return result

    @staticmethod
    def _extract_filename(response: requests.Response) -> str | None:
        content_disposition = response.headers.get("Content-Disposition")
        if not content_disposition:
            return None
        message = Message()
        message["Content-Disposition"] = content_disposition
        return message.get_filename()

    # --------------------------------------------------------- entity wrapping
    def _wrap_rows(
        self,
        rows: list[JsonDict],
        additional_properties: dict[str, list[Any]] | None,
        referenced_entities: dict[str, dict[str, JsonDict]] | None,
    ) -> list[WeclappEntity]:
        if not rows:
            return []
        ap_global = additional_properties or {}
        ref_map = referenced_entities or {}
        attribute_definitions = self._attribute_definitions_for([rows, ref_map])
        wrapped: list[WeclappEntity] = []
        for index, row in enumerate(rows):
            per_row = {
                name: values[index] if isinstance(values, list) and index < len(values) else None
                for name, values in ap_global.items()
            }
            wrapped.append(WeclappEntity.from_row(row, per_row, ref_map, attribute_definitions))
        return wrapped

    @overload
    def _wrap_response(
        self, data: Any, *, return_weclapp_response: Literal[True]
    ) -> WeclappResponse: ...

    @overload
    def _wrap_response(
        self, data: Any, *, return_weclapp_response: Literal[False]
    ) -> list[WeclappEntity]: ...

    @overload
    def _wrap_response(
        self, data: Any, *, return_weclapp_response: bool
    ) -> list[WeclappEntity] | WeclappResponse: ...

    def _wrap_response(
        self, data: Any, *, return_weclapp_response: bool
    ) -> list[WeclappEntity] | WeclappResponse:
        if not isinstance(data, dict):
            raise TypeError("weclapp list response must be a dictionary")
        response = WeclappResponse.from_api_response(data)
        raw_result: Any = response.result
        rows = raw_result if isinstance(raw_result, list) else [raw_result]
        wrapped = self._wrap_rows(
            [row for row in rows if isinstance(row, dict)],
            response.additional_properties,
            response.referenced_entities,
        )
        if return_weclapp_response:
            return WeclappResponse(
                result=wrapped,
                additional_properties=response.additional_properties,
                referenced_entities=response.referenced_entities,
                raw_response=response.raw_response,
            )
        return wrapped

    # ------------------------------------------------- attribute definitions
    def _attribute_definitions_for(self, rows: Any) -> dict[str, JsonDict]:
        """Return the definition cache, loading it on first need.

        The cache is needed only to derive flattened field names for
        ``customAttributes`` entries that lack ``internalName`` (the normal
        case for v2 responses). Permanent client-side failures (4xx that are
        not transient) are cached as "no definitions" with a single warning;
        transient failures propagate so entity shape never silently varies.
        """
        definitions = self._attribute_definitions
        if definitions is not None:
            return definitions
        if not _rows_need_attribute_definitions(rows):
            return {}
        with self._definitions_lock:
            if self._attribute_definitions is None:
                self._attribute_definitions = self._load_attribute_definitions()
            return self._attribute_definitions

    def _load_attribute_definitions(self) -> dict[str, JsonDict]:
        cache: dict[str, JsonDict] = {}
        try:
            for rows, _ in self._iter_pages(
                "customAttributeDefinition",
                {"properties": "id,attributeKey,attributeType,readOnly"},
                None,
            ):
                for definition in rows:
                    if isinstance(definition, dict) and "id" in definition:
                        cache[definition["id"]] = dict(definition)
        except WeclappAPIError as exc:
            if (
                exc.status_code is not None
                and 400 <= exc.status_code < 500
                and not exc.is_retryable
            ):
                logger.warning(
                    "customAttributeDefinition is not readable (status=%s, type=%s); "
                    "customAttributes without internalName will not be flattened",
                    exc.status_code,
                    exc.error_type,
                )
                return {}
            raise
        return cache

    def refresh_attribute_definitions(self) -> dict[str, JsonDict]:
        """Reload the ``customAttributeDefinition`` cache and return it."""
        with self._definitions_lock:
            self._attribute_definitions = self._load_attribute_definitions()
            return self._attribute_definitions

    # ------------------------------------------------------------------ reads
    @overload
    def get(
        self,
        entity: str,
        entity_id: str | None = None,
        params: Mapping[str, Any] | None = None,
        *,
        return_weclapp_response: Literal[True],
        id: str | None = None,
    ) -> WeclappResponse: ...

    @overload
    def get(
        self,
        entity: str,
        entity_id: None = None,
        params: Mapping[str, Any] | None = None,
        *,
        return_weclapp_response: Literal[False] = False,
        id: str,
    ) -> WeclappEntity: ...

    @overload
    def get(
        self,
        entity: str,
        entity_id: str,
        params: Mapping[str, Any] | None = None,
        *,
        return_weclapp_response: Literal[False] = False,
    ) -> WeclappEntity: ...

    @overload
    def get(
        self,
        entity: str,
        entity_id: None = None,
        params: Mapping[str, Any] | None = None,
        *,
        return_weclapp_response: Literal[False] = False,
    ) -> list[WeclappEntity]: ...

    def get(
        self,
        entity: str,
        entity_id: str | None = None,
        params: Mapping[str, Any] | None = None,
        *,
        return_weclapp_response: bool = False,
        id: str | None = None,
    ) -> list[WeclappEntity] | WeclappEntity | WeclappResponse:
        """Read one page of ``entity``, or a single record when ``entity_id`` is given.

        Single records are read as ``GET {entity}?id-eq={id}&pageSize=1``
        because ``/id/{id}`` ignores ``properties`` and
        ``includeReferencedEntities``. An empty result raises
        :class:`~weclappy.errors.WeclappNotFoundError` with a synthetic 404.
        """
        entity_id = _legacy_id(entity_id, id, "get")
        query = dict(params) if params else {}
        path = self._path(entity)
        if entity_id is None:
            return self._wrap_response(
                self.request("GET", path, params=query),
                return_weclapp_response=return_weclapp_response,
            )
        query.update({"id-eq": entity_id, "page": 1, "pageSize": 1})
        data = self.request("GET", path, params=query)
        wrapped = self._wrap_response(data, return_weclapp_response=False)
        if not wrapped:
            raise _not_found(entity, entity_id, self._build_url(path))
        if return_weclapp_response:
            parsed = WeclappResponse.from_api_response(data)
            return WeclappResponse(
                result=wrapped[0],
                additional_properties=parsed.additional_properties,
                referenced_entities=parsed.referenced_entities,
                raw_response=parsed.raw_response,
            )
        return wrapped[0]

    def count(self, entity: str, params: Mapping[str, Any] | None = None) -> int:
        """``GET {entity}/count`` with the filter part of ``params``."""
        data = self.request("GET", self._path(entity, action="count"), params=_count_params(params))
        return _count_result(data)

    @overload
    def get_all(
        self,
        entity: str,
        params: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
        max_records: int | None = None,
        threaded: ThreadedMode = "auto",
        max_workers: int | None = None,
        strategy: Strategy = "pages",
        return_weclapp_response: Literal[True],
    ) -> WeclappResponse: ...

    @overload
    def get_all(
        self,
        entity: str,
        params: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
        max_records: int | None = None,
        threaded: ThreadedMode = "auto",
        max_workers: int | None = None,
        strategy: Strategy = "pages",
        return_weclapp_response: Literal[False] = False,
    ) -> list[WeclappEntity]: ...

    def get_all(
        self,
        entity: str,
        params: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
        max_records: int | None = None,
        threaded: ThreadedMode = "auto",
        max_workers: int | None = None,
        strategy: Strategy = "pages",
        return_weclapp_response: bool = False,
    ) -> list[WeclappEntity] | WeclappResponse:
        """Read every record of ``entity`` matching ``params``.

        Args:
            entity: Entity name, e.g. ``salesOrder``.
            params: Query parameters (filters, ``properties``,
                ``includeReferencedEntities``, ``additionalProperties``,
                ``pageSize``, ``sort``). Without ``sort``/``orderBy`` the
                client sorts by ``id`` so that pages are stable; pass
                ``{"sort": None}`` to opt out.
            limit: Stop after this many records.
            max_records: Refuse the read (before fetching data) when the
                matching record count exceeds this budget.
            threaded: ``"auto"`` (default) reads the first page sequentially and,
                only when more pages exist, counts the result set and fetches
                the remaining pages concurrently under the adaptive
                controller. ``True`` is an alias; ``False`` reads every page
                sequentially without a count.
            max_workers: Concurrency ceiling for this call; must not exceed
                the controller's ``max_concurrency``.
            strategy: ``"pages"`` reads full rows page by page. ``"ids"`` reads
                ids first and then the rows in ``id-in`` chunks, the pattern
                weclapp recommends for large projections.
            return_weclapp_response: Return a :class:`WeclappResponse` instead
                of the bare list.

        Raises:
            WeclappPaginationError: on duplicate ids between pages, when fewer
                rows than counted arrive, or when ``max_records`` is exceeded.
        """
        _validate_non_negative(limit, "limit")
        _validate_non_negative(max_records, "max_records")
        workers = self._resolve_workers(max_workers)
        if threaded not in (True, False, "auto"):
            raise ValueError('threaded must be True, False or "auto"')
        if limit == 0:
            return _empty_collection(return_weclapp_response)
        query = _with_default_sort(params)
        page_size = _page_size(query, limit)
        query["pageSize"] = page_size

        if strategy == "ids":
            return self._get_all_by_ids(
                entity, query, limit, max_records, workers, return_weclapp_response
            )
        if strategy != "pages":
            raise ValueError('strategy must be "pages" or "ids"')

        collector = _Collector()
        path = self._path(entity)
        if threaded is False:
            self._collect_sequential(path, entity, query, collector, limit, max_records)
        else:
            self._collect_adaptive(path, entity, query, collector, limit, max_records, workers)
        return self._finalize(collector, limit, return_weclapp_response)

    def _fetch_page(self, path: str, query: Mapping[str, Any], page: int) -> Any:
        return self.request("GET", path, params={**query, "page": page})

    def _collect_sequential(
        self,
        path: str,
        entity: str,
        query: dict[str, Any],
        collector: _Collector,
        limit: int | None,
        max_records: int | None,
    ) -> None:
        page_size = query["pageSize"]
        page_number = 1
        while True:
            page_query = {**query, "page": page_number}
            logger.info("Fetching page %d for %s", page_number, entity)
            count = _merge_page(
                self.request("GET", path, params=page_query), collector, entity, page_number
            )
            if max_records is not None and len(collector.results) > max_records:
                raise WeclappPaginationError(
                    f"'{entity}' exceeds max_records={max_records}; stopped on page {page_number}"
                )
            if count < page_size or (limit is not None and len(collector.results) >= limit):
                return
            page_number += 1

    def _collect_adaptive(
        self,
        path: str,
        entity: str,
        query: dict[str, Any],
        collector: _Collector,
        limit: int | None,
        max_records: int | None,
        workers: int,
    ) -> None:
        page_size = query["pageSize"]
        first = self.request("GET", path, params={**query, "page": 1})
        first_count = _merge_page(first, collector, entity, 1)
        if first_count < page_size or (limit is not None and first_count >= limit):
            if max_records is not None and first_count > max_records:
                raise WeclappPaginationError(f"'{entity}' exceeds max_records={max_records}")
            return

        total = self.count(entity, query)
        expected = min(total, limit) if limit is not None else total
        if max_records is not None and expected > max_records:
            raise WeclappPaginationError(
                f"'{entity}' has {total} matching records, more than max_records={max_records}"
            )
        total_pages = max(1, math.ceil(expected / page_size))
        if total_pages > 1:
            logger.info(
                "Total %d records for %s; fetching %d more pages with concurrency up to %d",
                total,
                entity,
                total_pages - 1,
                workers,
            )
            pages = self._run_window(
                {
                    page: partial(self._fetch_page, path, query, page)
                    for page in range(2, total_pages + 1)
                },
                workers,
            )
            for page_number in sorted(pages):
                _merge_page(pages[page_number], collector, entity, page_number)
        if len(collector.results) < expected:
            raise WeclappPaginationError(
                f"Pagination for '{entity}' returned {len(collector.results)} of {expected} "
                "counted records; the data set changed between requests, retry the read"
            )

    def _get_all_by_ids(
        self,
        entity: str,
        query: dict[str, Any],
        limit: int | None,
        max_records: int | None,
        workers: int,
        return_weclapp_response: bool,
    ) -> list[WeclappEntity] | WeclappResponse:
        id_query = {
            key: value
            for key, value in query.items()
            if key not in ("properties", "additionalProperties", "includeReferencedEntities")
        }
        id_query["properties"] = "id"
        id_rows = self.get_all(
            entity,
            id_query,
            limit=limit,
            max_records=max_records,
            max_workers=workers,
            return_weclapp_response=True,
        )
        ids = [row["id"] for row in id_rows.result if isinstance(row, dict) and "id" in row]
        payload_query = {key: value for key, value in query.items() if key not in _PAGINATION_KEYS}
        payload_query.pop("sort", None)
        return self.get_by_ids(
            entity,
            ids,
            payload_query,
            max_workers=workers,
            return_weclapp_response=return_weclapp_response,
        )

    @overload
    def get_by_ids(
        self,
        entity: str,
        ids: Sequence[str],
        params: Mapping[str, Any] | None = None,
        *,
        chunk_size: int = DEFAULT_ID_CHUNK_SIZE,
        max_url_length: int = DEFAULT_MAX_URL_LENGTH,
        max_workers: int | None = None,
        return_weclapp_response: Literal[True],
    ) -> WeclappResponse: ...

    @overload
    def get_by_ids(
        self,
        entity: str,
        ids: Sequence[str],
        params: Mapping[str, Any] | None = None,
        *,
        chunk_size: int = DEFAULT_ID_CHUNK_SIZE,
        max_url_length: int = DEFAULT_MAX_URL_LENGTH,
        max_workers: int | None = None,
        return_weclapp_response: Literal[False] = False,
    ) -> list[WeclappEntity]: ...

    @overload
    def get_by_ids(
        self,
        entity: str,
        ids: Sequence[str],
        params: Mapping[str, Any] | None = None,
        *,
        chunk_size: int = DEFAULT_ID_CHUNK_SIZE,
        max_url_length: int = DEFAULT_MAX_URL_LENGTH,
        max_workers: int | None = None,
        return_weclapp_response: bool,
    ) -> list[WeclappEntity] | WeclappResponse: ...

    def get_by_ids(
        self,
        entity: str,
        ids: Sequence[str],
        params: Mapping[str, Any] | None = None,
        *,
        chunk_size: int = DEFAULT_ID_CHUNK_SIZE,
        max_url_length: int = DEFAULT_MAX_URL_LENGTH,
        max_workers: int | None = None,
        return_weclapp_response: bool = False,
    ) -> list[WeclappEntity] | WeclappResponse:
        """Read specific records by id in ``id-in`` chunks, concurrently.

        Rows are returned in the order of ``ids``; ids weclapp no longer knows
        are silently absent (the id list is a snapshot). Chunks are sized by
        ``chunk_size`` and additionally split so that no URL exceeds
        ``max_url_length`` bytes.
        """
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        workers = self._resolve_workers(max_workers)
        unique_ids = list(dict.fromkeys(str(value) for value in ids))
        if not unique_ids:
            return _empty_collection(return_weclapp_response)
        path = self._path(entity)
        base_query = {k: v for k, v in (params or {}).items() if k not in _PAGINATION_KEYS}
        base_query.pop("sort", None)
        url = self._build_url(path)
        chunks = _chunk_ids(unique_ids, chunk_size, max_url_length, url, base_query)
        jobs = {
            index: (
                lambda c=chunk: self.request(
                    "GET",
                    path,
                    params={**base_query, "id-in": _json_ids(c), "pageSize": len(c)},
                )
            )
            for index, chunk in enumerate(chunks)
        }
        pages = self._run_window(jobs, workers)
        collector = _Collector()
        for index in sorted(pages):
            _merge_page(pages[index], collector, entity, index + 1)
        order = {value: position for position, value in enumerate(unique_ids)}
        collector.results, collector.additional_properties = _reorder(
            collector.results, collector.additional_properties, order
        )
        return self._finalize(collector, None, return_weclapp_response)

    def iter_all(
        self,
        entity: str,
        params: Mapping[str, Any] | None = None,
        *,
        limit: int | None = None,
    ) -> Iterator[WeclappEntity]:
        """Yield records page by page without holding the whole result set."""
        for rows, response in self._iter_pages(entity, params, limit):
            yield from self._wrap_rows(
                rows, response.additional_properties, response.referenced_entities
            )

    def _iter_pages(
        self, entity: str, params: Mapping[str, Any] | None, limit: int | None
    ) -> Iterator[tuple[list[JsonDict], WeclappResponse]]:
        """Yield ``(rows, parsed response)`` per page, truncated to ``limit`` rows."""
        _validate_non_negative(limit, "limit")
        if limit == 0:
            return
        query = _with_default_sort(params)
        page_size = _page_size(query, limit)
        query["pageSize"] = page_size
        path = self._path(entity)
        seen: set[Any] = set()
        yielded = 0
        page_number = 1
        while True:
            data = self.request("GET", path, params={**query, "page": page_number})
            rows = _rows_of(data)
            if not rows:
                return
            _check_duplicates(rows, seen, entity, page_number)
            if limit is not None:
                rows = rows[: limit - yielded]
            yield rows, WeclappResponse.from_api_response(data)
            yielded += len(rows)
            if (limit is not None and yielded >= limit) or len(rows) < page_size:
                return
            page_number += 1

    def iter_keyset(
        self,
        entity: str,
        params: Mapping[str, Any] | None = None,
        *,
        start_after: str | None = None,
        limit: int | None = None,
    ) -> Iterator[WeclappEntity]:
        """Yield records with keyset pagination (``sort=id`` + ``id-gt``).

        Unlike offset pagination this never skips or duplicates rows when the
        data set changes while reading, which makes it the right iterator for
        long exports and reports. ``params`` must not contain ``page``,
        ``sort``, ``orderBy`` or an ``id-gt`` filter.
        """
        _validate_non_negative(limit, "limit")
        if limit == 0:
            return
        query = dict(params) if params else {}
        for key in ("page", "sort", "orderBy", "id-gt"):
            if key in query:
                raise ValueError(f"iter_keyset manages '{key}' itself")
        page_size = _page_size(query, limit)
        query.update({"pageSize": page_size, "sort": "id"})
        path = self._path(entity)
        last_id = start_after
        yielded = 0
        while True:
            page_query = dict(query)
            if last_id is not None:
                page_query["id-gt"] = last_id
            data = self.request("GET", path, params=page_query)
            rows = _rows_of(data)
            if not rows:
                return
            response = WeclappResponse.from_api_response(data)
            for item in self._wrap_rows(
                rows, response.additional_properties, response.referenced_entities
            ):
                yield item
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            last_row_id = rows[-1].get("id")
            if last_row_id is None:
                raise WeclappPaginationError(
                    f"iter_keyset for '{entity}' needs 'id' in the projection"
                )
            if len(rows) < page_size:
                return
            last_id = str(last_row_id)

    # ------------------------------------------------- unofficial read endpoints
    @overload
    def query(
        self,
        entity: str,
        *,
        filter: str | None = None,
        properties: Sequence[str] | None = None,
        include_referenced_entities: Sequence[str] | None = None,
        additional_properties: Sequence[str] | None = None,
        order_by: Sequence[str] | None = None,
        page: int | None = None,
        page_size: int | None = None,
        offset: int | None = None,
        serialize_nulls: bool | None = None,
        return_weclapp_response: Literal[True],
    ) -> WeclappResponse: ...

    @overload
    def query(
        self,
        entity: str,
        *,
        filter: str | None = None,
        properties: Sequence[str] | None = None,
        include_referenced_entities: Sequence[str] | None = None,
        additional_properties: Sequence[str] | None = None,
        order_by: Sequence[str] | None = None,
        page: int | None = None,
        page_size: int | None = None,
        offset: int | None = None,
        serialize_nulls: bool | None = None,
        return_weclapp_response: Literal[False] = False,
    ) -> list[WeclappEntity]: ...

    @overload
    def query(
        self,
        entity: str,
        *,
        filter: str | None = None,
        properties: Sequence[str] | None = None,
        include_referenced_entities: Sequence[str] | None = None,
        additional_properties: Sequence[str] | None = None,
        order_by: Sequence[str] | None = None,
        page: int | None = None,
        page_size: int | None = None,
        offset: int | None = None,
        serialize_nulls: bool | None = None,
        return_weclapp_response: bool,
    ) -> list[WeclappEntity] | WeclappResponse: ...

    def query(
        self,
        entity: str,
        *,
        filter: str | None = None,
        properties: Sequence[str] | None = None,
        include_referenced_entities: Sequence[str] | None = None,
        additional_properties: Sequence[str] | None = None,
        order_by: Sequence[str] | None = None,
        page: int | None = None,
        page_size: int | None = None,
        offset: int | None = None,
        serialize_nulls: bool | None = None,
        return_weclapp_response: bool = False,
    ) -> list[WeclappEntity] | WeclappResponse:
        """``POST {entity}/query`` - weclapp's undocumented body-based read.

        The endpoint is listed only in the hidden OpenAPI document
        (``openapi(include_hidden=True)``); weclapp does not announce changes
        to it. It accepts a ``filter`` expression (e.g. ``"id in [1,2]"`` or
        ``"status = 'ORDER_CONFIRMED'"``) in the request body, so very long id
        lists do not hit the URL length limit. ``order_by`` entries look like
        ``"id"`` or ``"-id"``.
        """
        body: dict[str, Any] = {}
        if filter is not None:
            body["filter"] = filter
        if properties is not None:
            body["properties"] = list(properties)
        if include_referenced_entities is not None:
            body["includeReferencedEntities"] = list(include_referenced_entities)
        if additional_properties is not None:
            body["additionalProperties"] = list(additional_properties)
        if order_by is not None:
            body["orderBy"] = list(order_by)
        for key, value in (("page", page), ("pageSize", page_size), ("offset", offset)):
            if value is not None:
                body[key] = value
        if serialize_nulls is not None:
            body["serializeNulls"] = serialize_nulls
        data = self.request("POST", self._path(entity, action="query"), json=body)
        return self._wrap_response(data, return_weclapp_response=return_weclapp_response)

    def query_count(self, entity: str, *, filter: str | None = None) -> int:
        """``POST {entity}/count`` with a body filter expression (undocumented endpoint)."""
        body = {"filter": filter} if filter is not None else {}
        return _count_result(self.request("POST", self._path(entity, action="count"), json=body))

    def batch_query(self, requests_: Sequence[str]) -> list[BatchResult]:
        """``POST batch/query`` - run up to 500 relative GET queries in one call.

        Undocumented endpoint. Each item is a relative collection path with
        query string, e.g. ``"article?properties=id&pageSize=100"`` or
        ``"party/count?partyType-eq=CUSTOMER"``; ``/id/{id}`` paths are
        rejected by weclapp. Results come back ordered by request index, and
        a failing sub-request does not fail the batch: check
        :attr:`BatchResult.ok` per entry.
        """
        items = [str(item).lstrip("/") for item in requests_]
        if not items:
            return []
        if len(items) > BATCH_QUERY_MAX_REQUESTS:
            raise ValueError(f"batch_query accepts at most {BATCH_QUERY_MAX_REQUESTS} requests")
        for item in items:
            self._build_url(item)
        data = self.request("POST", "batch/query", json={"requests": items})
        return _parse_batch(data)

    def openapi(self, *, include_hidden: bool = False) -> str:
        """Return the tenant's OpenAPI document (YAML text).

        ``include_hidden=True`` adds the undocumented endpoints (``/query``,
        ``POST /count``, ``batch/query`` ...).
        """
        params = {"includeHidden": "true"} if include_hidden else None
        data = self.request("GET", "meta/openapi.yaml", params=params)
        content = data.get("content") if isinstance(data, dict) else None
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            return content.decode("utf-8")
        return json_module.dumps(data)

    # ----------------------------------------------------------------- writes
    def post(
        self, entity: str, data: JsonDict | WeclappEntity, params: Mapping[str, Any] | None = None
    ) -> Any:
        """``POST {entity}``. Never retried unless the request provably never left."""
        return self.request("POST", self._path(entity), json=data, params=params)

    def put(
        self,
        entity: str,
        entity_id: str | None = None,
        data: JsonDict | WeclappEntity | None = None,
        params: Mapping[str, Any] | None = None,
        *,
        id: str | None = None,
    ) -> Any:
        """``PUT {entity}/id/{id}`` with ``ignoreMissingProperties=true`` unless overridden."""
        entity_id = _legacy_id(entity_id, id, "put")
        if entity_id is None:
            raise TypeError("put() requires entity_id")
        if data is None:
            raise TypeError("put() requires data")
        query = dict(params) if params else {}
        query.setdefault("ignoreMissingProperties", True)
        return self.request("PUT", self._path(entity, entity_id), json=data, params=query)

    def delete(
        self,
        entity: str,
        entity_id: str | None = None,
        params: Mapping[str, Any] | None = None,
        *,
        id: str | None = None,
    ) -> Any:
        """``DELETE {entity}/id/{id}``; returns ``{}`` on 204."""
        entity_id = _legacy_id(entity_id, id, "delete")
        if entity_id is None:
            raise TypeError("delete() requires entity_id")
        return self.request("DELETE", self._path(entity, entity_id), params=params)

    def call_method(
        self,
        entity: str,
        action: str,
        entity_id: str | None = None,
        *,
        method: Literal["GET", "POST"] = "GET",
        data: JsonDict | WeclappEntity | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Call ``{entity}[/id/{id}]/{action}`` with GET or POST."""
        method = method.upper()  # type: ignore[assignment]
        if method not in ("GET", "POST"):
            raise ValueError("call_method supports only GET and POST")
        return self.request(method, self._path(entity, entity_id, action), json=data, params=params)

    def upload(
        self,
        entity: str,
        data: bytes,
        entity_id: str | None = None,
        action: str | None = None,
        params: Mapping[str, Any] | None = None,
        *,
        content_type: str | None = None,
        filename: str | None = None,
        id: str | None = None,
    ) -> Any:
        """Upload binary data to ``{entity}[/id/{id}][/{action}]``.

        The content type is ``content_type`` if given, else inferred from
        ``filename``, else ``application/octet-stream``.
        """
        entity_id = _legacy_id(entity_id, id, "upload")
        inferred = infer_content_type(filename)
        effective = content_type or inferred or "application/octet-stream"
        if content_type and inferred and content_type != inferred:
            logger.warning(
                "Content type mismatch: explicit '%s' differs from inferred '%s' for '%s'",
                content_type,
                inferred,
                filename,
            )
        path = self._path(entity, entity_id, action)
        return self.request(
            "POST", path, data=data, headers={"Content-Type": effective}, params=params
        )

    def download(
        self,
        entity: str,
        entity_id: str | None = None,
        action: str | None = None,
        params: Mapping[str, Any] | None = None,
        *,
        id: str | None = None,
    ) -> Any:
        """Download from ``{entity}[/id/{id}][/{action}]``; defaults to ``/download``."""
        entity_id = _legacy_id(entity_id, id, "download")
        if entity_id is not None and action is None:
            action = "download"
        return self.request("GET", self._path(entity, entity_id, action), params=params)

    # ------------------------------------------------------------- internals
    def _resolve_workers(self, max_workers: int | None) -> int:
        ceiling = self.concurrency.ceiling
        if max_workers is None:
            return ceiling
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        if max_workers > ceiling:
            logger.warning(
                "max_workers=%d exceeds max_concurrency=%d; using %d "
                "(raise max_concurrency on the client to allow more)",
                max_workers,
                ceiling,
                ceiling,
            )
            return ceiling
        return max_workers

    def _run_window(self, jobs: Mapping[int, Callable[[], Any]], workers: int) -> dict[int, Any]:
        """Run ``jobs`` concurrently under the controller's moving window.

        The window is ``min(workers, controller.target)`` jobs in flight; it
        follows the controller as feedback arrives. The first failure cancels
        queued jobs, abandons running ones and propagates immediately.
        """
        results: dict[int, Any] = {}
        pending = sorted(jobs)
        if not pending:
            return results
        in_flight: dict[Future[Any], int] = {}
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="weclappy")

        def submit_available() -> None:
            target = min(workers, self.concurrency.target)
            while pending and len(in_flight) < target:
                index = pending.pop(0)
                in_flight[executor.submit(jobs[index])] = index

        try:
            submit_available()
            while in_flight:
                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in done:
                    results[in_flight.pop(future)] = future.result()
                submit_available()
        except BaseException:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        executor.shutdown(wait=True)
        return results

    def _finalize(
        self, collector: _Collector, limit: int | None, return_weclapp_response: bool
    ) -> list[WeclappEntity] | WeclappResponse:
        results = collector.results[:limit] if limit is not None else collector.results
        count = len(results)
        additional = {
            name: values[:count] for name, values in collector.additional_properties.items()
        }
        raw: JsonDict = {"result": results}
        if additional:
            raw["additionalProperties"] = additional
        if collector.referenced_entities:
            raw["referencedEntities"] = collector.referenced_entities
        return self._wrap_response(raw, return_weclapp_response=return_weclapp_response)


# ---------------------------------------------------------------- helpers


def _legacy_id(entity_id: str | None, legacy: str | None, method: str) -> str | None:
    """Resolve the deprecated ``id=`` keyword (0.x) onto ``entity_id``."""
    if legacy is None:
        return entity_id
    if entity_id is not None:
        raise TypeError(f"{method}() got both entity_id and the deprecated id keyword")
    warnings.warn(
        f"Weclapp.{method}(id=...) is deprecated and will be removed in weclappy 2.0; "
        "use entity_id=",
        DeprecationWarning,
        stacklevel=3,
    )
    return legacy


def _segment(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if "/" in value or "?" in value or "#" in value:
        raise ValueError(f"{name} must not contain '/', '?' or '#'")
    return quote(value, safe="")


def _validate_timeout(timeout: Timeout) -> Timeout:
    values = timeout if isinstance(timeout, tuple) else (timeout,)
    if isinstance(timeout, tuple) and len(values) != 2:
        raise ValueError("timeout tuple must be (connect, read)")
    for value in values:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("timeout must be greater than zero")
    return timeout


def _server_timeout_for(timeout: Timeout, header_ms: int) -> int:
    """Keep the server-side timeout header below the client timeout.

    The configured header wins while it is shorter than the client's read
    timeout; otherwise 90 % of the read timeout is used so weclapp answers
    with a definitive ``request_timeout`` problem before the client gives up.
    """
    read_ms = _read_timeout(timeout) * 1000
    return header_ms if header_ms < read_ms else max(1, int(read_ms * 0.9))


def _read_timeout(timeout: Timeout) -> float:
    return float(timeout[1] if isinstance(timeout, tuple) else timeout)


def _validate_non_negative(value: int | None, name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError(f"{name} must be a non-negative integer or None")


def _with_default_sort(params: Mapping[str, Any] | None) -> dict[str, Any]:
    query = dict(params) if params else {}
    if "sort" in query and query["sort"] is None:
        query.pop("sort")
    elif "sort" not in query and "orderBy" not in query:
        query["sort"] = "id"
    return query


def _page_size(query: dict[str, Any], limit: int | None) -> int:
    page_size = query.get("pageSize", DEFAULT_PAGE_SIZE)
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size <= 0:
        raise ValueError("pageSize must be a positive integer")
    if limit is not None and limit > 0:
        return min(page_size, limit)
    return page_size


def _count_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in (params or {}).items()
        if key not in _PAGINATION_KEYS and key not in _PROJECTION_KEYS
    }


def _count_result(data: Any) -> int:
    if not isinstance(data, dict):
        raise TypeError("weclapp count response must be a dictionary")
    total = data.get("result", 0)
    if isinstance(total, bool) or not isinstance(total, int):
        raise TypeError("weclapp count response 'result' must be an integer")
    return total


def _rows_of(data: Any) -> list[JsonDict]:
    if not isinstance(data, dict):
        raise TypeError("weclapp list response must be a dictionary")
    rows = data.get("result") or []
    if not isinstance(rows, list):
        raise TypeError("weclapp list response 'result' must be a list")
    return rows


def _check_duplicates(rows: list[JsonDict], seen: set[Any], entity: str, page_number: int) -> None:
    """Reject duplicate ids between pages: the data set moved under the read."""
    page_ids: set[Any] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        row_id = row["id"]
        try:
            duplicate = row_id in seen or row_id in page_ids
        except TypeError:
            continue
        if duplicate:
            raise WeclappPaginationError(
                f"Pagination for '{entity}' returned duplicate entity id '{row_id}' on page "
                f"{page_number}; the data set changed between requests, retry the read"
            )
        page_ids.add(row_id)
    seen.update(page_ids)


def _merge_page(data: Any, collector: _Collector, entity: str, page_number: int) -> int:
    rows = _rows_of(data)
    _check_duplicates(rows, collector.seen_ids, entity, page_number)
    previous = len(collector.results)
    count = len(rows)
    collector.results.extend(rows)

    page_properties = data.get("additionalProperties") or {}
    if not isinstance(page_properties, dict):
        page_properties = {}
    for name in set(collector.additional_properties) - set(page_properties):
        collector.additional_properties[name].extend([None] * count)
    for name, values in page_properties.items():
        column = collector.additional_properties.setdefault(name, [None] * previous)
        normalized = list(values)[:count] if isinstance(values, list) else []
        normalized.extend([None] * (count - len(normalized)))
        column.extend(normalized)

    references = data.get("referencedEntities") or {}
    if isinstance(references, dict):
        for entity_type, entities in references.items():
            if isinstance(entities, list):
                collector.referenced_entities.setdefault(entity_type, []).extend(entities)
    return count


def _reorder(
    rows: list[JsonDict], additional: dict[str, list[Any]], order: Mapping[str, int]
) -> tuple[list[JsonDict], dict[str, list[Any]]]:
    indexed = sorted(range(len(rows)), key=lambda i: order.get(str(rows[i].get("id")), len(order)))
    return (
        [rows[i] for i in indexed],
        {name: [values[i] for i in indexed] for name, values in additional.items()},
    )


def _json_ids(ids: Sequence[str]) -> str:
    return json_module.dumps(list(ids), separators=(",", ":"))


def _chunk_ids(
    ids: list[str], chunk_size: int, max_url_length: int, url: str, base_query: Mapping[str, Any]
) -> list[list[str]]:
    """Split ``ids`` by count and by the encoded URL length of each chunk."""
    overhead = (
        len(url) + 1 + len(urlencode({**base_query, "pageSize": chunk_size})) + len("&id-in=")
    )
    chunks: list[list[str]] = []
    current: list[str] = []
    current_length = 0
    for value in ids:
        encoded = len(quote(json_module.dumps(value))) + 3  # quotes, comma, brackets
        if current and (
            len(current) >= chunk_size or overhead + current_length + encoded > max_url_length
        ):
            chunks.append(current)
            current, current_length = [], 0
        current.append(value)
        current_length += encoded
    if current:
        chunks.append(current)
    return chunks


def _parse_batch(data: Any) -> list[BatchResult]:
    if not isinstance(data, list) or len(data) % 3:
        raise TypeError("batch/query response must be a flat list of (index, meta, result)")
    results: list[BatchResult] = []
    for position in range(0, len(data), 3):
        index, meta, entry = data[position : position + 3]
        if not isinstance(entry, dict):
            raise TypeError("batch/query entry must be a dictionary")
        results.append(
            BatchResult(
                index=int(index),
                status=int(entry.get("status", 0)),
                body=entry.get("body"),
                meta=int(meta) if isinstance(meta, int) else 0,
            )
        )
    return sorted(results, key=lambda item: item.index)


def _rows_need_attribute_definitions(rows: Any) -> bool:
    """True if any ``customAttributes`` entry in ``rows`` lacks ``internalName``."""
    if isinstance(rows, dict):
        attributes = rows.get("customAttributes")
        if isinstance(attributes, list) and any(
            isinstance(item, dict) and not item.get("internalName") for item in attributes
        ):
            return True
        return any(
            _rows_need_attribute_definitions(value)
            for value in rows.values()
            if isinstance(value, (dict, list))
        )
    if isinstance(rows, list):
        return any(_rows_need_attribute_definitions(item) for item in rows)
    return False


def _empty_collection(return_weclapp_response: bool) -> list[WeclappEntity] | WeclappResponse:
    if return_weclapp_response:
        return WeclappResponse(result=[], raw_response={"result": []})
    return []


def _not_found(entity: str, entity_id: str, url: str) -> WeclappNotFoundError:
    message = f"Entity '{entity}' with id '{entity_id}' not found"
    body = json_module.dumps({"type": "/errors/not_found", "error": "Not Found", "detail": message})
    synthetic = requests.Response()
    synthetic.status_code = 404
    synthetic.url = url
    synthetic._content = body.encode("utf-8")
    synthetic.headers["Content-Type"] = "application/json"
    return WeclappNotFoundError(message, synthetic, body)
