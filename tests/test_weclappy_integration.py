# tests/test_weclappy_integration.py

import os
import time
import uuid
import pytest
from weclappy import Weclapp, WeclappAPIError

@pytest.fixture(scope="module")
def client() -> Weclapp:
    """
    Fixture to create a Weclapp client using environment variables.
    Skips tests if the required environment variables are not set.
    """
    base_url = os.environ.get("WECLAPP_BASE_URL")
    api_key = os.environ.get("WECLAPP_API_KEY")
    if not base_url or not api_key:
        pytest.skip("Environment variables WECLAPP_BASE_URL and WECLAPP_API_KEY must be set for integration tests.")
    return Weclapp(base_url, api_key)

def test_get_all_salesorders(client: Weclapp) -> None:
    """
    Test that get_all returns a list from the 'salesOrder' endpoint.
    """
    try:
        results = client.get_all("salesOrder", limit=5)
    except WeclappAPIError as e:
        pytest.skip(f"API not accessible or no sales orders available: {e}")
    assert isinstance(results, list)

def test_get_salesorder_by_id(client: Weclapp) -> None:
    """
    Test retrieving a single salesOrder record using a known id.
    The salesOrder id must be provided in the environment variable WECLAPP_TEST_SALESORDER_ID.
    """
    salesorder_id = os.environ.get("WECLAPP_TEST_SALESORDER_ID")
    if not salesorder_id:
        pytest.skip("Environment variable WECLAPP_TEST_SALESORDER_ID not set for test_get_salesorder_by_id.")
    record = client.get("salesOrder", id=salesorder_id)
    assert isinstance(record, dict)
    assert record.get("id") == salesorder_id

def test_create_update_delete_salesorder(client: Weclapp) -> None:
    """
    Test creating a salesOrder record, updating it, and then deleting it.
    This test performs write operations on the test environment.
    """
    customer_id = os.environ.get("WECLAPP_TEST_CUSTOMER_ID")
    # Create a unique order number for testing
    unique_order_number = f"TEST-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    create_payload = {
        "customerId": customer_id,
        "orderNumber": unique_order_number,
        "description": "Test Sales Order created by integration tests"
    }
    created = client.post("salesOrder", data=create_payload)
    assert isinstance(created, dict)
    assert "id" in created
    record_id = created["id"]

    # Verify creation by fetching the new record
    created_record = client.get("salesOrder", id=record_id)
    assert isinstance(created_record, dict)
    assert created_record.get("orderNumber") == unique_order_number

    # Update the record using the proper endpoint pattern (e.g., salesOrder/id/{id})
    update_payload = {
        "orderNumber": unique_order_number,
        "description": "Updated Test Sales Order"
    }
    updated = client.put(f"salesOrder/id/{record_id}", data=update_payload)
    assert isinstance(updated, dict)
    assert updated.get("id") == record_id
    if "description" in updated:
        assert updated["description"] == "Updated Test Sales Order"

    # Delete the record.
    # Use dryRun mode if you do not want to permanently delete test data.
    delete_response = client.delete("salesOrder", id=record_id, params={"dryRun": True})
    assert isinstance(delete_response, dict)