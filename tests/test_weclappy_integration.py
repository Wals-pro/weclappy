# tests/test_weclappy_integration.py

import os
import time
import uuid
import pytest
import logging
from weclappy import Weclapp, WeclappAPIError, WeclappResponse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
        logger.info(f"Retrieved {len(results)} sales orders")
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
    if not customer_id:
        pytest.skip("WECLAPP_TEST_CUSTOMER_ID environment variable not set")

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

def test_get_articles_with_additional_properties(client: Weclapp) -> None:
    """
    Test getting articles with additionalProperties parameter.
    """
    try:
        # Define the additional properties to request
        additional_props = ["totalStockQuantity", "averagePrice", "currentSalesPrice"]

        # Get articles with additional properties
        response = client.get(
            "article",
            params={
                "page": 1,
                "pageSize": 5,
                "additionalProperties": ",".join(additional_props)
            },
            return_weclapp_response=True
        )

        logger.info(f"Retrieved {len(response.result)} articles with additional properties")

        # Print the raw response structure for debugging
        logger.info(f"Response keys: {list(response.raw_response.keys())}")

        # Check if additionalProperties is in the response
        if response.additional_properties:
            logger.info("Additional properties found in response")
            for prop_name, prop_values in response.additional_properties.items():
                logger.info(f"Property: {prop_name}, Values: {len(prop_values)}")
                assert prop_name in additional_props
        else:
            logger.warning("No additional properties found in response")

    except WeclappAPIError as e:
        pytest.skip(f"Failed to get articles with additional properties: {e}")

    assert isinstance(response, WeclappResponse)
    assert isinstance(response.result, list)

def test_get_articles_with_referenced_entities(client: Weclapp) -> None:
    """
    Test getting articles with includeReferencedEntities parameter.
    """
    try:
        # Define the referenced entities to request
        referenced_entities = ["unitId", "articleCategoryId"]

        # Get articles with referenced entities
        response = client.get(
            "article",
            params={
                "page": 1,
                "pageSize": 5,
                "includeReferencedEntities": ",".join(referenced_entities)
            },
            return_weclapp_response=True
        )

        logger.info(f"Retrieved {len(response.result)} articles with referenced entities")

        # Print the raw response structure for debugging
        logger.info(f"Response keys: {list(response.raw_response.keys())}")

        # Check if referencedEntities is in the response
        if response.referenced_entities:
            logger.info("Referenced entities found in response")
            for entity_type, entities in response.referenced_entities.items():
                logger.info(f"Entity type: {entity_type}, Entities: {len(entities)}")
        else:
            logger.warning("No referenced entities found in response")

    except WeclappAPIError as e:
        pytest.skip(f"Failed to get articles with referenced entities: {e}")

    assert isinstance(response, WeclappResponse)
    assert isinstance(response.result, list)

def test_get_all_articles_with_both_parameters(client: Weclapp) -> None:
    """
    Test getting all articles with both additionalProperties and includeReferencedEntities parameters.
    """
    try:
        # Define the parameters to request
        additional_props = ["totalStockQuantity"]
        referenced_entities = ["unitId"]

        # Get articles with both parameters
        response = client.get_all(
            "article",
            params={
                "additionalProperties": ",".join(additional_props),
                "includeReferencedEntities": ",".join(referenced_entities)
            },
            limit=5,
            return_weclapp_response=True
        )

        logger.info(f"Retrieved {len(response.result)} articles with both parameters using get_all")

        # Print the raw response structure for debugging
        logger.info(f"Response keys: {list(response.raw_response.keys())}")

        # Check if additionalProperties is in the response
        if response.additional_properties:
            logger.info("Additional properties found in response")
            for prop_name, prop_values in response.additional_properties.items():
                logger.info(f"Property: {prop_name}, Values: {len(prop_values)}")
        else:
            logger.warning("No additional properties found in response")

        # Check if referencedEntities is in the response
        if response.referenced_entities:
            logger.info("Referenced entities found in response")
            for entity_type, entities in response.referenced_entities.items():
                logger.info(f"Entity type: {entity_type}, Entities: {len(entities)}")
        else:
            logger.warning("No referenced entities found in response")

    except WeclappAPIError as e:
        pytest.skip(f"Failed to get all articles with both parameters: {e}")

    assert isinstance(response, WeclappResponse)
    assert isinstance(response.result, list)

def test_get_sales_invoices_with_referenced_entities(client: Weclapp) -> None:
    """
    Test getting sales invoices with includeReferencedEntities parameter.
    """
    try:
        # Define the referenced entities to request
        referenced_entities = ["customerId"]

        # Get sales invoices with referenced entities
        response = client.get(
            "salesInvoice",
            params={
                "page": 1,
                "pageSize": 5,
                "includeReferencedEntities": ",".join(referenced_entities)
            },
            return_weclapp_response=True
        )

        logger.info(f"Retrieved {len(response.result)} sales invoices with referenced entities")

        # Print the raw response structure for debugging
        logger.info(f"Response keys: {list(response.raw_response.keys())}")

        # Check if referencedEntities is in the response
        if response.referenced_entities:
            logger.info("Referenced entities found in response")
            for entity_type, entities in response.referenced_entities.items():
                logger.info(f"Entity type: {entity_type}, Entities: {len(entities)}")
        else:
            logger.warning("No referenced entities found in response")

    except WeclappAPIError as e:
        pytest.skip(f"Failed to get sales invoices with referenced entities: {e}")

    assert isinstance(response, WeclappResponse)
    assert isinstance(response.result, list)

def test_get_all_articles_threaded(client: Weclapp) -> None:
    """
    Test getting all articles using threaded fetching.
    """
    try:
        # Get articles using threaded fetching
        results = client.get_all(
            "article",
            limit=10,
            threaded=True
        )

        logger.info(f"Retrieved {len(results)} articles with threaded fetching")

        # Basic assertion
        assert isinstance(results, list)
        assert len(results) > 0, "No articles returned from threaded fetch"

    except WeclappAPIError as e:
        pytest.fail(f"Failed to get articles with threaded fetching: {e}")


def test_error_not_found_structured_fields(client: Weclapp) -> None:
    """
    Test that WeclappAPIError provides structured fields for 404 errors.
    """
    # Try to get a non-existent entity
    fake_id = "nonexistent-id-12345678"
    
    with pytest.raises(WeclappAPIError) as exc_info:
        client.get("article", id=fake_id)
    
    error = exc_info.value
    
    # Verify structured error fields
    assert error.status_code == 404
    assert error.is_not_found is True
    assert error.is_optimistic_lock is False
    assert error.is_rate_limited is False
    assert error.response_text is not None
    assert error.url is not None
    
    logger.info(f"404 Error details: status={error.status_code}, error={error.error}, detail={error.detail}")
    logger.info(f"Response text: {error.response_text}")


def test_error_validation_structured_fields(client: Weclapp) -> None:
    """
    Test that WeclappAPIError provides structured fields for validation errors.
    """
    # Try to create an invalid entity (missing required fields)
    invalid_data = {
        "articleNumber": ""  # Empty article number should fail validation
    }
    
    try:
        client.post("article", invalid_data)
        # If no error, the API accepted it - skip the test
        pytest.skip("API did not return a validation error for invalid data")
    except WeclappAPIError as error:
        # Verify structured error fields
        assert error.status_code is not None
        assert error.response_text is not None
        
        logger.info(f"Validation Error details: status={error.status_code}")
        logger.info(f"Error: {error.error}")
        logger.info(f"Detail: {error.detail}")
        logger.info(f"Validation errors: {error.validation_errors}")
        logger.info(f"Messages: {error.messages}")
        logger.info(f"Is validation error: {error.is_validation_error}")
        
        # Get all messages
        all_msgs = error.get_all_messages()
        logger.info(f"All messages: {all_msgs}")
        
        # Basic assertions
        assert error.is_not_found is False


def test_error_helper_methods(client: Weclapp) -> None:
    """
    Test WeclappAPIError helper methods with real API responses.
    """
    # Trigger a 404 error to test helper methods
    fake_id = "nonexistent-id-99999999"
    
    with pytest.raises(WeclappAPIError) as exc_info:
        client.get("salesOrder", id=fake_id)
    
    error = exc_info.value
    
    # Test get_validation_messages (should be empty for 404)
    validation_msgs = error.get_validation_messages()
    assert isinstance(validation_msgs, list)
    
    # Test get_all_messages
    all_msgs = error.get_all_messages()
    assert isinstance(all_msgs, list)
    
    logger.info(f"Validation messages: {validation_msgs}")
    logger.info(f"All messages: {all_msgs}")


def test_successful_request_no_error(client: Weclapp) -> None:
    """
    Test that successful requests don't raise errors and return expected data.
    """
    try:
        # Simple GET request that should succeed
        results = client.get("article", params={"page": 1, "pageSize": 1})
        
        assert isinstance(results, list)
        logger.info(f"Successfully retrieved {len(results)} articles")
        
    except WeclappAPIError as e:
        # Log the full error details for debugging
        logger.error(f"Unexpected error: {e}")
        logger.error(f"Status code: {e.status_code}")
        logger.error(f"Error field: {e.error}")
        logger.error(f"Detail field: {e.detail}")
        logger.error(f"Response text: {e.response_text}")
        pytest.fail(f"Request failed unexpectedly: {e}")