"""Exception hierarchy for weclappy.

Every error raised by the library derives from :class:`WeclappError`.
Errors that originate from a request lifecycle derive from
:class:`WeclappAPIError`, which keeps the structured problem details weclapp
returns (``type``, ``title``, ``detail``, ``validationErrors`` ...) and exposes
convenience predicates such as :attr:`WeclappAPIError.is_optimistic_lock`.

``except WeclappAPIError`` therefore still catches transport failures,
rate limits, pagination inconsistencies and HTTP errors alike, while the
typed subclasses allow precise handling where a caller needs it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import requests

__all__ = [
    "TRANSIENT_STATUS_CODES",
    "WeclappAPIError",
    "WeclappAuthenticationError",
    "WeclappConcurrencyTimeoutError",
    "WeclappError",
    "WeclappNotFoundError",
    "WeclappOptimisticLockError",
    "WeclappPaginationError",
    "WeclappRateLimitError",
    "WeclappRedirectError",
    "WeclappRequestTimeoutError",
    "WeclappTransportError",
    "WeclappValidationError",
    "problem_type_suffix",
]

TRANSIENT_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

_CORRELATION_HEADERS = ("X-Correlation-ID", "X-Correlation-Id", "X-Request-ID", "X-Request-Id")


def problem_type_suffix(value: object) -> str:
    """Return the last path segment of a weclapp problem ``type`` URI, lower-cased."""
    if not isinstance(value, str):
        return ""
    return value.rstrip("/").rsplit("/", 1)[-1].strip().lower()


@dataclass(slots=True)
class _ProblemDetails:
    """Parsed weclapp problem document (RFC 7807-like)."""

    error: str | None = None
    detail: str | None = None
    title: str | None = None
    error_type: str | None = None
    validation_errors: list[Any] = field(default_factory=list)
    messages: list[Any] = field(default_factory=list)

    @classmethod
    def parse(cls, response_text: str | None) -> _ProblemDetails:
        if not response_text:
            return cls()
        try:
            payload = json.loads(response_text)
        except ValueError:
            return cls()
        if not isinstance(payload, dict):
            return cls()
        validation_errors = payload.get("validationErrors") or []
        messages = payload.get("messages") or []
        return cls(
            error=_optional_str(payload.get("error")),
            detail=_optional_str(payload.get("detail")),
            title=_optional_str(payload.get("title")),
            error_type=_optional_str(payload.get("type")),
            validation_errors=validation_errors if isinstance(validation_errors, list) else [],
            messages=messages if isinstance(messages, list) else [],
        )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


class WeclappError(Exception):
    """Base class for every exception raised by weclappy."""


class WeclappAPIError(WeclappError):
    """An error that occurred while performing a weclapp API request.

    Attributes:
        response: The :class:`requests.Response` object, if a response was received.
        response_text: The raw response body text, if available.
        status_code: The HTTP status code, or ``None`` for transport-level failures.
        url: The request URL that caused the error, if known.
        error: ``error`` field from the weclapp problem document.
        detail: ``detail`` field from the weclapp problem document.
        title: ``title`` field from the weclapp problem document.
        error_type: ``type`` field (a URI such as ``/errors/validation``).
        validation_errors: ``validationErrors`` list from the problem document.
        messages: ``messages`` list from the problem document.
    """

    #: Marker weclapp puts into ``detail``/``error`` for optimistic-lock conflicts.
    OPTIMISTIC_LOCK_IDENTIFIER = "Optimistic lock error"

    def __init__(
        self,
        message: str,
        response: requests.Response | None = None,
        response_text: str | None = None,
        *,
        _details: _ProblemDetails | None = None,
    ) -> None:
        self.response = _redact_credentials(response)
        if response_text is None and response is not None:
            response_text = response.text
        self.response_text = response_text
        self.status_code: int | None = response.status_code if response is not None else None
        self.url: str | None = str(response.url) if response is not None else None

        details = _details if _details is not None else _ProblemDetails.parse(response_text)
        self.error = details.error
        self.detail = details.detail
        self.title = details.title
        self.error_type = details.error_type
        self.validation_errors: list[Any] = details.validation_errors
        self.messages: list[Any] = details.messages
        super().__init__(message)

    # ------------------------------------------------------------------ factory
    @classmethod
    def from_response(
        cls,
        message: str,
        response: requests.Response,
        response_text: str | None = None,
    ) -> WeclappAPIError:
        """Build the most specific error subclass for ``response``.

        Subclass selection uses the HTTP status and the weclapp problem type.
        Calling this on a subclass still returns the subclass picked for the
        response, never a less specific one.
        """
        if response_text is None:
            response_text = response.text
        details = _ProblemDetails.parse(response_text)
        error_class = _select_error_class(response.status_code, details)
        if issubclass(cls, error_class):
            error_class = cls
        return error_class(message, response, response_text, _details=details)

    # --------------------------------------------------------------- predicates
    @property
    def is_optimistic_lock(self) -> bool:
        """Whether weclapp reported a version conflict (``optimistic_lock``)."""
        return _is_optimistic_lock(self.error_type, self.detail, self.error)

    @property
    def is_not_found(self) -> bool:
        """Whether the server answered 404."""
        return self.status_code == 404

    @property
    def is_validation_error(self) -> bool:
        """Whether weclapp returned validation problems."""
        return problem_type_suffix(self.error_type) == "validation" or bool(self.validation_errors)

    @property
    def is_rate_limited(self) -> bool:
        """Whether the server answered 429."""
        return self.status_code == 429

    @property
    def is_request_timeout(self) -> bool:
        """Whether weclapp classified the request as a transient ``request_timeout``."""
        return problem_type_suffix(self.error_type) == "request_timeout"

    @property
    def is_persistence_error(self) -> bool:
        """Whether weclapp classified the response as a ``persistence`` conflict."""
        return problem_type_suffix(self.error_type) == "persistence"

    @property
    def is_retryable(self) -> bool:
        """Whether the failure is transient in principle.

        Callers must still decide whether repeating the operation is safe; the
        library never repeats writes automatically on these conditions.
        """
        return (
            self.status_code in TRANSIENT_STATUS_CODES
            or self.is_request_timeout
            or self.is_persistence_error
        )

    # ------------------------------------------------------------ header access
    @property
    def retry_after(self) -> str | None:
        """Raw ``Retry-After`` header, if the response carried one."""
        return self._response_header("Retry-After")

    @property
    def wait_ms(self) -> float | None:
        """weclapp's reported queue wait (``X-Weclapp-Wait-Ms``) in milliseconds."""
        raw = self._response_header("X-Weclapp-Wait-Ms")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    @property
    def wait_reason(self) -> str | None:
        """weclapp's reported queue reason (``X-Weclapp-Wait-Reason``), if present."""
        return self._response_header("X-Weclapp-Wait-Reason")

    @property
    def correlation_id(self) -> str | None:
        """A request/correlation identifier header, if the response carried one."""
        for header in _CORRELATION_HEADERS:
            value = self._response_header(header)
            if value:
                return value
        return None

    def _response_header(self, name: str) -> str | None:
        if self.response is None:
            return None
        headers = getattr(self.response, "headers", None)
        if not headers or not hasattr(headers, "get"):
            return None
        value = headers.get(name)
        return str(value) if value is not None else None

    # ----------------------------------------------------------------- messages
    def get_validation_messages(self) -> list[str]:
        """Human-readable validation messages."""
        messages: list[str] = []
        for error in self.validation_errors:
            if isinstance(error, dict):
                messages.append(str(error.get("message") or error.get("error") or error))
            else:
                messages.append(str(error))
        return messages

    def get_all_messages(self) -> list[str]:
        """All messages: ``error``, ``detail``, validation messages and ``messages``."""
        all_messages: list[str] = []
        if self.error:
            all_messages.append(self.error)
        if self.detail and self.detail != self.error:
            all_messages.append(self.detail)
        all_messages.extend(self.get_validation_messages())
        for msg in self.messages:
            if isinstance(msg, dict):
                text = str(msg.get("message", msg))
                severity = msg.get("severity", "")
                all_messages.append(f"[{severity}] {text}" if severity else text)
            else:
                all_messages.append(str(msg))
        return all_messages


class WeclappTransportError(WeclappAPIError):
    """The request failed below HTTP: connection, DNS, TLS or read failures.

    Attributes:
        request_sent: ``True`` when the request may have reached weclapp.
        outcome_unknown: ``True`` when the request may have been processed
            although no response arrived (read timeout, connection dropped
            after sending). For writes this means: read the entity back
            before deciding whether to repeat the operation.
    """

    def __init__(
        self,
        message: str,
        *,
        request_sent: bool,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.request_sent = request_sent
        self.outcome_unknown = request_sent
        self.__cause__ = cause


class WeclappRateLimitError(WeclappAPIError):
    """weclapp answered 429 after queueing the request."""


class WeclappNotFoundError(WeclappAPIError):
    """The entity does not exist (404, or an empty ``id-eq`` lookup)."""


class WeclappValidationError(WeclappAPIError):
    """weclapp rejected the payload with validation problems."""


class WeclappOptimisticLockError(WeclappAPIError):
    """The entity ``version`` sent with a write is stale."""


class WeclappRequestTimeoutError(WeclappAPIError):
    """weclapp aborted the request server-side (``request_timeout``)."""


class WeclappAuthenticationError(WeclappAPIError):
    """The API key is invalid or lacks permission (401/403)."""


class WeclappRedirectError(WeclappAPIError):
    """weclapp answered with a redirect, which weclappy never follows."""


class WeclappPaginationError(WeclappAPIError):
    """A paginated read returned an inconsistent data set.

    Raised for duplicate ids between pages, for a shortfall against the
    pre-fetch count, and when ``max_records`` would be exceeded.
    """


class WeclappConcurrencyTimeoutError(WeclappError):
    """No read permit became available before the client timeout elapsed."""


def _redact_credentials(response: requests.Response | None) -> requests.Response | None:
    """Strip the API token from the request attached to a response.

    Exceptions travel into logs and error reporters; the response object they
    carry must not reveal the credential that produced it.
    """
    if response is None:
        return None
    request = getattr(response, "request", None)
    headers = getattr(request, "headers", None)
    if headers is not None and "AuthenticationToken" in headers:
        headers["AuthenticationToken"] = "<redacted>"
    return response


def _is_optimistic_lock(error_type: str | None, detail: str | None, error: str | None) -> bool:
    if problem_type_suffix(error_type) == "optimistic_lock":
        return True
    marker = WeclappAPIError.OPTIMISTIC_LOCK_IDENTIFIER.lower()
    return any(marker in text.lower() for text in (detail, error) if text)


def _select_error_class(status_code: int, details: _ProblemDetails) -> type[WeclappAPIError]:
    if 300 <= status_code < 400:
        return WeclappRedirectError
    if _is_optimistic_lock(details.error_type, details.detail, details.error):
        return WeclappOptimisticLockError
    suffix = problem_type_suffix(details.error_type)
    match status_code:
        case 429:
            return WeclappRateLimitError
        case 404:
            return WeclappNotFoundError
        case 401 | 403:
            return WeclappAuthenticationError
        case 400 if suffix == "request_timeout":
            return WeclappRequestTimeoutError
        case 400 if suffix == "validation" or details.validation_errors:
            return WeclappValidationError
    return WeclappAPIError
