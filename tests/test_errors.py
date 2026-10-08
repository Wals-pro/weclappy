"""Exception hierarchy, subclass selection and problem-document parsing."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from fakeserver import make_response
from weclappy import (
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
from weclappy.errors import TRANSIENT_STATUS_CODES, problem_type_suffix

ERRORS = "https://api.weclapp.com/errors/"
API_SUBCLASSES = [
    WeclappTransportError,
    WeclappRateLimitError,
    WeclappNotFoundError,
    WeclappValidationError,
    WeclappOptimisticLockError,
    WeclappRequestTimeoutError,
    WeclappAuthenticationError,
    WeclappRedirectError,
    WeclappPaginationError,
]


@pytest.mark.parametrize("cls", API_SUBCLASSES)
def test_api_subclasses_derive_from_api_error(cls: type[Exception]) -> None:
    assert issubclass(cls, WeclappAPIError)
    assert issubclass(cls, WeclappError)


def test_root_hierarchy() -> None:
    assert issubclass(WeclappAPIError, WeclappError)
    assert issubclass(WeclappError, Exception)
    assert issubclass(WeclappConcurrencyTimeoutError, WeclappError)
    assert not issubclass(WeclappConcurrencyTimeoutError, WeclappAPIError)


def test_transient_status_codes() -> None:
    assert frozenset({429, 500, 502, 503, 504}) == TRANSIENT_STATUS_CODES


# ------------------------------------------------------- subclass selection
def _from(status: int, body: Any, **headers: str) -> WeclappAPIError:
    return WeclappAPIError.from_response("msg", make_response(status, body, headers=headers))


LOCK_DETAIL = "Optimistic lock error: entity was modified"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (429, {}, WeclappRateLimitError),
        (404, {}, WeclappNotFoundError),
        (401, {}, WeclappAuthenticationError),
        (403, {"type": f"{ERRORS}forbidden"}, WeclappAuthenticationError),
        (301, None, WeclappRedirectError),
        (302, {"detail": LOCK_DETAIL}, WeclappRedirectError),
        (307, None, WeclappRedirectError),
        (400, {"type": f"{ERRORS}validation"}, WeclappValidationError),
        (400, {"validationErrors": [{"message": "name missing"}]}, WeclappValidationError),
        (400, {"type": f"{ERRORS}request_timeout"}, WeclappRequestTimeoutError),
        (409, {"type": f"{ERRORS}persistence"}, WeclappAPIError),
        (409, {"type": f"{ERRORS}optimistic_lock"}, WeclappOptimisticLockError),
        (409, {"detail": LOCK_DETAIL}, WeclappOptimisticLockError),
        (409, {"error": "OPTIMISTIC LOCK ERROR"}, WeclappOptimisticLockError),
        (400, {"type": f"{ERRORS}optimistic_lock"}, WeclappOptimisticLockError),
        (400, {"detail": LOCK_DETAIL}, WeclappOptimisticLockError),
        (400, {}, WeclappAPIError),
        (409, {}, WeclappAPIError),
        (500, {}, WeclappAPIError),
        (503, "<html>gateway</html>", WeclappAPIError),
        (418, ["not", "a", "dict"], WeclappAPIError),
    ],
)
def test_from_response_selects_subclass(status: int, body: Any, expected: type) -> None:
    error = _from(status, body)
    assert type(error) is expected
    assert error.status_code == status
    assert str(error) == "msg"


def test_persistence_conflict_stays_base_but_is_flagged() -> None:
    error = _from(409, {"type": f"{ERRORS}persistence"})
    assert type(error) is WeclappAPIError
    assert error.is_persistence_error
    assert error.is_retryable
    assert not error.is_optimistic_lock


def test_from_response_on_a_subclass_never_returns_a_less_specific_class() -> None:
    response = make_response(500, {})
    error = WeclappNotFoundError.from_response("m", response)
    assert type(error) is WeclappNotFoundError


def test_from_response_on_a_subclass_still_picks_the_response_class() -> None:
    error = WeclappValidationError.from_response("m", make_response(429, {}))
    assert type(error) is WeclappRateLimitError


def test_from_response_uses_explicit_response_text() -> None:
    response = make_response(400, {})
    error = WeclappAPIError.from_response(
        "m", response, response_text='{"type": "/errors/validation", "detail": "bad"}'
    )
    assert type(error) is WeclappValidationError
    assert error.detail == "bad"
    assert error.response_text is not None
    assert "bad" in error.response_text


# ------------------------------------------------------------ parsed fields
def test_problem_fields_are_parsed() -> None:
    body = {
        "error": "Bad request",
        "detail": "the detail",
        "title": "Title",
        "type": f"{ERRORS}validation",
        "validationErrors": [{"message": "a"}],
        "messages": [{"message": "m", "severity": "ERROR"}],
    }
    response = make_response(400, body, url="https://acme.weclapp.com/webapp/api/v2/article")
    error = WeclappAPIError.from_response("m", response)
    assert error.response is response
    assert error.url == "https://acme.weclapp.com/webapp/api/v2/article"
    assert (error.error, error.detail, error.title) == ("Bad request", "the detail", "Title")
    assert error.error_type == f"{ERRORS}validation"
    assert error.validation_errors == [{"message": "a"}]
    assert error.messages == [{"message": "m", "severity": "ERROR"}]
    assert error.is_validation_error


def test_non_json_body_leaves_fields_empty() -> None:
    error = _from(502, "Bad Gateway")
    assert error.error is error.detail is error.title is error.error_type is None
    assert error.validation_errors == []
    assert error.response_text == "Bad Gateway"


def test_invalid_list_fields_are_ignored() -> None:
    error = _from(400, {"validationErrors": "oops", "messages": {"a": 1}, "error": 42})
    assert error.validation_errors == []
    assert error.messages == []
    assert error.error == "42"


def test_error_without_response() -> None:
    error = WeclappAPIError("plain")
    assert error.response is None
    assert error.status_code is None
    assert error.url is None
    assert error.wait_ms is None
    assert error.retry_after is None
    assert error.correlation_id is None
    assert not error.is_retryable


@pytest.mark.parametrize(
    ("status", "body", "predicates"),
    [
        (404, {}, {"is_not_found"}),
        (429, {}, {"is_rate_limited", "is_retryable"}),
        (503, {}, {"is_retryable"}),
        (400, {"type": f"{ERRORS}request_timeout"}, {"is_request_timeout", "is_retryable"}),
        (409, {"type": f"{ERRORS}optimistic_lock"}, {"is_optimistic_lock"}),
        (400, {"type": f"{ERRORS}validation"}, {"is_validation_error"}),
        (400, {}, set()),
    ],
)
def test_predicates(status: int, body: Any, predicates: set[str]) -> None:
    error = _from(status, body)
    names = {
        "is_not_found",
        "is_rate_limited",
        "is_retryable",
        "is_request_timeout",
        "is_optimistic_lock",
        "is_validation_error",
        "is_persistence_error",
    }
    assert {name for name in names if getattr(error, name)} == predicates


# ------------------------------------------------------------------ headers
@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1500", 1500.0), ("12.5", 12.5), ("0", 0.0), ("abc", None), ("", None)],
)
def test_wait_ms_is_parsed_as_float(raw: str, expected: float | None) -> None:
    error = _from(429, {}, **{"X-Weclapp-Wait-Ms": raw})
    assert error.wait_ms == expected
    if expected is not None:
        assert isinstance(error.wait_ms, float)


def test_wait_ms_absent() -> None:
    assert _from(429, {}).wait_ms is None


def test_header_accessors() -> None:
    error = _from(
        429,
        {},
        **{
            "Retry-After": "12",
            "X-Weclapp-Wait-Reason": "concurrency, load",
            "X-Request-Id": "req-1",
        },
    )
    assert error.retry_after == "12"
    assert error.wait_reason == "concurrency, load"
    assert error.correlation_id == "req-1"


def test_correlation_id_prefers_x_correlation_id() -> None:
    error = _from(500, {}, **{"X-Correlation-ID": "corr", "X-Request-ID": "req"})
    assert error.correlation_id == "corr"


# ----------------------------------------------------------------- messages
def test_get_validation_messages() -> None:
    error = _from(
        400,
        {
            "validationErrors": [
                {"message": "from message"},
                {"error": "from error"},
                {"other": 1},
                "plain string",
            ]
        },
    )
    assert error.get_validation_messages() == [
        "from message",
        "from error",
        "{'other': 1}",
        "plain string",
    ]


def test_get_all_messages_dedupes_detail_and_formats_severity() -> None:
    error = _from(
        400,
        {
            "error": "same",
            "detail": "same",
            "validationErrors": [{"message": "v"}],
            "messages": [{"message": "w", "severity": "WARNING"}, {"message": "x"}, "raw"],
        },
    )
    assert error.get_all_messages() == ["same", "v", "[WARNING] w", "x", "raw"]


def test_get_all_messages_keeps_distinct_detail() -> None:
    error = _from(400, {"error": "e", "detail": "d"})
    assert error.get_all_messages() == ["e", "d"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (f"{ERRORS}Validation/", "validation"),
        ("/errors/optimistic_lock", "optimistic_lock"),
        ("persistence", "persistence"),
        (None, ""),
        (42, ""),
    ],
)
def test_problem_type_suffix(value: object, expected: str) -> None:
    assert problem_type_suffix(value) == expected


# ---------------------------------------------------------------- transport
@pytest.mark.parametrize("sent", [True, False])
def test_transport_error_flags(sent: bool) -> None:
    cause = requests.exceptions.ReadTimeout("slow")
    error = WeclappTransportError("failed", request_sent=sent, cause=cause)
    assert error.request_sent is sent
    assert error.outcome_unknown is sent
    assert error.__cause__ is cause
    assert error.status_code is None
    assert error.response is None
    assert isinstance(error, WeclappAPIError)
    assert str(error) == "failed"


def test_transport_error_requires_keyword_flag() -> None:
    with pytest.raises(TypeError):
        WeclappTransportError("failed", True)  # type: ignore[misc]
