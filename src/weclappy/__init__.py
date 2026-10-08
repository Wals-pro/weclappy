"""weclappy - a thin, safe Python client for the weclapp REST API.

Quick start::

    from weclappy import Weclapp

    client = Weclapp.for_tenant("acme", api_key)
    orders = client.get_all("salesOrder", {"status-eq": "ORDER_CONFIRMED"})
    order = client.get("salesOrder", "4384")
    order.customer.name          # lazy *Id resolution via referencedEntities
"""

from .client import (
    DEFAULT_API_REQUEST_TIMEOUT_MS,
    DEFAULT_ID_CHUNK_SIZE,
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_URL_LENGTH,
    DEFAULT_PAGE_SIZE,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_WAIT_TIMEOUT_MS,
    SLOW_REQUEST_THRESHOLD_MS,
    BatchResult,
    OutgoingRequest,
    Weclapp,
    __version__,
)
from .concurrency import ConcurrencyController, ConcurrencySettings, ConcurrencySnapshot, Signal
from .entity import JsonDict, WeclappEntity, WeclappResponse
from .errors import (
    WeclappAPIError,
    WeclappAuthenticationError,
    WeclappConcurrencyTimeoutError,
    WeclappError,
    WeclappNotFoundError,
    WeclappOptimisticLockError,
    WeclappPaginationError,
    WeclappRateLimitError,
    WeclappRedirectError,
    WeclappRequestTimeoutError,
    WeclappTransportError,
    WeclappValidationError,
)
from .metrics import ClientStats, RequestMetrics, StatsSnapshot
from .mime import MIME_TYPES, infer_content_type
from .retry import RetryPolicy, TransportOutcome, classify_transport_error

__all__ = [
    "DEFAULT_API_REQUEST_TIMEOUT_MS",
    "DEFAULT_ID_CHUNK_SIZE",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_MAX_URL_LENGTH",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_WAIT_TIMEOUT_MS",
    "MIME_TYPES",
    "SLOW_REQUEST_THRESHOLD_MS",
    "BatchResult",
    "ClientStats",
    "ConcurrencyController",
    "ConcurrencySettings",
    "ConcurrencySnapshot",
    "JsonDict",
    "OutgoingRequest",
    "RequestMetrics",
    "RetryPolicy",
    "Signal",
    "StatsSnapshot",
    "TransportOutcome",
    "Weclapp",
    "WeclappAPIError",
    "WeclappAuthenticationError",
    "WeclappConcurrencyTimeoutError",
    "WeclappEntity",
    "WeclappError",
    "WeclappNotFoundError",
    "WeclappOptimisticLockError",
    "WeclappPaginationError",
    "WeclappRateLimitError",
    "WeclappRedirectError",
    "WeclappRequestTimeoutError",
    "WeclappResponse",
    "WeclappTransportError",
    "WeclappValidationError",
    "__version__",
    "classify_transport_error",
    "infer_content_type",
]
