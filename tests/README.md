# Weclappy Tests

This directory contains tests for the weclappy library.

## Test Types

1. **Unit Tests**: Tests that mock the API responses and verify the library's functionality without making actual API calls.
2. **Integration Tests**: Tests that make actual API calls to verify the library works correctly with the weclapp API.

## Running Tests

### Prerequisites

- Python 3.6+
- pytest (`pip install pytest`)
- pytest-cov (optional, for coverage reports: `pip install pytest-cov`)

### Environment Setup

For integration tests, you need to set the following environment variables:

```bash
export WECLAPP_BASE_URL="https://your-instance.weclapp.com/webapp/api/v1"
export WECLAPP_API_KEY="your-api-key"
```

For specific tests that require existing records:

```bash
export WECLAPP_TEST_SALESORDER_ID="existing-sales-order-id"
export WECLAPP_TEST_CUSTOMER_ID="existing-customer-id"
```

### Running Unit Tests

```bash
# Run all unit tests
pytest tests/test_weclappy_unit.py -v

# Run a specific test
pytest tests/test_weclappy_unit.py::TestWeclappUnit::test_get_with_additional_properties -v
```

### Running Integration Tests

```bash
# Run all integration tests
pytest tests/test_weclappy_integration.py -v

# Run a specific test
pytest tests/test_weclappy_integration.py::test_get_articles_with_additional_properties -v
```

### Running All Tests with Coverage

```bash
pytest --cov=weclappy tests/
```

## Test Features

The tests verify the following features:

1. **Basic API Operations**:
   - GET, POST, PUT, DELETE operations
   - Fetching single entities and lists of entities
   - Pagination with `get_all` method

2. **Advanced Features**:
   - `additionalProperties` parameter for fetching additional calculated properties
   - `includeReferencedEntities` parameter for fetching referenced entities
   - Structured response handling with `WeclappResponse` class

3. **Error Handling**:
   - Proper error handling for API errors
   - Validation of parameters

## Test Structure

- `test_weclappy_unit.py`: Unit tests that mock API responses
- `test_weclappy_integration.py`: Integration tests that make actual API calls

## Notes

- Integration tests are skipped if the required environment variables are not set
- Some tests use `dryRun=True` to avoid making permanent changes to your data
- The tests print detailed logs to help diagnose issues
