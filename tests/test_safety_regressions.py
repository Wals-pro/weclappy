"""Offline regression tests for safety-critical weclappy contracts.

These tests deliberately mock the transport (``session.request``). They cover
behaviour that must not depend on a live tenant and are kept separate from
broad feature tests so the security/reliability contract remains easy to audit.
"""

import contextlib
import inspect
import threading
from typing import get_overloads, get_type_hints
from unittest.mock import MagicMock, patch

import pytest
import requests
from urllib3.exceptions import MaxRetryError, NewConnectionError

import weclappy
from weclappy import (
    ConcurrencyController,
    ConcurrencySettings,
    RetryPolicy,
    Signal,
    Weclapp,
    WeclappAPIError,
    WeclappEntity,
    WeclappRateLimitError,
    WeclappResponse,
    WeclappTransportError,
)

BASE_URL = "https://tenant.weclapp.com/webapp/api/v2"
API_ROOT = f"{BASE_URL}/"
SLEEP = "weclappy.client.time.sleep"


def _unsent_connection_error() -> requests.exceptions.ConnectionError:
    """What requests raises when the TCP connection could not be opened."""
    return requests.exceptions.ConnectionError(
        MaxRetryError(None, f"{API_ROOT}article", reason=NewConnectionError(None, "refused"))
    )


# ---------------------------------------------------------------- public surface


def test_package_exports_the_documented_public_surface():
    expected = {
        "Weclapp",
        "WeclappAPIError",
        "WeclappEntity",
        "WeclappResponse",
        "WeclappTransportError",
        "WeclappRateLimitError",
        "WeclappPaginationError",
        "WeclappConcurrencyTimeoutError",
        "ConcurrencyController",
        "ConcurrencySettings",
        "RetryPolicy",
        "Signal",
        "StatsSnapshot",
        "RequestMetrics",
        "BatchResult",
        "MIME_TYPES",
        "infer_content_type",
        "__version__",
    }

    assert expected <= set(weclappy.__all__)
    assert len(weclappy.__all__) == len(set(weclappy.__all__))
    assert all(hasattr(weclappy, name) for name in weclappy.__all__)


def test_public_overload_annotations_are_runtime_resolvable():
    assert get_type_hints(Weclapp.get)
    for method in (Weclapp.get, Weclapp.get_all):
        overloads = get_overloads(method)
        assert overloads
        assert all(get_type_hints(candidate) for candidate in overloads)


def test_get_all_defaults_to_auto_pagination_with_keyword_only_options():
    parameters = inspect.signature(Weclapp.get_all).parameters

    assert parameters["threaded"].default == "auto"
    assert parameters["max_workers"].default is None
    for name in ("limit", "threaded", "max_workers", "return_weclapp_response"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_auto_pagination_skips_the_count_when_the_first_page_is_short(make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, {"result": [{"id": "1"}]})

    rows = api.get_all("article", {"pageSize": 2})

    assert [row.id for row in rows] == ["1"]
    transport.assert_called_once()
    assert transport.call_args.args[1] == f"{API_ROOT}article"


# ------------------------------------------------------- concurrency controller


def test_queue_feedback_maps_to_controller_signals():
    signal = ConcurrencyController.signal_from_response

    assert signal(200, {"X-Weclapp-Wait-Reason": "concurrency"}) is Signal.CONCURRENCY
    assert signal(200, {"X-Weclapp-Wait-Ms": "300"}) is Signal.CONCURRENCY
    assert signal(200, {"X-Weclapp-Wait-Reason": "load"}) is Signal.LOAD
    assert signal(200, {"X-Weclapp-Wait-Ms": "2200"}) is Signal.LOAD
    assert signal(429, {}) is Signal.RATE_LIMITED
    assert signal(503, {}) is Signal.ERROR
    assert signal(200, {}) is Signal.OK


def test_controller_reacts_to_queue_feedback_once_per_epoch():
    settings = ConcurrencySettings(max_concurrency=8, initial_concurrency=4)

    concurrency = ConcurrencyController(settings)
    concurrency.observe(Signal.CONCURRENCY)
    assert concurrency.target == 3
    # A second decrease inside the same epoch is ignored: in-flight responses
    # carrying the same signal must not cascade the target down to one.
    concurrency.observe(Signal.LOAD)
    assert concurrency.target == 3

    load = ConcurrencyController(settings)
    load.observe(Signal.LOAD)
    assert load.target == 2


def test_controller_ignores_invalid_queue_headers():
    headers = {"X-Weclapp-Wait-Ms": "not-a-number", "X-Weclapp-Wait-Reason": "unknown"}
    controller = ConcurrencyController(ConcurrencySettings(max_concurrency=4))

    signal = ConcurrencyController.signal_from_response(400, headers)
    controller.observe(signal)

    assert signal is Signal.OK
    assert ConcurrencyController.wait_ms_from_headers(headers) is None
    assert controller.target == 2


def test_controller_shares_rate_limit_cooldown_between_clients():
    controller = ConcurrencyController(ConcurrencySettings(max_concurrency=4), clock=lambda: 10.0)
    first = Weclapp(BASE_URL, "secret-token", concurrency=controller)
    second = Weclapp(BASE_URL, "secret-token", concurrency=controller)

    controller.observe(Signal.RATE_LIMITED, cooldown=3.0)

    assert first.concurrency is second.concurrency is controller
    assert controller.target == 1
    assert controller.snapshot().cooldown_remaining == 3.0
    controller.observe(Signal.RATE_LIMITED, cooldown=0.5)
    # The configured minimum never shortens an already running cooldown.
    assert controller.snapshot().cooldown_remaining == 3.0


# ------------------------------------------------------------- URL confinement


def test_leading_slash_stays_relative_to_api_root(make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, {"result": []})

    assert api.get("/article") == []

    assert transport.call_args.args[:2] == ("GET", f"{API_ROOT}article")


ENTITY_ENTRYPOINTS = [
    lambda api, endpoint: api.get(endpoint),
    lambda api, endpoint: api.get_all(endpoint, limit=1),
    lambda api, endpoint: api.post(endpoint, {}),
    lambda api, endpoint: api.put(endpoint, "1", {}),
    lambda api, endpoint: api.delete(endpoint, "1"),
    lambda api, endpoint: api.call_method(endpoint, "count"),
    lambda api, endpoint: api.upload(endpoint, b"data"),
    lambda api, endpoint: api.download(endpoint),
]


@pytest.mark.parametrize("invoke", ENTITY_ENTRYPOINTS)
def test_entity_entrypoints_reject_absolute_urls(invoke, make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, handler=MagicMock(side_effect=AssertionError("network")))

    with pytest.raises(ValueError, match=r"(?i)(origin|host|relative|url)"):
        invoke(api, "https://attacker.example/collect")

    transport.assert_not_called()


@pytest.mark.parametrize("invoke", ENTITY_ENTRYPOINTS)
@pytest.mark.parametrize(
    "endpoint",
    ["//attacker.example/collect", "https://attacker.example/collect", "/article"],
)
def test_entity_entrypoints_never_leave_the_tenant_origin(
    invoke, endpoint, make_client, fake_transport
):
    # Entity names are path segments: a protocol-relative "//host/x" is
    # stripped to the relative path "host/x" under the API root.
    api = make_client()
    transport = fake_transport(api, handler=lambda method, url, **kwargs: {"result": []})

    with contextlib.suppress(ValueError):
        invoke(api, endpoint)

    for sent in transport.call_args_list:
        assert sent.args[1].startswith(API_ROOT)


@pytest.mark.parametrize(
    "endpoint",
    [
        "//attacker.example/collect",
        "https://attacker.example/collect",
        "../../other/api",
        "article#fragment",
        "",
    ],
)
def test_raw_request_rejects_urls_outside_the_api_root(endpoint, make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, handler=MagicMock(side_effect=AssertionError("network")))

    with pytest.raises(ValueError, match=r"(?i)(origin|relative|url|fragment|traverse|path)"):
        api.request("GET", endpoint)

    transport.assert_not_called()


@pytest.mark.parametrize("entity_id", ["a/b", "a?b=1", "a#b"])
def test_path_segments_reject_separators(entity_id, make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, handler=MagicMock(side_effect=AssertionError("network")))

    with pytest.raises(ValueError, match="entity_id"):
        api.put("article", entity_id, {})

    transport.assert_not_called()


def _prepared_with_session(api, url):
    return api.session.prepare_request(requests.Request("GET", url))


def test_cross_origin_redirect_strips_authentication_token(make_client, make_response):
    api = make_client()
    original = _prepared_with_session(api, f"{API_ROOT}document/id/1/download")
    redirected = _prepared_with_session(api, "https://cdn.example.test/file.bin")
    redirect_response = make_response(302, content=b"")
    redirect_response.request = original

    assert redirected.headers["AuthenticationToken"] == "secret-token"
    api.session.rebuild_auth(redirected, redirect_response)

    assert "AuthenticationToken" not in redirected.headers


def test_same_origin_redirect_keeps_authentication_token(make_client, make_response):
    api = make_client()
    original = _prepared_with_session(api, f"{API_ROOT}article")
    redirected = _prepared_with_session(api, f"{API_ROOT}article?page=2")
    redirect_response = make_response(302, content=b"")
    redirect_response.request = original

    api.session.rebuild_auth(redirected, redirect_response)

    assert redirected.headers["AuthenticationToken"] == "secret-token"


# ------------------------------------------------------------------- retries


def test_transport_adapter_never_retries_below_the_central_client_loop(make_client):
    retry = make_client().session.get_adapter("https://").max_retries

    assert retry.total == 0
    assert retry.status_forcelist == set()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retry_adapter_never_status_retries_writes(method, status, make_client):
    retry = make_client().session.get_adapter("https://").max_retries

    assert not retry.is_retry(method, status, has_retry_after=status == 429)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
@pytest.mark.parametrize("status", [301, 302, 307, 308])
def test_redirects_are_never_followed_or_replayed(
    method, status, make_client, fake_transport, make_response
):
    api = make_client()
    transport = fake_transport(
        api,
        make_response(status, content=b"", headers={"Location": f"{API_ROOT}redirect-target"}),
    )

    with patch(SLEEP) as sleep, pytest.raises(WeclappAPIError) as exc_info:
        api.request(method, "article", json={"name": "one-shot"})

    assert exc_info.value.status_code == status
    assert "redirect-target" in str(exc_info.value)
    transport.assert_called_once()
    assert transport.call_args.kwargs["allow_redirects"] is False
    sleep.assert_not_called()


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_safe_read_retries_transient_http_status_in_central_loop(
    status, make_client, fake_transport, make_response
):
    api = make_client()
    transport = fake_transport(
        api,
        make_response(status, {"type": "/errors/transient"}),
        {"result": [{"id": "1"}]},
    )

    with patch(SLEEP) as sleep:
        result = api.request("GET", "article")

    assert result == {"result": [{"id": "1"}]}
    assert transport.call_count == 2
    sleep.assert_called_once()


def test_rate_limit_has_its_own_slower_budget(make_client, fake_transport, make_response):
    api = make_client(retry_policy=RetryPolicy(jitter=False))
    transport = fake_transport(api, handler=lambda method, url, **kwargs: make_response(429))

    with patch(SLEEP) as sleep, pytest.raises(WeclappRateLimitError):
        api.request("GET", "article")

    assert transport.call_count == 6
    assert [c.args[0] for c in sleep.call_args_list] == [2.0, 4.0, 8.0, 16.0, 32.0]


def test_server_errors_use_the_fast_transient_budget(make_client, fake_transport, make_response):
    api = make_client(retry_policy=RetryPolicy(jitter=False))
    transport = fake_transport(api, handler=lambda method, url, **kwargs: make_response(503))

    with patch(SLEEP) as sleep, pytest.raises(WeclappAPIError) as exc_info:
        api.request("GET", "article")

    assert exc_info.value.status_code == 503
    assert transport.call_count == 4
    assert [c.args[0] for c in sleep.call_args_list] == pytest.approx([0.3, 0.6, 1.2])


@pytest.mark.parametrize(("retry_after", "expected"), [("7", 7.0), ("600", 60.0)])
def test_rate_limit_retry_respects_capped_retry_after_header(
    retry_after, expected, make_client, fake_transport, make_response
):
    metrics = []
    api = make_client(on_response=metrics.append)
    fake_transport(
        api,
        make_response(429, {"type": "/errors/rate_limit"}, {"Retry-After": retry_after}),
        {"result": []},
    )

    with patch(SLEEP) as sleep:
        assert api.request("GET", "article") == {"result": []}

    sleep.assert_called_once_with(expected)
    assert metrics[0].status_code == 429
    assert metrics[0].will_retry is True
    assert metrics[0].retry_delay == expected


def test_safe_read_retries_transport_failure(make_client, fake_transport):
    api = make_client()
    transport = fake_transport(
        api,
        requests.exceptions.ConnectionError("temporary failure"),
        {"result": []},
    )

    with patch(SLEEP) as sleep:
        result = api.request("GET", "article")

    assert result == {"result": []}
    assert transport.call_count == 2
    sleep.assert_called_once()


def test_safe_retry_budget_is_shared_by_status_and_transport_failures(
    make_client, fake_transport, make_response
):
    api = make_client(max_retries=1, problem_retries=0)
    transport = fake_transport(
        api,
        make_response(503, {"type": "/errors/transient"}),
        requests.exceptions.ConnectionError("temporary failure"),
        {"result": []},
    )

    with patch(SLEEP) as sleep, pytest.raises(WeclappTransportError):
        api.request("GET", "article")

    assert transport.call_count == 2
    sleep.assert_called_once()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize(
    "failure",
    [
        requests.exceptions.ConnectionError("uncertain write outcome"),
        requests.exceptions.ReadTimeout("read timed out"),
        requests.exceptions.ChunkedEncodingError("connection broken"),
    ],
)
def test_write_with_unknown_outcome_is_never_retried(method, failure, make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, handler=MagicMock(side_effect=failure))

    with patch(SLEEP) as sleep, pytest.raises(WeclappTransportError) as exc_info:
        api.request(method, "article", json={"name": "one-shot"})

    assert exc_info.value.outcome_unknown is True
    assert exc_info.value.request_sent is True
    assert exc_info.value.status_code is None
    assert exc_info.value.__cause__ is failure
    assert "read the entity back" in str(exc_info.value)
    transport.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_write_that_provably_never_left_is_retried(method, make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, _unsent_connection_error(), {"id": "1"})

    with patch(SLEEP) as sleep:
        assert api.request(method, "article", json={"name": "one-shot"}) == {"id": "1"}

    assert transport.call_count == 2
    sleep.assert_called_once()


def test_unsent_write_reports_that_it_was_not_sent_once_retries_are_exhausted(
    make_client, fake_transport
):
    api = make_client(max_retries=2)
    transport = fake_transport(
        api, handler=lambda method, url, **kwargs: _unsent_connection_error()
    )

    with patch(SLEEP), pytest.raises(WeclappTransportError) as exc_info:
        api.post("article", {"name": "one-shot"})

    assert transport.call_count == 3
    assert exc_info.value.request_sent is False
    assert exc_info.value.outcome_unknown is False


def test_tls_failures_are_never_retried(make_client, fake_transport):
    api = make_client()
    transport = fake_transport(
        api, handler=MagicMock(side_effect=requests.exceptions.SSLError("bad certificate"))
    )

    with patch(SLEEP) as sleep, pytest.raises(WeclappTransportError):
        api.request("GET", "article")

    transport.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize(
    ("status", "suffix"),
    [(400, "request_timeout"), (409, "persistence")],
)
def test_safe_read_retries_transient_problem_once_then_surfaces_error(
    status, suffix, make_client, fake_transport, make_problem
):
    api = make_client()
    transport = fake_transport(
        api, handler=lambda method, url, **kwargs: make_problem(status, suffix)
    )

    with patch(SLEEP) as sleep, pytest.raises(WeclappAPIError) as exc_info:
        api.request("GET", "article")

    assert transport.call_count == 2
    assert exc_info.value.status_code == status
    sleep.assert_called_once()


def test_safe_read_does_not_retry_validation_problem(make_client, fake_transport, make_problem):
    api = make_client()
    transport = fake_transport(
        api, handler=lambda method, url, **kwargs: make_problem(400, "validation")
    )

    with patch(SLEEP) as sleep, pytest.raises(WeclappAPIError):
        api.request("GET", "article")

    transport.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize(
    ("status", "suffix"),
    [(400, "request_timeout"), (409, "persistence")],
)
def test_writes_do_not_retry_transient_problem_responses(
    method, status, suffix, make_client, fake_transport, make_problem
):
    api = make_client()
    transport = fake_transport(
        api, handler=lambda method, url, **kwargs: make_problem(status, suffix)
    )

    with patch(SLEEP) as sleep, pytest.raises(WeclappAPIError):
        api.request(method, "article", json={"name": "one-shot"})

    transport.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_writes_never_retry_transient_http_status(
    method, status, make_client, fake_transport, make_problem
):
    api = make_client()
    transport = fake_transport(api, handler=lambda method, url, **kwargs: make_problem(status, "x"))

    with patch(SLEEP) as sleep, pytest.raises(WeclappAPIError) as exc_info:
        api.request(method, "article", json={"name": "one-shot"})

    assert exc_info.value.status_code == status
    transport.assert_called_once()
    sleep.assert_not_called()


def test_first_rate_limit_cooldown_matches_the_retry_delay(
    make_client, fake_transport, make_response
):
    class _StopError(Exception):
        pass

    controller = ConcurrencyController(clock=lambda: 100.0)
    observed = []
    api = make_client(concurrency=controller, retry_policy=RetryPolicy(jitter=False))
    api.on_response = lambda metrics: observed.append(
        (metrics.retry_delay, controller.snapshot().cooldown_remaining)
    )
    fake_transport(api, make_response(429))

    with patch(SLEEP, side_effect=_StopError), pytest.raises(_StopError):
        api.request("GET", "article")

    assert observed == [(2.0, 2.0)]


# ---------------------------------------------------------------- pagination


def test_threaded_get_all_restores_page_order_before_applying_limit(make_client, fake_transport):
    api = make_client()
    page_two_started = threading.Event()
    page_three_finished = threading.Event()

    def handler(method, url, **kwargs):
        if url.endswith("/article/count"):
            return {"result": 6}
        page = kwargs["params"]["page"]
        if page == 1:
            return {"result": [{"id": "1"}, {"id": "2"}]}
        if page == 2:
            page_two_started.set()
            assert page_three_finished.wait(2)
            return {"result": [{"id": "3"}, {"id": "4"}]}
        assert page_two_started.wait(2)
        page_three_finished.set()
        return {"result": [{"id": "5"}, {"id": "6"}]}

    fake_transport(api, handler=handler)

    rows = api.get_all("article", {"pageSize": 2}, limit=5, threaded=True, max_workers=2)

    assert [row["id"] for row in rows] == ["1", "2", "3", "4", "5"]


def test_threaded_get_all_propagates_page_error_instead_of_returning_partial_data(
    make_client, fake_transport
):
    api = make_client()
    page_error = WeclappAPIError("page two failed")

    def handler(method, url, **kwargs):
        if url.endswith("/article/count"):
            return {"result": 6}
        page = kwargs["params"]["page"]
        if page == 2:
            raise page_error
        return {"result": [{"id": str(page * 2 - 1)}, {"id": str(page * 2)}]}

    fake_transport(api, handler=handler)

    with pytest.raises(WeclappAPIError) as exc_info:
        api.get_all("article", {"pageSize": 2}, threaded=True, max_workers=2)

    assert exc_info.value is page_error


def test_limit_zero_short_circuits_without_network_io(make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, handler=MagicMock(side_effect=AssertionError("network")))

    assert api.get_all("article", limit=0) == []
    assert api.get_all("article", limit=0, threaded=True) == []
    assert list(api.iter_all("article", limit=0)) == []
    assert list(api.iter_keyset("article", limit=0)) == []
    assert api.get_by_ids("article", []) == []
    transport.assert_not_called()


def test_get_all_rejects_invalid_limit_and_worker_count_before_network_io(
    make_client, fake_transport
):
    api = make_client(max_concurrency=4)
    transport = fake_transport(api, handler=MagicMock(side_effect=AssertionError("network")))

    with pytest.raises(ValueError, match="limit"):
        api.get_all("article", limit=-1)
    with pytest.raises(ValueError, match="max_workers"):
        api.get_all("article", limit=1, threaded=True, max_workers=0)
    with pytest.raises(ValueError, match="max_workers"):
        api.get_all("article", max_workers=True)
    with pytest.raises(ValueError, match="threaded"):
        api.get_all("article", threaded="always")
    with pytest.raises(ValueError, match="limit"):
        list(api.iter_all("article", limit=-1))

    transport.assert_not_called()


def test_limit_slices_additional_properties_in_lockstep_with_rows(make_client, fake_transport):
    api = make_client()
    fake_transport(
        api,
        {"result": [{"id": "1"}, {"id": "2"}], "additionalProperties": {"score": [10, 20]}},
        {"result": [{"id": "3"}, {"id": "4"}], "additionalProperties": {"score": [30, 40]}},
    )

    result = api.get_all(
        "article",
        {"pageSize": 2},
        limit=3,
        threaded=False,
        return_weclapp_response=True,
    )

    assert isinstance(result, WeclappResponse)
    assert [row["id"] for row in result.result] == ["1", "2", "3"]
    assert result.additional_properties == {"score": [10, 20, 30]}
    assert result.raw_response["additionalProperties"] == {"score": [10, 20, 30]}


def test_count_uses_central_request_path_and_strips_projection_params(make_client, fake_transport):
    api = make_client()
    params = {
        "filter": "active-eq=true",
        "name-eq": "A",
        "page": 9,
        "pageSize": 2,
        "sort": "name",
        "properties": "id,name",
        "additionalProperties": "score",
        "includeReferencedEntities": "unitId",
        "serializeNulls": True,
    }

    def handler(method, url, **kwargs):
        if url.endswith("/article/count"):
            return {"result": 2}
        return {"result": [{"id": "1"}, {"id": "2"}]}

    transport = fake_transport(api, handler=handler)

    assert [row.id for row in api.get_all("article", params, threaded=True)] == ["1", "2"]

    page_call, count_call = transport.call_args_list
    assert page_call.kwargs["params"]["page"] == 1
    assert page_call.kwargs["params"]["sort"] == "name"
    assert count_call.args[:2] == ("GET", f"{API_ROOT}article/count")
    assert count_call.kwargs["params"] == {"filter": "active-eq=true", "name-eq": "A"}
    assert params["page"] == 9
    assert params["additionalProperties"] == "score"


def test_get_all_adds_a_stable_sort_unless_the_caller_opts_out(make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, {"result": []}, {"result": []}, {"result": []})

    api.get_all("article")
    api.get_all("article", {"orderBy": "name"})
    api.get_all("article", {"sort": None})

    sent = [c.kwargs["params"] for c in transport.call_args_list]
    assert sent[0]["sort"] == "id"
    assert "sort" not in sent[1]
    assert sent[1]["orderBy"] == "name"
    assert "sort" not in sent[2]


# ------------------------------------------------------------ response bodies


@pytest.mark.parametrize(
    "content_type",
    [
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.ms-outlook",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ],
)
def test_office_responses_remain_bytes(content_type, make_client, fake_transport, make_response):
    api = make_client()
    binary = b"PK\x03\x04\xff\xfe\x00binary"
    fake_transport(api, make_response(content=binary, content_type=f"{content_type}; version=1"))

    result = api.request("GET", "document/id/1/download")

    assert result == {"content": binary, "content_type": f"{content_type}; version=1"}


def test_vendor_plus_json_is_parsed_as_json(make_client, fake_transport, make_response):
    api = make_client()
    fake_transport(
        api,
        make_response(
            content=b'{"result":{"id":"1"}}',
            content_type="application/vnd.weclapp+json; charset=utf-8",
        ),
    )

    assert api.request("GET", "article/id/1") == {"result": {"id": "1"}}


def test_text_response_remains_text(make_client, fake_transport, make_response):
    api = make_client()
    fake_transport(
        api,
        make_response(content="Grüße".encode(), content_type="text/plain; charset=utf-8"),
    )

    assert api.request("GET", "status") == {
        "content": "Grüße",
        "content_type": "text/plain; charset=utf-8",
    }


# ---------------------------------------------------------- custom attributes


def test_reference_custom_attribute_round_trips_through_entity_references():
    original = [{"entityId": "42", "entityName": "article"}]
    entity = WeclappEntity.from_row(
        {
            "id": "1",
            "customAttributes": [
                {"attributeDefinitionId": "reference-def", "entityReferences": original}
            ],
        },
        attribute_definitions={
            "reference-def": {
                "id": "reference-def",
                "attributeKey": "relatedArticles",
                "attributeType": "REFERENCE",
            }
        },
    )

    assert entity.relatedArticles == original
    replacement = [{"entityId": "99", "entityName": "article"}]
    entity.relatedArticles = replacement
    custom_attribute = entity.to_payload()["customAttributes"][0]

    assert custom_attribute["entityReferences"] == replacement
    assert "stringValue" not in custom_attribute


def test_empty_boolean_custom_attribute_keeps_boolean_value_field_on_edit():
    entity = WeclappEntity.from_row(
        {
            "id": "1",
            "customAttributes": [
                {
                    "attributeDefinitionId": "boolean-def",
                    "stringValue": None,
                    "booleanValue": None,
                }
            ],
        },
        attribute_definitions={
            "boolean-def": {
                "id": "boolean-def",
                "attributeKey": "fragile",
                "attributeType": "BOOLEAN",
            }
        },
    )

    assert entity.fragile is None
    entity.fragile = True
    custom_attribute = entity.to_payload()["customAttributes"][0]

    assert custom_attribute["booleanValue"] is True
    assert custom_attribute.get("stringValue") is None


def test_referenced_entity_receives_parent_attribute_definition_map():
    entity = WeclappEntity.from_row(
        {"id": "order-1", "customerId": "party-1"},
        referenced_entities={
            "party": {
                "party-1": {
                    "id": "party-1",
                    "customAttributes": [
                        {"attributeDefinitionId": "segment-def", "stringValue": "VIP"}
                    ],
                }
            }
        },
        attribute_definitions={
            "segment-def": {
                "id": "segment-def",
                "attributeKey": "segment",
                "attributeType": "STRING",
            }
        },
    )

    assert entity.customer.segment == "VIP"


def _writeable_entity():
    return WeclappEntity.from_row(
        {
            "id": "1",
            "customAttributes": [
                {
                    "attributeDefinitionId": "flag-def",
                    "internalName": "flag",
                    "booleanValue": True,
                }
            ],
        },
        additional_properties_for_row={"computedScore": 99},
    )


def test_all_json_write_entrypoints_auto_convert_weclapp_entity_to_payload(
    make_client, fake_transport
):
    api = make_client()
    transport = fake_transport(api, handler=lambda method, url, **kwargs: {})
    entity = _writeable_entity()
    expected = entity.to_payload()

    api.post("article", entity)
    api.put("article", "1", entity)
    api.call_method("article", "duplicate", entity_id="1", method="POST", data=entity)
    api.request("POST", "article", json=entity)

    assert transport.call_count == 4
    for sent in transport.call_args_list:
        payload = sent.kwargs["json"]
        assert payload == expected
        assert type(payload) is dict
        assert "flag" not in payload
        assert "computedScore" not in payload


def test_problem_type_drives_optimistic_lock_and_validation_helpers(make_problem):
    optimistic = WeclappAPIError("conflict", response=make_problem(409, "optimistic_lock"))
    validation = WeclappAPIError("invalid", response=make_problem(400, "validation"))

    assert optimistic.is_optimistic_lock
    assert validation.is_validation_error


# --------------------------------------------------------------- lifecycle


def test_client_context_manager_closes_owned_session(make_client):
    api = make_client()
    api.session.close = MagicMock()

    with api as entered:
        assert entered is api

    api.session.close.assert_called_once_with()


def test_client_does_not_close_a_caller_supplied_session():
    session = requests.Session()
    session.close = MagicMock()

    with Weclapp(BASE_URL, "secret-token", session=session) as api:
        assert api.session is session

    session.close.assert_not_called()


def test_get_by_id_forces_first_page_without_mutating_callers_params(make_client, fake_transport):
    api = make_client()
    transport = fake_transport(api, {"result": [{"id": "123"}]})
    params = {"page": 9, "pageSize": 500, "sort": "id"}

    result = api.get("article", "123", params)

    assert result.id == "123"
    assert transport.call_args.kwargs["params"] == {
        "page": 1,
        "pageSize": 1,
        "sort": "id",
        "id-eq": "123",
    }
    assert params == {"page": 9, "pageSize": 500, "sort": "id"}


def test_public_request_routes_supported_arguments_through_central_transport(
    make_client, fake_transport
):
    api = make_client()
    transport = fake_transport(api, {"result": {"id": "1"}})

    result = api.request(
        "post",
        "/article",
        params={"dryRun": True},
        json={"name": "Test"},
        headers={"X-Test": "yes"},
        timeout=61,
    )

    assert result == {"result": {"id": "1"}}
    transport.assert_called_once_with(
        "POST",
        f"{API_ROOT}article",
        params={"dryRun": True},
        json={"name": "Test"},
        # A per-request timeout below the default lowers the server-side
        # timeout header to 90 % of the read timeout.
        headers={"X-Test": "yes", "X-Weclapp-Request-Timeout-Ms": "54900"},
        timeout=61,
        allow_redirects=False,
    )


def test_iter_all_is_lazy_uses_param_page_size_and_honors_limit(make_client, fake_transport):
    api = make_client()
    calls = []

    def handler(method, url, **kwargs):
        calls.append((method, url, dict(kwargs["params"])))
        page = kwargs["params"]["page"]
        if page == 1:
            return {"result": [{"id": "1"}, {"id": "2"}]}
        if page == 2:
            return {"result": [{"id": "3"}, {"id": "4"}]}
        raise AssertionError("iterator fetched beyond its limit")

    fake_transport(api, handler=handler)
    params = {"page": 99, "pageSize": 2, "sort": "id"}

    iterator = api.iter_all("article", params=params, limit=3)
    assert calls == []
    rows = list(iterator)

    assert all(isinstance(row, WeclappEntity) for row in rows)
    assert [row.id for row in rows] == ["1", "2", "3"]
    assert [call[2]["page"] for call in calls] == [1, 2]
    assert all(call[2]["pageSize"] == 2 for call in calls)
    assert params == {"page": 99, "pageSize": 2, "sort": "id"}
