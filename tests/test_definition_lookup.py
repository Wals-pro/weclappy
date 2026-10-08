"""Contract tests for lazy custom-attribute definition loading.

``customAttributes`` entries in v2 responses usually lack ``internalName``.
The client then loads ``customAttributeDefinition`` once, lazily, to derive
flattened field names. These tests observe that only through the transport.
"""

import logging
from unittest.mock import patch

import pytest

from weclappy import WeclappAPIError

BASE_URL = "https://tenant.weclapp.com/webapp/api/v2"
DEFINITIONS_URL = f"{BASE_URL}/customAttributeDefinition"
PROJECTION = "id,attributeKey,attributeType,readOnly"

ARTICLE_PAGE = {
    "result": [
        {
            "id": "article-1",
            "customAttributes": [{"attributeDefinitionId": "definition-1", "stringValue": "value"}],
        }
    ]
}
TRACKING_DEFINITION = {
    "id": "definition-1",
    "attributeKey": "trackingCode",
    "attributeType": "STRING",
    "readOnly": False,
}


def _router(definition_replies):
    """Serve ``article`` reads and the given definition replies in order."""
    replies = iter(definition_replies)
    definition_calls = []

    def handler(method, url, **kwargs):
        if url == DEFINITIONS_URL:
            definition_calls.append(dict(kwargs["params"]))
            return next(replies)
        return ARTICLE_PAGE

    return handler, definition_calls


def test_definition_lookup_uses_projection_stable_sort_pagination_and_cache(
    make_client, fake_transport
):
    api = make_client()
    handler, definition_calls = _router(
        [
            {
                "result": [
                    TRACKING_DEFINITION,
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
    fake_transport(api, handler=handler)

    with patch("weclappy.client.DEFAULT_PAGE_SIZE", 2):
        first = api.get("article")
        second = api.get("article")

    assert first[0].trackingCode == "value"
    assert second[0].trackingCode == "value"
    assert definition_calls == [
        {"properties": PROJECTION, "sort": "id", "pageSize": 2, "page": 1},
        {"properties": PROJECTION, "sort": "id", "pageSize": 2, "page": 2},
    ]


def test_rows_with_internal_names_never_load_definitions(make_client, fake_transport):
    api = make_client()
    transport = fake_transport(
        api,
        {
            "result": [
                {
                    "id": "article-1",
                    "customAttributes": [
                        {
                            "attributeDefinitionId": "definition-1",
                            "internalName": "trackingCode",
                            "stringValue": "value",
                        }
                    ],
                }
            ]
        },
    )

    assert api.get("article")[0].trackingCode == "value"
    transport.assert_called_once()


def test_permanent_definition_lookup_failure_is_cached(
    make_client, fake_transport, make_problem, caplog
):
    api = make_client()
    handler, definition_calls = _router([make_problem(403, "authorization")])
    fake_transport(api, handler=handler)

    with caplog.at_level(logging.WARNING, logger="weclappy"):
        first = api.get("article")
        second = api.get("article")

    assert len(definition_calls) == 1
    with pytest.raises(AttributeError):
        _ = first[0].trackingCode
    assert second[0]["customAttributes"][0]["stringValue"] == "value"
    assert sum("customAttributeDefinition is not readable" in m for m in caplog.messages) == 1


def test_transient_definition_lookup_failure_propagates_and_recovers_on_later_read(
    make_client, fake_transport, make_problem
):
    # Behaviour change in 1.0: a transient failure is raised instead of
    # silently returning entities without flattened attributes, so the entity
    # shape never depends on a passing outage.
    api = make_client(max_retries=0)
    handler, definition_calls = _router(
        [make_problem(503, "unexpected"), {"result": [TRACKING_DEFINITION]}]
    )
    fake_transport(api, handler=handler)

    with pytest.raises(WeclappAPIError) as exc_info:
        api.get("article")
    assert exc_info.value.status_code == 503
    assert exc_info.value.is_retryable

    article = api.get("article")

    assert article[0].trackingCode == "value"
    assert len(definition_calls) == 2


def test_refresh_reloads_the_definition_cache(make_client, fake_transport):
    api = make_client()
    renamed = {**TRACKING_DEFINITION, "attributeKey": "carrierCode"}
    handler, definition_calls = _router([{"result": [TRACKING_DEFINITION]}, {"result": [renamed]}])
    fake_transport(api, handler=handler)

    assert api.get("article")[0].trackingCode == "value"
    assert api.refresh_attribute_definitions() == {"definition-1": renamed}
    assert api.get("article")[0].carrierCode == "value"
    assert len(definition_calls) == 2
