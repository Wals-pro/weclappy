"""Contract tests for lazy custom-attribute definition loading."""

from unittest.mock import MagicMock, call, patch

import requests

import weclappy as weclappy_module
from weclappy import Weclapp, WeclappAPIError


BASE_URL = "https://tenant.weclapp.com/webapp/api/v2"


def client() -> Weclapp:
    return Weclapp(BASE_URL, "test-token")


def rows_requiring_definitions():
    return [
        {
            "id": "article-1",
            "customAttributes": [
                {"attributeDefinitionId": "definition-1", "stringValue": "value"}
            ],
        }
    ]


def api_error(status: int, problem_type: str) -> WeclappAPIError:
    response = requests.Response()
    response.status_code = status
    response.url = f"{BASE_URL}/customAttributeDefinition"
    response.headers["Content-Type"] = "application/problem+json"
    response._content = (
        '{"type":"/errors/%s","status":%d}' % (problem_type, status)
    ).encode("utf-8")
    return WeclappAPIError("definition lookup failed", response=response)


def test_definition_lookup_uses_projection_stable_sort_pagination_and_cache():
    api = client()
    api.request = MagicMock(
        side_effect=[
            {
                "result": [
                    {
                        "id": "definition-1",
                        "attributeKey": "trackingCode",
                        "attributeType": "STRING",
                        "readOnly": False,
                    },
                    {
                        "id": "definition-2",
                        "attributeKey": "locked",
                        "attributeType": "BOOLEAN",
                        "readOnly": True,
                    },
                ]
            },
            {
                "result": [
                    {
                        "id": "definition-3",
                        "attributeKey": "deliveryDate",
                        "attributeType": "DATE",
                        "readOnly": False,
                    }
                ]
            },
        ]
    )

    with patch.object(weclappy_module, "DEFAULT_PAGE_SIZE", 2):
        definitions = api._ensure_attribute_definitions(rows_requiring_definitions())
        cached = api._ensure_attribute_definitions(rows_requiring_definitions())

    assert cached is definitions
    assert set(definitions) == {"definition-1", "definition-2", "definition-3"}
    expected_projection = "id,attributeKey,attributeType,readOnly"
    assert api.request.call_args_list == [
        call(
            "GET",
            "customAttributeDefinition",
            params={
                "page": 1,
                "pageSize": 2,
                "sort": "id",
                "properties": expected_projection,
            },
        ),
        call(
            "GET",
            "customAttributeDefinition",
            params={
                "page": 2,
                "pageSize": 2,
                "sort": "id",
                "properties": expected_projection,
            },
        ),
    ]


def test_permanent_definition_lookup_failure_is_cached():
    api = client()
    api.request = MagicMock(side_effect=api_error(403, "authorization"))

    assert api._ensure_attribute_definitions(rows_requiring_definitions()) == {}
    assert api._ensure_attribute_definitions(rows_requiring_definitions()) == {}

    api.request.assert_called_once()
    assert api._attribute_definitions_by_id == {}


def test_transient_definition_lookup_failure_can_recover_on_later_read():
    api = client()
    api.request = MagicMock(
        side_effect=[
            api_error(503, "unexpected"),
            {
                "result": [
                    {
                        "id": "definition-1",
                        "attributeKey": "trackingCode",
                        "attributeType": "STRING",
                        "readOnly": False,
                    }
                ]
            },
        ]
    )

    assert api._ensure_attribute_definitions(rows_requiring_definitions()) == {}
    assert api._attribute_definitions_by_id is None

    definitions = api._ensure_attribute_definitions(rows_requiring_definitions())

    assert definitions["definition-1"]["attributeKey"] == "trackingCode"
    assert api.request.call_count == 2


def test_wrapped_read_uses_lazily_loaded_attribute_definition():
    api = client()
    api.request = MagicMock(
        return_value={
            "result": [
                {
                    "id": "definition-1",
                    "attributeKey": "trackingCode",
                    "attributeType": "STRING",
                    "readOnly": False,
                }
            ]
        }
    )

    wrapped = api._wrap_rows(rows_requiring_definitions(), None, None)

    assert wrapped[0].trackingCode == "value"
