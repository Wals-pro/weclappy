"""Offline regression tests for safety-critical weclappy contracts.

These tests deliberately mock the transport.  They cover behavior that must
not depend on a live tenant and are kept separate from broad feature tests so
the security/reliability contract remains easy to audit.
"""

import json as json_module
import inspect
import threading
from typing import get_type_hints
from unittest.mock import MagicMock, patch

try:
    from typing import get_overloads
except ImportError:  # Python 3.9 and 3.10 do not expose overload introspection.
    get_overloads = None

import pytest
import requests

import weclappy as weclappy_module
from weclappy import Weclapp, WeclappAPIError, WeclappEntity, WeclappResponse


BASE_URL = "https://tenant.weclapp.com/webapp/api/v2"
API_ROOT = f"{BASE_URL}/"


def response(
    status=200,
    payload=None,
    *,
    content=None,
    content_type="application/json",
    headers=None,
    url=f"{API_ROOT}article",
):
    """Build a real requests.Response without performing network I/O."""
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.reason = {
        200: "OK",
        302: "Found",
        400: "Bad Request",
        409: "Conflict",
        429: "Too Many Requests",
        503: "Service Unavailable",
    }.get(status, "Test Response")
    if content is None:
        content = b"" if payload is None else json_module.dumps(payload).encode("utf-8")
    result._content = content
    if content_type:
        result.headers["Content-Type"] = content_type
    if headers:
        result.headers.update(headers)
    return result


def problem(status, suffix):
    return response(
        status,
        {
            "type": f"/webapp/view/api/errors.html#!/errors/{suffix}",
            "title": suffix.replace("_", " ").title(),
            "status": status,
        },
        content_type="application/problem+json",
    )


def client():
    return Weclapp(BASE_URL, "secret-token")


def test_module_declares_a_small_public_star_export_surface():
    assert weclappy_module.__all__ == [
        "Weclapp",
        "WeclappAPIError",
        "WeclappEntity",
        "WeclappResponse",
        "MIME_TYPES",
        "infer_content_type",
    ]


def test_public_overload_annotations_are_runtime_resolvable():
    assert get_type_hints(Weclapp.get)
    if get_overloads is None:
        assert weclappy_module.Literal
        return
    for method in (Weclapp.get, Weclapp.get_all):
        overloads = get_overloads(method)
        assert overloads
        assert all(get_type_hints(candidate) for candidate in overloads)


def test_get_all_defaults_to_adaptive_threaded_pagination():
    signature = inspect.signature(Weclapp.get_all)
    assert signature.parameters["threaded"].default is True
    assert signature.parameters["max_workers"].default is None


def test_adaptive_read_controller_reacts_to_queue_feedback():
    controller = weclappy_module._AdaptiveReadController(ceiling=8)
    controller._target = 4

    controller.observe(
        response(
            headers={
                "X-Weclapp-Wait-Ms": "300",
                "X-Weclapp-Wait-Reason": "concurrency",
            }
        )
    )
    assert controller.target == 3

    controller.observe(
        response(
            headers={
                "X-Weclapp-Wait-Ms": "2200",
                "X-Weclapp-Wait-Reason": "load",
            }
        )
    )
    assert controller.target == 2


def test_adaptive_read_controller_ignores_invalid_queue_headers():
    controller = weclappy_module._AdaptiveReadController(ceiling=4)
    controller.observe(
        response(
            status=400,
            headers={
                "X-Weclapp-Wait-Ms": "not-a-number",
                "X-Weclapp-Wait-Reason": "unknown",
            },
        )
    )
    assert controller.target == 2


def test_adaptive_read_controller_shares_rate_limit_cooldown():
    controller = weclappy_module._AdaptiveReadController(ceiling=4)
    with patch("weclappy.time.monotonic", return_value=10.0):
        controller.observe(response(429), retry_delay=3.0)
    assert controller.target == 1
    assert controller._cooldown_until == 13.0


def test_leading_slash_stays_relative_to_api_root():
    api = client()
    api.session.request = MagicMock(return_value=response(payload={"result": []}))

    assert api.get("/article") == []

    assert api.session.request.call_args.args[:2] == (
        "GET",
        f"{API_ROOT}article",
    )


@pytest.mark.parametrize(
    "invoke",
    [
        lambda api, endpoint: api.get(endpoint),
        lambda api, endpoint: api.get_all(endpoint, limit=1),
        lambda api, endpoint: api.post(endpoint, {}),
        lambda api, endpoint: api.put(endpoint, "1", {}),
        lambda api, endpoint: api.delete(endpoint, "1"),
        lambda api, endpoint: api.call_method(endpoint, "count"),
        lambda api, endpoint: api.upload(endpoint, b"data"),
        lambda api, endpoint: api.download(endpoint),
        lambda api, endpoint: api.request("GET", endpoint),
    ],
)
@pytest.mark.parametrize(
    "endpoint",
    ["//attacker.example/collect", "https://attacker.example/collect"],
)
def test_every_public_request_path_rejects_cross_origin_urls(invoke, endpoint):
    api = client()
    api.session.request = MagicMock(side_effect=AssertionError("network must not be reached"))

    with pytest.raises(ValueError, match="(?i)(origin|host|relative|url)"):
        invoke(api, endpoint)

    api.session.request.assert_not_called()


def _prepared_with_session(api, url):
    return api.session.prepare_request(requests.Request("GET", url))


def test_cross_origin_redirect_strips_authentication_token():
    api = client()
    original = _prepared_with_session(api, f"{API_ROOT}document/id/1/download")
    redirected = _prepared_with_session(api, "https://cdn.example.test/file.bin")
    redirect_response = response(302, content=b"")
    redirect_response.request = original

    assert redirected.headers["AuthenticationToken"] == "secret-token"
    api.session.rebuild_auth(redirected, redirect_response)

    assert "AuthenticationToken" not in redirected.headers


def test_same_origin_redirect_keeps_authentication_token():
    api = client()
    original = _prepared_with_session(api, f"{API_ROOT}article")
    redirected = _prepared_with_session(api, f"{API_ROOT}article?page=2")
    redirect_response = response(302, content=b"")
    redirect_response.request = original

    api.session.rebuild_auth(redirected, redirect_response)

    assert redirected.headers["AuthenticationToken"] == "secret-token"


def test_transport_adapter_never_retries_below_the_central_client_loop():
    api = client()
    retry = api.session.get_adapter("https://").max_retries

    assert retry.total == 0
    assert retry.status_forcelist == set()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize("status", [307, 308])
def test_write_redirects_are_never_followed_or_replayed(method, status):
    api = client()
    api.session.request = MagicMock(
        return_value=response(
            status,
            content=b"",
            headers={"Location": f"{API_ROOT}redirect-target"},
        )
    )

    with pytest.raises(WeclappAPIError) as exc_info:
        api.request(method, "article", json={"name": "one-shot"})

    assert exc_info.value.status_code == status
    api.session.request.assert_called_once()
    assert api.session.request.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_safe_read_retries_transient_http_status_in_central_loop(status):
    api = client()
    api.session.request = MagicMock(
        side_effect=[
            response(status, payload={"type": "/errors/transient"}),
            response(payload={"result": [{"id": "1"}]}),
        ]
    )

    with patch("weclappy.time.sleep") as sleep:
        result = api.request("GET", "article")

    assert result == {"result": [{"id": "1"}]}
    assert api.session.request.call_count == 2
    sleep.assert_called_once()


def test_rate_limit_retry_respects_retry_after_header():
    api = client()
    api.session.request = MagicMock(
        side_effect=[
            response(
                429,
                payload={"type": "/errors/rate_limit"},
                headers={"Retry-After": "7"},
            ),
            response(payload={"result": []}),
        ]
    )

    with patch("weclappy.time.sleep") as sleep, patch.object(
        api, "_log_queue_metadata"
    ) as queue_log:
        assert api.request("GET", "article") == {"result": []}

    sleep.assert_called_once_with(7.0)
    assert queue_log.call_args_list[0].args[2].status_code == 429


def test_safe_read_retries_transport_failure():
    api = client()
    api.session.request = MagicMock(
        side_effect=[
            requests.exceptions.ConnectionError("temporary failure"),
            response(payload={"result": []}),
        ]
    )

    with patch("weclappy.time.sleep") as sleep:
        result = api.request("GET", "article")

    assert result == {"result": []}
    assert api.session.request.call_count == 2
    sleep.assert_called_once()


def test_safe_retry_budget_is_shared_by_status_and_transport_failures():
    api = Weclapp(BASE_URL, "secret-token", max_retries=1, problem_retries=0)
    api.session.request = MagicMock(
        side_effect=[
            response(503, payload={"type": "/errors/transient"}),
            requests.exceptions.ConnectionError("temporary failure"),
            response(payload={"result": []}),
        ]
    )

    with patch("weclappy.time.sleep") as sleep, pytest.raises(WeclappAPIError):
        api.request("GET", "article")

    assert api.session.request.call_count == 2
    sleep.assert_called_once()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_write_transport_failure_is_never_retried(method):
    api = client()
    api.session.request = MagicMock(
        side_effect=requests.exceptions.ConnectionError("uncertain write outcome")
    )

    with patch("weclappy.time.sleep") as sleep, pytest.raises(WeclappAPIError):
        api.request(method, "article", json={"name": "one-shot"})

    api.session.request.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retry_adapter_never_status_retries_writes(method, status):
    retry = client().session.get_adapter("https://").max_retries

    assert not retry.is_retry(method, status, has_retry_after=status == 429)


@pytest.mark.parametrize(
    ("status", "suffix"),
    [(400, "request_timeout"), (409, "persistence")],
)
def test_safe_read_retries_transient_problem_once_then_surfaces_error(status, suffix):
    api = client()
    api.session.request = MagicMock(return_value=problem(status, suffix))

    with patch("weclappy.time.sleep") as sleep, pytest.raises(WeclappAPIError) as exc_info:
        api.request("GET", "article")

    assert api.session.request.call_count == 2
    assert exc_info.value.status_code == status
    sleep.assert_called_once()


def test_safe_read_does_not_retry_validation_problem():
    api = client()
    api.session.request = MagicMock(return_value=problem(400, "validation"))

    with patch("weclappy.time.sleep") as sleep, pytest.raises(WeclappAPIError):
        api.request("GET", "article")

    api.session.request.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize(
    ("status", "suffix"),
    [(400, "request_timeout"), (409, "persistence")],
)
def test_writes_do_not_retry_transient_problem_responses(method, status, suffix):
    api = client()
    api.session.request = MagicMock(return_value=problem(status, suffix))

    with patch("weclappy.time.sleep") as sleep, pytest.raises(WeclappAPIError):
        api.request(method, "article", json={"name": "one-shot"})

    api.session.request.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_writes_do_not_manually_retry_transient_http_status(method):
    api = client()
    api.session.request = MagicMock(return_value=problem(503, "unexpected"))

    with patch("weclappy.time.sleep") as sleep, pytest.raises(WeclappAPIError):
        api.request(method, "article", json={"name": "one-shot"})

    api.session.request.assert_called_once()
    sleep.assert_not_called()


def test_threaded_get_all_restores_page_order_before_applying_limit():
    api = client()
    page_one_started = threading.Event()
    page_two_finished = threading.Event()

    def fake_send(method, url, **kwargs):
        if url.endswith("/article/count"):
            return {"result": 4}
        page = kwargs["params"]["page"]
        if page == 1:
            page_one_started.set()
            assert page_two_finished.wait(2)
            return {"result": [{"id": "1"}, {"id": "2"}]}
        assert page_one_started.wait(2)
        page_two_finished.set()
        return {"result": [{"id": "3"}, {"id": "4"}]}

    api._send_request = fake_send

    with patch.object(weclappy_module, "DEFAULT_PAGE_SIZE", 2):
        rows = api.get_all("article", limit=3, threaded=True, max_workers=2)

    assert [row["id"] for row in rows] == ["1", "2", "3"]


def test_threaded_get_all_propagates_page_error_instead_of_returning_partial_data():
    api = client()
    page_error = WeclappAPIError("page two failed")

    def fake_send(method, url, **kwargs):
        if url.endswith("/article/count"):
            return {"result": 4}
        if kwargs["params"]["page"] == 2:
            raise page_error
        return {"result": [{"id": "1"}, {"id": "2"}]}

    api._send_request = fake_send

    with patch.object(weclappy_module, "DEFAULT_PAGE_SIZE", 2), pytest.raises(
        WeclappAPIError
    ) as exc_info:
        api.get_all("article", threaded=True, max_workers=2)

    assert exc_info.value is page_error


def test_limit_zero_short_circuits_without_network_io():
    api = client()
    api._send_request = MagicMock(side_effect=AssertionError("network must not be reached"))

    assert api.get_all("article", limit=0) == []
    assert api.get_all("article", limit=0, threaded=True) == []
    assert list(api.iter_all("article", limit=0)) == []
    api._send_request.assert_not_called()


def test_get_all_rejects_invalid_limit_and_worker_count_before_network_io():
    api = client()
    api._send_request = MagicMock(side_effect=AssertionError("network must not be reached"))

    with pytest.raises(ValueError, match="limit"):
        api.get_all("article", limit=-1)
    with pytest.raises(ValueError, match="max_workers"):
        api.get_all("article", limit=1, threaded=True, max_workers=0)
    with pytest.raises(ValueError, match="limit"):
        list(api.iter_all("article", limit=-1))

    api._send_request.assert_not_called()


def test_limit_slices_additional_properties_in_lockstep_with_rows():
    api = client()
    api._send_request = MagicMock(
        side_effect=[
            {
                "result": [{"id": "1"}, {"id": "2"}],
                "additionalProperties": {"score": [10, 20]},
            },
            {
                "result": [{"id": "3"}, {"id": "4"}],
                "additionalProperties": {"score": [30, 40]},
            },
        ]
    )

    with patch.object(weclappy_module, "DEFAULT_PAGE_SIZE", 2):
        result = api.get_all(
            "article",
            limit=3,
            threaded=False,
            return_weclapp_response=True,
        )

    assert isinstance(result, WeclappResponse)
    assert [row["id"] for row in result.result] == ["1", "2", "3"]
    assert result.additional_properties == {"score": [10, 20, 30]}
    assert result.raw_response["additionalProperties"] == {"score": [10, 20, 30]}


def test_threaded_count_uses_central_request_path_and_strips_projection_params():
    api = client()
    api._send_request = MagicMock(return_value={"result": 0})
    params = {
        "filter": "active-eq=true",
        "name-eq": "A",
        "page": 9,
        "pageSize": 12,
        "sort": "name",
        "properties": "id,name",
        "additionalProperties": "score",
        "includeReferencedEntities": "unitId",
        "serializeNulls": True,
    }

    assert api.get_all("article", params=params, threaded=True) == []

    api._send_request.assert_called_once()
    method, url = api._send_request.call_args.args[:2]
    assert method == "GET"
    assert url == f"{API_ROOT}article/count"
    assert api._send_request.call_args.kwargs["params"] == {
        "filter": "active-eq=true",
        "name-eq": "A",
    }
    assert params["page"] == 9
    assert params["additionalProperties"] == "score"


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
def test_office_responses_remain_bytes(content_type):
    api = client()
    binary = b"PK\x03\x04\xff\xfe\x00binary"
    api.session.request = MagicMock(
        return_value=response(content=binary, content_type=f"{content_type}; version=1")
    )

    result = api.request("GET", "document/id/1/download")

    assert result == {
        "content": binary,
        "content_type": f"{content_type}; version=1",
    }


def test_vendor_plus_json_is_parsed_as_json():
    api = client()
    api.session.request = MagicMock(
        return_value=response(
            content=b'{"result":{"id":"1"}}',
            content_type="application/vnd.weclapp+json; charset=utf-8",
        )
    )

    assert api.request("GET", "article/id/1") == {"result": {"id": "1"}}


def test_text_response_remains_text():
    api = client()
    api.session.request = MagicMock(
        return_value=response(
            content="Grüße".encode("utf-8"),
            content_type="text/plain; charset=utf-8",
        )
    )

    assert api.request("GET", "status") == {
        "content": "Grüße",
        "content_type": "text/plain; charset=utf-8",
    }


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


def _assert_last_json_is_payload(api, expected):
    sent = api._send_request.call_args.kwargs["json"]
    assert sent == expected
    assert "flag" not in sent
    assert "computedScore" not in sent


def test_all_json_write_entrypoints_auto_convert_weclapp_entity_to_payload():
    api = client()
    api._send_request = MagicMock(return_value={})
    entity = _writeable_entity()
    expected = entity.to_payload()

    api.post("article", entity)
    _assert_last_json_is_payload(api, expected)
    api._send_request.reset_mock()

    api.put("article", "1", entity)
    _assert_last_json_is_payload(api, expected)
    api._send_request.reset_mock()

    api.call_method("article", "duplicate", entity_id="1", method="POST", data=entity)
    _assert_last_json_is_payload(api, expected)
    api._send_request.reset_mock()

    api.request("POST", "article", json=entity)
    _assert_last_json_is_payload(api, expected)


def test_problem_type_drives_optimistic_lock_and_validation_helpers():
    optimistic = WeclappAPIError(
        "conflict",
        response=problem(409, "optimistic_lock"),
    )
    validation = WeclappAPIError(
        "invalid",
        response=problem(400, "validation"),
    )

    assert optimistic.is_optimistic_lock
    assert validation.is_validation_error


def test_client_context_manager_closes_owned_session():
    api = client()
    api.session.close = MagicMock()

    with api as entered:
        assert entered is api

    api.session.close.assert_called_once_with()


def test_get_by_id_forces_first_page_without_mutating_callers_params():
    api = client()
    api._send_request = MagicMock(return_value={"result": [{"id": "123"}]})
    params = {"page": 9, "pageSize": 500, "sort": "id"}

    result = api.get("article", id="123", params=params)

    assert result.id == "123"
    assert api._send_request.call_args.kwargs["params"] == {
        "page": 1,
        "pageSize": 1,
        "sort": "id",
        "id-eq": "123",
    }
    assert params == {"page": 9, "pageSize": 500, "sort": "id"}


def test_public_request_routes_supported_arguments_through_central_transport():
    api = client()
    api._send_request = MagicMock(return_value={"result": {"id": "1"}})

    result = api.request(
        "post",
        "/article",
        params={"dryRun": True},
        json={"name": "Test"},
        headers={"X-Test": "yes"},
        timeout=61,
    )

    assert result == {"result": {"id": "1"}}
    api._send_request.assert_called_once_with(
        "POST",
        f"{API_ROOT}article",
        params={"dryRun": True},
        json={"name": "Test"},
        headers={"X-Test": "yes"},
        timeout=61,
    )


def test_iter_all_is_lazy_uses_param_page_size_and_honors_limit():
    api = client()
    calls = []

    def fake_send(method, url, **kwargs):
        calls.append((method, url, dict(kwargs["params"])))
        page = kwargs["params"]["page"]
        if page == 1:
            return {"result": [{"id": "1"}, {"id": "2"}]}
        if page == 2:
            return {"result": [{"id": "3"}, {"id": "4"}]}
        raise AssertionError("iterator fetched beyond its limit")

    api._send_request = fake_send
    params = {"page": 99, "pageSize": 2, "sort": "id"}

    iterator = api.iter_all("article", params=params, limit=3)
    assert calls == []
    rows = list(iterator)

    assert all(isinstance(row, WeclappEntity) for row in rows)
    assert [row.id for row in rows] == ["1", "2", "3"]
    assert [call[2]["page"] for call in calls] == [1, 2]
    assert all(call[2]["pageSize"] == 2 for call in calls)
    assert params == {"page": 99, "pageSize": 2, "sort": "id"}
