"""Optional live integration contracts for a dedicated weclapp API v2 tenant."""

import logging
import os
import time
import uuid
from typing import Iterator

import pytest

from weclappy import Weclapp, WeclappAPIError, WeclappEntity, WeclappResponse


logger = logging.getLogger(__name__)
pytestmark = pytest.mark.integration

ARTICLE_PROPERTIES = "id,articleNumber,name"
ARTICLE_REFERENCE_PROPERTIES = (
    "id,articleNumber,name,unitId,unit:id,unit:name"
)
SALES_ORDER_CUSTOMER_PROPERTIES = (
    "id,customerId,party:id,party:company,party:firstName,party:lastName"
)


def required_fixture(name: str, description: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"{name} is required: {description}")
    return value


@pytest.fixture(scope="module")
def client() -> Iterator[Weclapp]:
    """Create a client only when explicit live credentials are available."""
    base_url = os.environ.get("WECLAPP_BASE_URL")
    api_key = os.environ.get("WECLAPP_API_KEY")
    if not base_url or not api_key:
        pytest.skip("WECLAPP_BASE_URL and WECLAPP_API_KEY are required")
    if "/webapp/api/v2" not in base_url.rstrip("/"):
        pytest.fail("WECLAPP_BASE_URL must point to /webapp/api/v2")

    live_client = Weclapp(base_url, api_key)
    try:
        yield live_client
    finally:
        live_client.close()


def assert_article_reference_contract(response: WeclappResponse) -> None:
    """Assert native lists, normalized id maps, and entity resolution agree."""
    assert response.result
    native_references = (response.raw_response or {}).get("referencedEntities")
    assert isinstance(native_references, dict)
    native_units = native_references.get("unit")
    assert isinstance(native_units, list)
    assert native_units
    assert all(
        set(unit).issubset({"id", "name"}) and unit.get("id") and unit.get("name")
        for unit in native_units
    )

    normalized_units = (response.referenced_entities or {}).get("unit")
    assert isinstance(normalized_units, dict)
    for article in response.result:
        assert article.unitId in normalized_units
        assert article.unit.id == article.unitId
        assert article.unit.name


def test_get_all_salesorders(client: Weclapp) -> None:
    results = client.get_all(
        "salesOrder",
        params={"properties": "id,orderNumber", "sort": "id"},
        limit=5,
    )
    assert isinstance(results, list)
    assert all(isinstance(order, WeclappEntity) for order in results)


def test_get_salesorder_by_id(client: Weclapp) -> None:
    sales_order_id = required_fixture(
        "WECLAPP_TEST_SALESORDER_ID",
        "id of an existing sales order",
    )
    record = client.get(
        "salesOrder",
        id=sales_order_id,
        params={"properties": "id,orderNumber"},
    )
    assert isinstance(record, WeclappEntity)
    assert record.id == sales_order_id


@pytest.mark.write
def test_create_update_delete_salesorder(client: Weclapp) -> None:
    """Exercise a persistent lifecycle only after a separate explicit opt-in."""
    if os.environ.get("WECLAPP_RUN_WRITE_TESTS") != "1":
        pytest.skip("set WECLAPP_RUN_WRITE_TESTS=1 to run persistent-write tests")

    customer_id = required_fixture(
        "WECLAPP_TEST_CUSTOMER_ID",
        "customer id in an isolated test tenant",
    )
    order_number = f"TEST-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    record_id = None
    create_attempted = False

    try:
        create_attempted = True
        created = client.post(
            "salesOrder",
            data={
                "customerId": customer_id,
                "orderNumber": order_number,
                "description": "Test Sales Order created by integration tests",
            },
        )
        assert isinstance(created, dict)
        record_id = created.get("id")
        assert record_id

        created_record = client.get(
            "salesOrder",
            id=record_id,
            params={"properties": "id,orderNumber,description"},
        )
        assert created_record.orderNumber == order_number

        updated = client.put(
            "salesOrder",
            id=record_id,
            data={
                "orderNumber": order_number,
                "description": "Updated Test Sales Order",
            },
        )
        assert isinstance(updated, dict)
        assert updated.get("id") == record_id
    finally:
        if create_attempted and record_id is None:
            candidates = client.get(
                "salesOrder",
                params={
                    "orderNumber-eq": order_number,
                    "pageSize": 2,
                    "properties": "id",
                    "sort": "id",
                },
            )
            if len(candidates) == 1:
                record_id = candidates[0].id
        if record_id is not None:
            logger.info("Deleting integration-test sales order %s", record_id)
            assert client.delete("salesOrder", id=record_id) == {}


def test_get_articles_with_additional_properties(client: Weclapp) -> None:
    requested = ["totalStockQuantity", "averagePrice", "currentSalesPrice"]
    response = client.get(
        "article",
        params={
            "page": 1,
            "pageSize": 5,
            "properties": ARTICLE_PROPERTIES,
            "additionalProperties": ",".join(requested),
            "sort": "id",
        },
        return_weclapp_response=True,
    )
    if not response.result:
        pytest.skip("tenant has no articles for the additionalProperties fixture")

    assert isinstance(response, WeclappResponse)
    assert set(response.additional_properties or {}) == set(requested)
    for name in requested:
        values = response.additional_properties[name]
        assert len(values) == len(response.result)
        assert all(
            article.get(name) == values[index]
            for index, article in enumerate(response.result)
        )
        assert all(name not in article.to_payload() for article in response.result)


def test_get_articles_with_referenced_entities(client: Weclapp) -> None:
    response = client.get(
        "article",
        params={
            "unitId-notnull": "true",
            "page": 1,
            "pageSize": 5,
            "properties": ARTICLE_REFERENCE_PROPERTIES,
            "includeReferencedEntities": "unitId",
            "sort": "id",
        },
        return_weclapp_response=True,
    )
    if not response.result:
        pytest.skip("tenant has no article with a unitId reference")
    assert_article_reference_contract(response)


def test_get_all_articles_with_both_parameters(client: Weclapp) -> None:
    response = client.get_all(
        "article",
        params={
            "unitId-notnull": "true",
            "pageSize": 2,
            "properties": ARTICLE_REFERENCE_PROPERTIES,
            "additionalProperties": "currentSalesPrice",
            "includeReferencedEntities": "unitId",
            "sort": "id",
        },
        limit=5,
        return_weclapp_response=True,
    )
    if not response.result:
        pytest.skip("tenant has no article with a unitId reference")

    prices = (response.additional_properties or {}).get("currentSalesPrice")
    assert isinstance(prices, list)
    assert len(prices) == len(response.result)
    assert_article_reference_contract(response)


def test_get_sales_invoices_with_referenced_entities(client: Weclapp) -> None:
    response = client.get(
        "salesInvoice",
        params={
            "customerId-notnull": "true",
            "page": 1,
            "pageSize": 5,
            "properties": (
                "id,invoiceNumber,customerId,party:id,party:company,"
                "party:firstName,party:lastName"
            ),
            "includeReferencedEntities": "customerId",
            "sort": "id",
        },
        return_weclapp_response=True,
    )
    if not response.result:
        pytest.skip("tenant has no sales invoice with a customerId reference")

    native_parties = (response.raw_response or {}).get("referencedEntities", {}).get(
        "party"
    )
    assert isinstance(native_parties, list)
    normalized_parties = (response.referenced_entities or {}).get("party")
    assert isinstance(normalized_parties, dict)
    for invoice in response.result:
        assert invoice.customerId in normalized_parties
        assert invoice.customer.id == invoice.customerId


def test_get_all_articles_threaded(client: Weclapp) -> None:
    params = {
        "pageSize": 2,
        "properties": ARTICLE_PROPERTIES,
        "sort": "id",
    }
    sequential = client.get_all("article", params=params, limit=10)
    if not sequential:
        pytest.skip("tenant has no articles for pagination")
    threaded = client.get_all(
        "article",
        params=params,
        limit=10,
        threaded=True,
        max_workers=2,
    )
    assert [article.id for article in threaded] == [
        article.id for article in sequential
    ]


def test_error_not_found_structured_fields(client: Weclapp) -> None:
    missing_id = required_fixture(
        "WECLAPP_TEST_MISSING_ARTICLE_ID",
        "valid-format numeric article id known not to exist",
    )
    with pytest.raises(WeclappAPIError) as exc_info:
        client.get("article", id=missing_id, params={"properties": "id"})

    error = exc_info.value
    assert error.status_code == 404
    assert error.is_not_found is True
    assert error.is_optimistic_lock is False
    assert error.is_rate_limited is False
    assert error.response_text is not None
    assert error.url is not None


def test_error_validation_structured_fields(client: Weclapp) -> None:
    """Unknown properties are a stable 400 contract and dryRun cannot persist."""
    with pytest.raises(WeclappAPIError) as exc_info:
        client.post(
            "article",
            data={"__weclappyUnknownProperty": True},
            params={"dryRun": True},
        )

    error = exc_info.value
    assert error.status_code == 400
    assert error.response_text is not None
    assert error.is_not_found is False
    assert isinstance(error.get_all_messages(), list)


def test_error_helper_methods(client: Weclapp) -> None:
    missing_id = required_fixture(
        "WECLAPP_TEST_MISSING_ARTICLE_ID",
        "valid-format numeric article id known not to exist",
    )
    with pytest.raises(WeclappAPIError) as exc_info:
        client.get("article", id=missing_id, params={"properties": "id"})

    error = exc_info.value
    assert error.get_validation_messages() == []
    assert isinstance(error.get_all_messages(), list)


def test_entity_dot_access_and_referenced_id_resolve(client: Weclapp) -> None:
    orders = client.get_all(
        "salesOrder",
        params={
            "customerId-notnull": "true",
            "properties": SALES_ORDER_CUSTOMER_PROPERTIES,
            "includeReferencedEntities": "customerId",
            "sort": "id",
        },
        limit=1,
    )
    if not orders:
        pytest.skip("tenant has no sales order with a customerId reference")
    order = orders[0]
    assert isinstance(order, WeclappEntity)
    assert order.id == order["id"]
    assert order.customer.id == order.customerId


def test_entity_nested_wrapping_against_real_order(client: Weclapp) -> None:
    orders = client.get_all(
        "salesOrder",
        params={
            "properties": (
                "id,orderItems.id,orderItems.articleId,orderItems.unitId,"
                "article:id,unit:id"
            ),
            "includeReferencedEntities": (
                "orderItems.articleId,orderItems.unitId"
            ),
            "sort": "id",
        },
        limit=20,
    )
    target = next(
        (
            (order, item)
            for order in orders
            for item in (order.get("orderItems") or [])
            if item.get("articleId") and item.get("unitId")
        ),
        None,
    )
    if target is None:
        pytest.skip("no sampled sales-order item has articleId and unitId")

    order, item = target
    assert isinstance(item, WeclappEntity)
    assert item.article.id == item.articleId
    assert item.unit.id == item.unitId
    assert item is order.orderItems[order.orderItems.index(item)]
    assert item.article is item.article


def test_custom_attribute_flatten_and_round_trip(client: Weclapp) -> None:
    """Dry-run only a present, projected custom attribute with readOnly=false."""
    definitions = client.get_all(
        "customAttributeDefinition",
        params={
            "active-eq": "true",
            "readOnly-eq": "false",
            "properties": "id,attributeKey,attributeType,readOnly",
            "sort": "id",
        },
    )
    writable_string_definitions = {
        definition.id: definition
        for definition in definitions
        if definition.get("readOnly") is False
        and definition.get("attributeType") in {"STRING", "LARGE_TEXT"}
        and isinstance(definition.get("attributeKey"), str)
    }
    if not writable_string_definitions:
        pytest.skip("tenant has no active writable string custom attribute")

    articles = client.get_all(
        "article",
        params={
            "properties": "id,version,customAttributes",
            "sort": "id",
        },
        limit=200,
    )
    target = next(
        (
            (article, name, definition_id)
            for article in articles
            for custom_attribute in (article.get("customAttributes") or [])
            for definition_id in [
                custom_attribute.get("attributeDefinitionId")
            ]
            if definition_id in writable_string_definitions
            for name in [writable_string_definitions[definition_id].attributeKey]
            if "stringValue" in custom_attribute
            and name in article._custom_attr_index
            and not hasattr(WeclappEntity, name)
        ),
        None,
    )
    if target is None:
        pytest.skip(
            "no sampled article contains an active writable string custom attribute"
        )

    article, name, definition_id = target
    definition = writable_string_definitions[definition_id]
    assert definition.readOnly is False
    assert definition.attributeKey == name

    setattr(article, name, "weclappy-dry-run")
    payload = article.to_payload()
    custom_attributes = {
        item["attributeDefinitionId"]: item for item in payload["customAttributes"]
    }
    assert custom_attributes[definition_id]["stringValue"] == "weclappy-dry-run"
    client.put(
        "article",
        id=article.id,
        data=payload,
        params={"dryRun": True},
    )


def test_successful_request_no_error(client: Weclapp) -> None:
    results = client.get(
        "article",
        params={
            "page": 1,
            "pageSize": 1,
            "properties": "id",
            "sort": "id",
        },
    )
    assert isinstance(results, list)
