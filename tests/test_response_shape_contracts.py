"""Focused contracts for paginated response shaping.

All transport is mocked.  These tests mirror weclapp's documented
``additionalProperties`` alignment and ``referencedEntities`` side-loading,
including the valid colon-projection response that omits referenced IDs.
"""

import threading
from unittest.mock import MagicMock

import pytest

from weclappy import Weclapp, WeclappAPIError, WeclappResponse


BASE_URL = "https://tenant.weclapp.com/webapp/api/v2"


def client():
    return Weclapp(BASE_URL, "secret-token")


def test_colon_projected_reference_without_id_remains_available_raw():
    payload = {
        "result": [{"id": "4137", "articleNumber": "EPM242J"}],
        "referencedEntities": {"unit": [{"name": "Stk."}]},
    }

    response = WeclappResponse.from_api_response(payload)

    # The existing ID-indexed view remains safe for lazy resolution.
    assert response.referenced_entities == {"unit": {}}
    # The documented ``unit:name`` shape is still directly accessible even
    # though it cannot be indexed by ID.
    assert response.raw_referenced_entities is payload["referencedEntities"]
    assert response.raw_referenced_entities["unit"] == [{"name": "Stk."}]


def test_colon_projected_reference_with_id_remains_lazy_resolvable():
    api = client()
    api._send_request = MagicMock(
        return_value={
            "result": [
                {"id": "4137", "articleNumber": "EPM242J", "unitId": "2770"}
            ],
            "referencedEntities": {
                "unit": [{"id": "2770", "name": "Stk."}]
            },
        }
    )
    params = {
        "properties": "id,articleNumber,unitId,unit:id,unit:name",
        "includeReferencedEntities": "unitId",
    }

    response = api.get("article", params=params, return_weclapp_response=True)

    assert response.result[0].unit.name == "Stk."
    assert response.referenced_entities["unit"]["2770"]["name"] == "Stk."
    assert response.raw_referenced_entities == {
        "unit": [{"id": "2770", "name": "Stk."}]
    }
    assert api._send_request.call_args.kwargs["params"] == params


def test_get_all_aligns_missing_late_and_short_additional_properties():
    api = client()
    api._send_request = MagicMock(
        side_effect=[
            {
                "result": [{"id": "1"}, {"id": "2"}],
                "additionalProperties": {
                    "currentSalesPrice": [{"articleUnitPrice": "10.00"}]
                },
            },
            {
                "result": [{"id": "3"}, {"id": "4"}],
                "additionalProperties": {
                    "totalStockQuantity": [{"value": "30"}]
                },
            },
            {"result": [{"id": "5"}]},
        ]
    )

    response = api.get_all(
        "article",
        params={
            "pageSize": 2,
            "properties": "id",
            "additionalProperties": "currentSalesPrice,totalStockQuantity",
        },
        threaded=False,
        return_weclapp_response=True,
    )

    assert response.additional_properties == {
        "currentSalesPrice": [
            {"articleUnitPrice": "10.00"},
            None,
            None,
            None,
            None,
        ],
        "totalStockQuantity": [None, None, {"value": "30"}, None, None],
    }
    assert [row.currentSalesPrice for row in response.result] == [
        {"articleUnitPrice": "10.00"},
        None,
        None,
        None,
        None,
    ]
    assert [row.totalStockQuantity for row in response.result] == [
        None,
        None,
        {"value": "30"},
        None,
        None,
    ]


def test_threaded_get_all_restores_page_order_with_properties_and_references():
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
            return {
                "result": [
                    {"id": "1", "unitId": "u1"},
                    {"id": "2", "unitId": "u1"},
                ],
                "additionalProperties": {
                    "currentSalesPrice": [
                        {"articleUnitPrice": "10.00"},
                        {"articleUnitPrice": "20.00"},
                    ]
                },
                "referencedEntities": {
                    "unit": [{"id": "u1", "name": "Piece"}]
                },
            }
        assert page_one_started.wait(2)
        page_two_finished.set()
        return {
            "result": [
                {"id": "3", "unitId": "u2"},
                {"id": "4", "unitId": "u2"},
            ],
            "additionalProperties": {
                "currentSalesPrice": [
                    {"articleUnitPrice": "30.00"},
                    {"articleUnitPrice": "40.00"},
                ]
            },
            "referencedEntities": {
                "unit": [{"id": "u2", "name": "Box"}]
            },
        }

    api._send_request = fake_send

    response = api.get_all(
        "article",
        params={
            "pageSize": 2,
            "properties": "id,unitId,unit:id,unit:name",
            "additionalProperties": "currentSalesPrice",
            "includeReferencedEntities": "unitId",
        },
        threaded=True,
        max_workers=2,
        return_weclapp_response=True,
    )

    assert [row.id for row in response.result] == ["1", "2", "3", "4"]
    assert [row.currentSalesPrice.articleUnitPrice for row in response.result] == [
        "10.00",
        "20.00",
        "30.00",
        "40.00",
    ]
    assert [row.unit.name for row in response.result] == [
        "Piece",
        "Piece",
        "Box",
        "Box",
    ]
    assert response.raw_referenced_entities == {
        "unit": [
            {"id": "u1", "name": "Piece"},
            {"id": "u2", "name": "Box"},
        ]
    }


def test_get_all_rejects_duplicate_ids_across_sequential_pages():
    api = client()
    api._send_request = MagicMock(
        side_effect=[
            {"result": [{"id": "1"}, {"id": "2"}]},
            {"result": [{"id": "2"}, {"id": "4"}]},
        ]
    )

    with pytest.raises(
        WeclappAPIError,
        match=r"Pagination for 'article'.*duplicate entity id '2'.*page 2",
    ):
        api.get_all(
            "article",
            params={"pageSize": 2, "properties": "id", "sort": "id"},
            threaded=False,
        )


def test_get_all_rejects_duplicate_ids_across_threaded_pages():
    api = client()

    def fake_send(method, url, **kwargs):
        if url.endswith("/article/count"):
            return {"result": 4}
        if kwargs["params"]["page"] == 1:
            return {"result": [{"id": "1"}, {"id": "2"}]}
        return {"result": [{"id": "2"}, {"id": "4"}]}

    api._send_request = fake_send

    with pytest.raises(
        WeclappAPIError,
        match=r"Pagination for 'article'.*duplicate entity id '2'.*page 2",
    ):
        api.get_all(
            "article",
            params={"pageSize": 2, "properties": "id", "sort": "id"},
            threaded=True,
            max_workers=2,
        )


def test_get_all_does_not_claim_duplicate_detection_without_projected_ids():
    api = client()
    api._send_request = MagicMock(
        side_effect=[
            {"result": [{"name": "same"}, {"name": "same"}]},
            {"result": [{"name": "same"}]},
        ]
    )

    rows = api.get_all(
        "article",
        params={"pageSize": 2, "properties": "name", "sort": "name"},
        threaded=False,
    )

    assert [row.name for row in rows] == ["same", "same", "same"]


def test_threaded_count_removes_ordering_and_response_shape_parameters():
    api = client()
    api._send_request = MagicMock(return_value={"result": 0})
    params = {
        "active-eq": True,
        "page": 9,
        "pageSize": 200,
        "orderBy": "lower(name)",
        "properties": "id,name",
        "additionalProperties": "currentSalesPrice",
        "includeReferencedEntities": "unitId",
        "serializeNulls": True,
    }

    assert api.get_all("article", params=params, threaded=True) == []

    assert api._send_request.call_args.args[1].endswith("/article/count")
    assert api._send_request.call_args.kwargs["params"] == {"active-eq": True}
    assert params["orderBy"] == "lower(name)"


def test_iter_all_preserves_per_page_additional_properties_and_references():
    api = client()
    api._send_request = MagicMock(
        side_effect=[
            {
                "result": [
                    {"id": "1", "unitId": "u1"},
                    {"id": "2", "unitId": "u2"},
                ],
                "additionalProperties": {
                    "currentSalesPrice": [{"articleUnitPrice": "10.00"}]
                },
                "referencedEntities": {
                    "unit": [
                        {"id": "u1", "name": "Piece"},
                        {"id": "u2", "name": "Box"},
                    ]
                },
            },
            {
                "result": [{"id": "3", "unitId": "u3"}],
                "additionalProperties": {
                    "currentSalesPrice": [{"articleUnitPrice": "30.00"}]
                },
                "referencedEntities": {
                    "unit": [{"id": "u3", "name": "Pallet"}]
                },
            },
        ]
    )

    rows = list(
        api.iter_all(
            "article",
            params={
                "pageSize": 2,
                "properties": "id,unitId,unit:id,unit:name",
                "additionalProperties": "currentSalesPrice",
                "includeReferencedEntities": "unitId",
                "sort": "id",
            },
        )
    )

    assert [row.id for row in rows] == ["1", "2", "3"]
    assert rows[0].currentSalesPrice.articleUnitPrice == "10.00"
    assert rows[1].currentSalesPrice is None
    assert rows[2].currentSalesPrice.articleUnitPrice == "30.00"
    assert [row.unit.name for row in rows] == ["Piece", "Box", "Pallet"]


def test_iter_all_rejects_duplicate_ids_before_yielding_the_second_page():
    api = client()
    api._send_request = MagicMock(
        side_effect=[
            {"result": [{"id": "1"}, {"id": "2"}]},
            {"result": [{"id": "2"}]},
        ]
    )
    iterator = api.iter_all(
        "article",
        params={"pageSize": 2, "properties": "id", "sort": "id"},
    )

    assert next(iterator).id == "1"
    assert next(iterator).id == "2"
    with pytest.raises(
        WeclappAPIError,
        match=r"Pagination for 'article'.*duplicate entity id '2'.*page 2",
    ):
        next(iterator)
