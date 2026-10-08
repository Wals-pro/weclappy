"""Merging of ``additionalProperties`` and ``referencedEntities`` across pages."""

from weclappy import WeclappResponse


def test_additional_properties_are_extended_across_pages(make_client, fake_transport):
    api = make_client()
    fake_transport(
        api,
        {
            "result": [{"id": "1"}, {"id": "2"}],
            "additionalProperties": {"totalStockQuantity": [{"value": 10}, {"value": 20}]},
        },
        {
            "result": [{"id": "3"}, {"id": "4"}],
            "additionalProperties": {"totalStockQuantity": [{"value": 30}, {"value": 40}]},
        },
        {"result": []},
    )

    response = api.get_all(
        "article",
        {"pageSize": 2, "additionalProperties": "totalStockQuantity"},
        threaded=False,
        return_weclapp_response=True,
    )

    stock = response.additional_properties["totalStockQuantity"]
    assert len(stock) == 4
    assert stock[0]["value"] == 10
    assert stock[2]["value"] == 30
    assert response.result[3].totalStockQuantity == {"value": 40}


def test_referenced_entities_are_merged_and_deduplicated_across_pages(make_client, fake_transport):
    api = make_client()
    fake_transport(
        api,
        {
            "result": [{"id": "1", "unitId": "unit1"}],
            "referencedEntities": {"unit": [{"id": "unit1", "name": "Piece"}]},
        },
        {
            "result": [{"id": "2", "unitId": "unit2"}],
            "referencedEntities": {
                "unit": [
                    {"id": "unit1", "name": "Piece"},  # duplicate entity
                    {"id": "unit2", "name": "Box"},  # new entity
                ]
            },
        },
        {"result": []},
    )

    response = api.get_all(
        "article",
        {"pageSize": 1, "includeReferencedEntities": "unitId"},
        threaded=False,
        return_weclapp_response=True,
    )

    assert len(response.referenced_entities["unit"]) == 2
    assert "unit1" in response.referenced_entities["unit"]
    assert "unit2" in response.referenced_entities["unit"]
    assert [row.unit.name for row in response.result] == ["Piece", "Box"]


def test_integration_with_weclapp_response():
    api_response = {
        "result": [{"id": "1", "name": "Article 1"}, {"id": "2", "name": "Article 2"}],
        "additionalProperties": {
            "totalStockQuantity": [{"value": 10}, {"value": 20}],
            "currentSalesPrice": [{"articleUnitPrice": "39.95"}, {"articleUnitPrice": "49.95"}],
        },
        "referencedEntities": {
            "unit": [{"id": "unit1", "name": "Piece"}, {"id": "unit2", "name": "Box"}]
        },
    }

    response = WeclappResponse.from_api_response(api_response)

    assert len(response.result) == 2
    assert response.result[0]["name"] == "Article 1"
    assert len(response.additional_properties["totalStockQuantity"]) == 2
    assert response.additional_properties["totalStockQuantity"][0]["value"] == 10
    assert len(response.referenced_entities["unit"]) == 2
    assert response.referenced_entities["unit"]["unit1"]["name"] == "Piece"
