"""RetryPolicy, transport classification and per-response retry decisions."""

from __future__ import annotations

import http.client
import math
import socket
import time
from email.utils import formatdate
from typing import Any

import pytest
import requests
from urllib3.exceptions import (
    ConnectTimeoutError,
    MaxRetryError,
    NameResolutionError,
    NewConnectionError,
    ProtocolError,
)

from fakeserver import make_response
from weclappy import RetryPolicy, TransportOutcome, classify_transport_error
from weclappy import retry as retry_module
from weclappy.retry import (
    RetryKind,
    RetryState,
    decide_for_exception,
    decide_for_response,
    rate_limit_cooldown,
    retry_after_seconds,
)

NO_JITTER = RetryPolicy(jitter=False)


def problem_response(status: int, suffix: str, **headers: str) -> requests.Response:
    body = {"type": f"https://api.weclapp.com/errors/{suffix}"}
    return make_response(status, body, headers=headers)


# --------------------------------------------------------------- validation
def test_defaults() -> None:
    policy = RetryPolicy()
    assert (policy.max_retries, policy.rate_limit_retries, policy.problem_retries) == (3, 5, 1)
    assert (policy.backoff_factor, policy.rate_limit_backoff, policy.max_backoff) == (
        0.3,
        2.0,
        60.0,
    )
    assert policy.jitter is True


@pytest.mark.parametrize("name", ["max_retries", "rate_limit_retries", "problem_retries"])
@pytest.mark.parametrize("value", [-1, 1.5, True, "3", None])
def test_counts_must_be_non_negative_integers(name: str, value: Any) -> None:
    with pytest.raises(ValueError, match=name):
        RetryPolicy(**{name: value})


@pytest.mark.parametrize("name", ["backoff_factor", "rate_limit_backoff", "max_backoff"])
@pytest.mark.parametrize("value", [-0.1, math.inf, math.nan, "1", None])
def test_delays_must_be_finite_non_negative(name: str, value: Any) -> None:
    with pytest.raises(ValueError, match=name):
        RetryPolicy(**{name: value})


def test_zero_values_are_allowed() -> None:
    policy = RetryPolicy(max_retries=0, backoff_factor=0, rate_limit_backoff=0, max_backoff=0)
    assert policy.delay(RetryKind.TRANSIENT, 3) == 0


def test_budgets_per_kind() -> None:
    policy = RetryPolicy(max_retries=2, rate_limit_retries=7, problem_retries=4)
    assert policy.budget(RetryKind.TRANSIENT) == 2
    assert policy.budget(RetryKind.RATE_LIMIT) == 7
    assert policy.budget(RetryKind.PROBLEM) == 4


# ------------------------------------------------------------------- delays
@pytest.mark.parametrize(
    ("kind", "attempt", "expected"),
    [
        (RetryKind.TRANSIENT, 0, 0.3),
        (RetryKind.TRANSIENT, 1, 0.6),
        (RetryKind.TRANSIENT, 2, 1.2),
        (RetryKind.PROBLEM, 1, 0.6),
        (RetryKind.RATE_LIMIT, 0, 2.0),
        (RetryKind.RATE_LIMIT, 2, 8.0),
        (RetryKind.RATE_LIMIT, 5, 60.0),
        (RetryKind.TRANSIENT, 30, 60.0),
    ],
)
def test_exponential_delays_without_jitter(kind: RetryKind, attempt: int, expected: float) -> None:
    assert NO_JITTER.delay(kind, attempt) == pytest.approx(expected)


def test_jitter_adds_at_most_one_base_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[float, float]] = []

    def upper(low: float, high: float) -> float:
        calls.append((low, high))
        return high

    monkeypatch.setattr(retry_module.random, "uniform", upper)
    policy = RetryPolicy()
    assert policy.delay(RetryKind.TRANSIENT, 1) == pytest.approx(0.6 + 0.3)
    assert policy.delay(RetryKind.RATE_LIMIT, 0) == pytest.approx(2.0 + 2.0)
    assert calls == [(0, 0.3), (0, 2.0)]


def test_jitter_samples_stay_within_bounds() -> None:
    policy = RetryPolicy()
    samples = [policy.delay(RetryKind.TRANSIENT, 2) for _ in range(200)]
    assert all(1.2 <= sample <= 1.5 for sample in samples)
    assert len(set(samples)) > 1


def test_cap_includes_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retry_module.random, "uniform", lambda low, high: high)
    policy = RetryPolicy(rate_limit_backoff=50, max_backoff=60)
    assert policy.delay(RetryKind.RATE_LIMIT, 0) == 60


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (math.inf, None),
        (-math.inf, None),
        (math.nan, None),
        (-3, 0),
        (5, 5),
        (1e9, 60),
    ],
)
def test_cap(value: float | None, expected: float | None) -> None:
    assert RetryPolicy().cap(value) == expected


# -------------------------------------------------------------- Retry-After
def _with_retry_after(value: str, status: int = 429) -> requests.Response:
    return make_response(status, {}, headers={"Retry-After": value})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5", 5.0),
        ("0", 0.0),
        ("2.5", 2.5),
        ("-3", 0.0),
        ("garbage", None),
        ("", None),
        ("inf", None),
        ("nan", None),
    ],
)
def test_retry_after_seconds(value: str, expected: float | None) -> None:
    assert retry_after_seconds(_with_retry_after(value)) == expected


def test_retry_after_absent() -> None:
    assert retry_after_seconds(make_response(429, {})) is None


def test_retry_after_http_date_in_the_future() -> None:
    value = formatdate(time.time() + 30, usegmt=True)
    assert retry_after_seconds(_with_retry_after(value)) == pytest.approx(30, abs=2)


def test_retry_after_http_date_in_the_past_is_zero() -> None:
    value = formatdate(time.time() - 3600, usegmt=True)
    assert retry_after_seconds(_with_retry_after(value)) == 0.0


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [
        ("5", 5.0),
        ("1000000000", 60.0),
        ("inf", 2.0),  # non-finite is ignored -> computed backoff
        ("1e400", 2.0),
        (formatdate(time.time() + 86_400, usegmt=True), 60.0),
        ("nonsense", 2.0),
    ],
)
def test_429_delay_honours_and_caps_retry_after(retry_after: str, expected: float) -> None:
    decision = decide_for_response(
        NO_JITTER, RetryState(), _with_retry_after(retry_after), is_read=True
    )
    assert decision.retry
    assert decision.delay == pytest.approx(expected)


def test_nan_retry_after_is_ignored() -> None:
    """Regression: max(0.0, nan) used to turn ``Retry-After: nan`` into an immediate retry."""
    decision = decide_for_response(NO_JITTER, RetryState(), _with_retry_after("nan"), is_read=True)
    assert decision.delay == pytest.approx(2.0)


def test_retry_after_on_5xx_is_capped_too() -> None:
    response = _with_retry_after("99999", status=503)
    decision = decide_for_response(NO_JITTER, RetryState(), response, is_read=True)
    assert decision.kind is RetryKind.TRANSIENT
    assert decision.delay == 60.0


# ----------------------------------------------------- transport classifier
def _gaierror() -> socket.gaierror:
    return socket.gaierror(8, "nodename nor servname provided")


TRANSPORT_MATRIX: list[tuple[str, requests.RequestException, TransportOutcome]] = [
    ("connect-timeout", requests.exceptions.ConnectTimeout("t"), TransportOutcome.NOT_SENT),
    (
        "new-connection",
        requests.exceptions.ConnectionError(NewConnectionError(None, "refused")),  # type: ignore[arg-type]
        TransportOutcome.NOT_SENT,
    ),
    (
        "name-resolution",
        requests.exceptions.ConnectionError(
            NameResolutionError("acme.weclapp.com", None, _gaierror())  # type: ignore[arg-type]
        ),
        TransportOutcome.NOT_SENT,
    ),
    (
        "urllib3-connect-timeout",
        requests.exceptions.ConnectionError(ConnectTimeoutError("connect timed out")),
        TransportOutcome.NOT_SENT,
    ),
    (
        "max-retry-new-connection",
        requests.exceptions.ConnectionError(
            MaxRetryError(None, "/x", reason=NewConnectionError(None, "refused"))  # type: ignore[arg-type]
        ),
        TransportOutcome.NOT_SENT,
    ),
    (
        "max-retry-name-resolution",
        requests.exceptions.ConnectionError(
            MaxRetryError(
                None,  # type: ignore[arg-type]
                "/x",
                reason=NameResolutionError("h", None, _gaierror()),  # type: ignore[arg-type]
            )
        ),
        TransportOutcome.NOT_SENT,
    ),
    (
        "remote-disconnected",
        requests.exceptions.ConnectionError(
            ProtocolError("Connection aborted.", http.client.RemoteDisconnected("closed"))
        ),
        TransportOutcome.UNKNOWN,
    ),
    (
        "max-retry-protocol",
        requests.exceptions.ConnectionError(
            MaxRetryError(None, "/x", reason=ProtocolError("reset"))  # type: ignore[arg-type]
        ),
        TransportOutcome.UNKNOWN,
    ),
    ("plain-connection-error", requests.exceptions.ConnectionError("?"), TransportOutcome.UNKNOWN),
    ("read-timeout", requests.exceptions.ReadTimeout("r"), TransportOutcome.UNKNOWN),
    ("chunked", requests.exceptions.ChunkedEncodingError("c"), TransportOutcome.UNKNOWN),
    ("generic", requests.exceptions.RequestException("g"), TransportOutcome.UNKNOWN),
    ("ssl", requests.exceptions.SSLError("cert"), TransportOutcome.NOT_RETRYABLE),
    (
        "ssl-wrapping-new-connection",
        requests.exceptions.SSLError(NewConnectionError(None, "x")),  # type: ignore[arg-type]
        TransportOutcome.NOT_RETRYABLE,
    ),
]


@pytest.mark.parametrize(
    ("exc", "expected"),
    [pytest.param(exc, expected, id=name) for name, exc, expected in TRANSPORT_MATRIX],
)
def test_classify_transport_error(
    exc: requests.RequestException, expected: TransportOutcome
) -> None:
    assert classify_transport_error(exc) is expected


def test_classify_follows_the_cause_chain() -> None:
    exc = requests.exceptions.ConnectionError("wrapped")
    exc.__cause__ = NewConnectionError(None, "refused")  # type: ignore[arg-type]
    assert classify_transport_error(exc) is TransportOutcome.NOT_SENT


def test_classify_survives_cyclic_chains() -> None:
    exc = requests.exceptions.ConnectionError("cycle")
    other = ProtocolError("p")
    exc.__context__ = other
    other.__context__ = exc
    assert classify_transport_error(exc) is TransportOutcome.UNKNOWN


# -------------------------------------------------------- exception policy
REFUSED = requests.exceptions.ConnectionError(NewConnectionError(None, "refused"))  # type: ignore[arg-type]
READ_TIMEOUT = requests.exceptions.ReadTimeout("read")
SSL = requests.exceptions.SSLError("ssl")


@pytest.mark.parametrize(
    ("exc", "is_read", "retry"),
    [
        (REFUSED, True, True),
        (REFUSED, False, True),
        (READ_TIMEOUT, True, True),
        (READ_TIMEOUT, False, False),
        (requests.exceptions.ChunkedEncodingError("c"), False, False),
        (SSL, True, False),
        (SSL, False, False),
    ],
)
def test_decide_for_exception(exc: requests.RequestException, is_read: bool, retry: bool) -> None:
    decision = decide_for_exception(NO_JITTER, RetryState(), exc, is_read=is_read)
    assert decision.retry is retry
    if retry:
        assert decision.kind is RetryKind.TRANSIENT
        assert decision.delay == pytest.approx(0.3)
        assert type(exc).__name__ in decision.reason


def test_exception_budget_is_exhausted_after_max_retries() -> None:
    state = RetryState()
    policy = RetryPolicy(max_retries=2, jitter=False)
    delays = [decide_for_exception(policy, state, READ_TIMEOUT, is_read=True) for _ in range(3)]
    assert [d.retry for d in delays] == [True, True, False]
    assert [d.delay for d in delays[:2]] == pytest.approx([0.3, 0.6])
    assert state.used(RetryKind.TRANSIENT) == 2


def test_write_never_charges_budget_for_unknown_outcome() -> None:
    state = RetryState()
    decide_for_exception(NO_JITTER, state, READ_TIMEOUT, is_read=False)
    assert state.total == 0


# --------------------------------------------------------- response policy
@pytest.mark.parametrize(
    "response",
    [
        make_response(429, {}),
        make_response(500, {}),
        make_response(502, {}),
        make_response(503, {}),
        make_response(504, {}),
        make_response(302, None, headers={"Location": "https://elsewhere"}),
        problem_response(400, "request_timeout"),
        problem_response(409, "persistence"),
    ],
    ids=["429", "500", "502", "503", "504", "302", "request_timeout", "persistence"],
)
def test_writes_never_retry_on_any_status(response: requests.Response) -> None:
    state = RetryState()
    assert decide_for_response(NO_JITTER, state, response, is_read=False).retry is False
    assert state.total == 0


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (make_response(429, {}), RetryKind.RATE_LIMIT),
        (make_response(500, {}), RetryKind.TRANSIENT),
        (make_response(502, {}), RetryKind.TRANSIENT),
        (make_response(503, {}), RetryKind.TRANSIENT),
        (make_response(504, {}), RetryKind.TRANSIENT),
        (problem_response(400, "request_timeout"), RetryKind.PROBLEM),
        (problem_response(409, "persistence"), RetryKind.PROBLEM),
        (problem_response(400, "validation"), None),
        (problem_response(409, "optimistic_lock"), None),
        (problem_response(400, "persistence"), None),
        (problem_response(409, "request_timeout"), None),
        (make_response(404, {}), None),
        (make_response(401, {}), None),
        (make_response(302, None), None),
        (make_response(400, "not json"), None),
        (make_response(400, ["list"]), None),
    ],
)
def test_reads_retry_per_status(response: requests.Response, kind: RetryKind | None) -> None:
    decision = decide_for_response(NO_JITTER, RetryState(), response, is_read=True)
    assert decision.retry is (kind is not None)
    assert decision.kind is kind


def test_rate_limit_budget_is_separate_from_transient() -> None:
    policy = RetryPolicy(max_retries=1, rate_limit_retries=2, jitter=False)
    state = RetryState()
    assert decide_for_response(policy, state, make_response(503, {}), is_read=True).retry
    assert not decide_for_response(policy, state, make_response(503, {}), is_read=True).retry
    first = decide_for_response(policy, state, make_response(429, {}), is_read=True)
    second = decide_for_response(policy, state, make_response(429, {}), is_read=True)
    third = decide_for_response(policy, state, make_response(429, {}), is_read=True)
    assert (first.retry, second.retry, third.retry) == (True, True, False)
    assert (first.delay, second.delay) == (2.0, 4.0)
    assert state.attempts == {RetryKind.TRANSIENT: 1, RetryKind.RATE_LIMIT: 2}


def test_problem_retries_have_their_own_budget_and_transient_delays() -> None:
    policy = RetryPolicy(max_retries=0, problem_retries=2, jitter=False)
    state = RetryState()
    timeout = problem_response(400, "request_timeout")
    decisions = [decide_for_response(policy, state, timeout, is_read=True) for _ in range(3)]
    assert [d.retry for d in decisions] == [True, True, False]
    assert [d.delay for d in decisions[:2]] == pytest.approx([0.3, 0.6])
    assert decisions[0].reason == "400/request_timeout"
    assert not decide_for_response(policy, state, make_response(503, {}), is_read=True).retry


def test_problem_type_matching_is_case_and_slash_insensitive() -> None:
    response = make_response(409, {"type": "https://api.weclapp.com/errors/Persistence/"})
    decision = decide_for_response(NO_JITTER, RetryState(), response, is_read=True)
    assert decision.kind is RetryKind.PROBLEM


# ------------------------------------------------------------- misc helpers
def test_retry_state_counts() -> None:
    state = RetryState()
    assert state.charge(RetryKind.TRANSIENT) == 0
    assert state.charge(RetryKind.TRANSIENT) == 1
    assert state.charge(RetryKind.RATE_LIMIT) == 0
    assert state.used(RetryKind.PROBLEM) == 0
    assert state.total == 3


def test_rate_limit_cooldown_prefers_capped_retry_after() -> None:
    state = RetryState()
    assert rate_limit_cooldown(NO_JITTER, _with_retry_after("7"), state) == 7.0
    assert rate_limit_cooldown(NO_JITTER, _with_retry_after("9999"), state) == 60.0


def test_rate_limit_cooldown_falls_back_to_the_next_backoff_step() -> None:
    state = RetryState()
    assert rate_limit_cooldown(NO_JITTER, make_response(429, {}), state) == 2.0
    state.charge(RetryKind.RATE_LIMIT)
    assert rate_limit_cooldown(NO_JITTER, make_response(429, {}), state) == 4.0


def test_policy_is_frozen() -> None:
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        NO_JITTER.max_retries = 9  # type: ignore[misc]
