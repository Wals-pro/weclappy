# weclappy

The weclapp Python Client.

## Motivation

There is no lightweight, simple weclapp client library available for Python currently. Let's build it together.

## Disclaimer

This package is not affiliated with weclapp GmbH in any way. This is an independent project and subject to constant development and improvement. Until an official release of version 1.0.0, the API may change without notice, breaking your code. This is a mandatory step in the development of any software library to incrementally improve the library quickly and by that be able to fully support the weclapp API soon.

## Overview

The goal of this library is to provide a minimal, threaded client that handles pagination effectively when fetching lists from the weclapp API. It is capable of retrieving large volumes of data by parallelizing page requests, significantly reducing wait times. This library is designed to be lean with no unnecessary bloat, allowing you to get started very quickly.

## Features

- **Threaded Pagination:** Fetch multiple pages concurrently for enhanced performance.
- **Document & Image Uploads:** Upload binary files with automatic content type inference.
- **Binary Downloads:** Download documents, images, and PDFs with a simple API.
- **Additional Properties & Referenced Entities:** Support for weclapp API's additionalProperties and referencedEntities parameters.
- **Structured Response:** Optional WeclappResponse class to handle complex API responses.
- **Enhanced Error Handling:** Structured error parsing with helper properties for common error types (404, 429, validation errors, optimistic lock conflicts).
- **Minimal Dependencies:** Only dependency is [`requests`](https://pypi.org/project/requests/).
- **Simplicity:** A lean bloat free solution to interact with the weclapp API.
- **Open Source:** Free to use in any project, with contributions and improvements highly welcome.

## Installation

Install the package via pip:

```bash
pip install weclappy
```

## Quick Start

```python

from weclappy import Weclapp

# Initialize the client with your base URL and API key
client = Weclapp("https://acme.weclapp.com/webapp/api/v1", "your_api_key")

# Fetch a single entity by ID, e.g., 'salesOrder' with ID '12345'
sales_order = client.get("salesOrder", id="12345")

# Fetch paginated results for an entity, e.g., 'salesOrder' with a filter
sales_orders = client.get_all("salesOrder", { "salesOrderPaymentType-eq": "ADVANCE_PAYMENT" }, threaded=True)

# Create a new entity, e.g., 'salesOrder'
new_sales_order = client.post("salesOrder", { "customerId": "12345", "commission": "Hello, world!" })

# Update an existing entity, e.g., 'salesOrder' with ID '12345', ignoreMissingProperties is True per default
updated_sales_order = client.put("salesOrder", id="12345", data={ "commission": "Hello, universe!" })

# Delete an entity, e.g., 'salesOrder' with ID '12345'
client.delete("salesOrder", id="12345")

# Get an invoice PDF
pdf_response = client.call_method("salesInvoice", "downloadLatestSalesInvoicePdf", sales_invoice["id"], method="GET")
# { "content": b"...", "content-type": "application/pdf" }

if "content" in pdf_response:
    pdf_bytes = pdf_response["content"]
    filename = "Rechnung.pdf"

    # Save the PDF to disk
    with open(filename, "wb") as f:
        f.write(pdf_bytes)
else:
    # Otherwise, it's likely an error
    print("Response:", pdf_response)

# Using additionalProperties and referencedEntities
from weclappy import WeclappResponse

# Get all sales orders with customer details and referenced entities
sales_order_response = client.get_all(
    "salesOrder",
    limit=10,
    params={
        "additionalProperties": "customer,positions",  # Comma-separated property names
        "includeReferencedEntities": "customerId,positions.articleId"  # Comma-separated property paths
    },
    return_weclapp_response=True
)

# Access the main result
sales_order = sales_order_response.result
print(f"Sales Order: {sales_order['orderNumber']}")

# Access additional properties if available
if sales_order_response.additional_properties:
    customer_data = sales_order_response.additional_properties.get("customer")
    if customer_data:
        print(f"Customer: {customer_data[0].get('name')}")

# Access referenced entities if available
if sales_order_response.referenced_entities:
    customer_id = sales_order["customerId"]
    customer = sales_order_response.referenced_entities.get("customer", {}).get(customer_id)
    if customer:
        print(f"Customer: {customer.get('name')}")
```

## Threaded Pagination

The `get_all` method supports threaded pagination, which can significantly improve performance when fetching large datasets:

```python
# Fetch all sales orders with threaded pagination
sales_orders = client.get_all("salesOrder", threaded=True, max_workers=10)
```

By default, `max_workers` is set to 10, but you can adjust this based on your needs.

## Structured Response

When using `additionalProperties` or `includeReferencedEntities`, you can get a structured response by setting `return_weclapp_response=True`:

```python
response = client.get_all(
    "salesOrder",
    params={
        "additionalProperties": "customer",
        "includeReferencedEntities": "customerId"
    },
    return_weclapp_response=True
)

# Access the main result
orders = response.result

# Access additional properties
customer_data = response.additional_properties.get("customer")

# Access referenced entities
customer_entities = response.referenced_entities.get("customer")
```

## Error Handling

The library raises `WeclappAPIError` for API-related errors. The exception provides structured access to error details from the Weclapp API response.

### Basic Usage

```python
from weclappy import Weclapp, WeclappAPIError

client = Weclapp("https://acme.weclapp.com/webapp/api/v1", "your_api_key")

try:
    result = client.get("article", id="nonexistent-id")
except WeclappAPIError as e:
    print(f"API Error: {e}")
    print(f"Status Code: {e.status_code}")
    print(f"Raw Response: {e.response_text}")
```

### Structured Error Fields

The `WeclappAPIError` exception parses JSON error responses and provides these attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `status_code` | `int` | HTTP status code (e.g., 404, 400, 500) |
| `response_text` | `str` | Raw response body text |
| `error` | `str` | Error message from the API |
| `detail` | `str` | Detailed error description |
| `title` | `str` | Error title |
| `error_type` | `str` | Error type identifier |
| `validation_errors` | `list` | List of validation error objects |
| `messages` | `list` | List of additional messages with severity |
| `url` | `str` | The request URL that caused the error |
| `response` | `Response` | The raw requests.Response object |

### Helper Properties

Convenient boolean properties for common error types:

```python
try:
    client.put("article", id="123", data={"name": "Test"})
except WeclappAPIError as e:
    if e.is_not_found:
        print("Entity does not exist")
    elif e.is_optimistic_lock:
        print("Version conflict - entity was modified by another process")
    elif e.is_rate_limited:
        print("Too many requests - implement backoff and retry")
    elif e.is_validation_error:
        print("Invalid data submitted")
```

### Helper Methods

Extract error messages in a convenient format:

```python
try:
    client.post("article", {"articleNumber": ""})
except WeclappAPIError as e:
    # Get just validation error messages
    for msg in e.get_validation_messages():
        print(f"Validation: {msg}")
    
    # Get all error messages (includes error, detail, validation, and messages)
    for msg in e.get_all_messages():
        print(f"Error: {msg}")
```

### Programmatic Error Handling Pattern

```python
def safe_get_entity(client, entity_type, entity_id):
    """Example of programmatic error handling."""
    try:
        return client.get(entity_type, id=entity_id)
    except WeclappAPIError as e:
        if e.is_not_found:
            return None  # Entity doesn't exist
        elif e.is_rate_limited:
            time.sleep(60)  # Wait and retry
            return safe_get_entity(client, entity_type, entity_id)
        elif e.is_optimistic_lock:
            # Refresh entity and retry update
            raise
        elif e.is_validation_error:
            # Log validation details for debugging
            print(f"Validation failed: {e.get_validation_messages()}")
            raise
        else:
            raise  # Re-raise unexpected errors
```

## Document & Image Uploads

Upload binary files (documents, images) to weclapp entities using the `upload()` method. Content type is automatically inferred from the filename extension, with optional override.

### Upload a Document

```python
# Read file content
with open("invoice.pdf", "rb") as f:
    data = f.read()

# Upload document to a sales order
doc = client.upload(
    "document",
    data=data,
    action="upload",
    filename="invoice.pdf",  # Content type inferred as application/pdf
    params={
        "entityName": "salesOrder",
        "entityId": "12345",
        "name": "Invoice.pdf",
        "documentType": "SALES_INVOICE"
    }
)
print(f"Document created: {doc['result']['id']}")
```

### Upload an Article Image

```python
with open("product.jpg", "rb") as f:
    data = f.read()

# Upload image to an article
client.upload(
    "article",
    data=data,
    id="art123",
    action="uploadArticleImage",
    filename="product.jpg",  # Content type inferred as image/jpeg
    params={"name": "Main Product Image", "mainImage": True}
)
```

### Override Content Type

When the filename extension doesn't match the actual content, explicitly specify the content type:

```python
client.upload(
    "document",
    data=pdf_bytes,
    action="upload",
    content_type="application/pdf",  # Explicit override
    filename="report.dat",            # Would otherwise be unknown
    params={"entityName": "contract", "entityId": "456", "name": "Report"}
)
```

A warning is logged if the explicit `content_type` differs from what would be inferred from the filename.

## Binary Downloads

Download documents, images, and other binary files using the `download()` method.

### Download a Document

```python
# Download by document ID (defaults to 'download' action)
result = client.download("document", id="doc123")

if "content" in result:
    with open("downloaded.pdf", "wb") as f:
        f.write(result["content"])
    print(f"Content-Type: {result['content_type']}")
```

### Download an Invoice PDF

```python
# Download latest sales invoice PDF
result = client.download(
    "salesInvoice",
    id="inv456",
    action="downloadLatestSalesInvoicePdf"
)

with open("invoice.pdf", "wb") as f:
    f.write(result["content"])
```

### Download an Article Image

```python
result = client.download(
    "article",
    id="art789",
    action="downloadArticleImage",
    params={"articleImageId": "img123", "scaleWidth": 800}
)

with open("product.jpg", "wb") as f:
    f.write(result["content"])
```

## Library Design Patterns

Weclappy follows consistent design patterns to provide a predictable and intuitive API.

### Polymorphic Method Signatures

All entity-related methods use named parameters for clarity and consistency:

| Parameter | Description |
|-----------|-------------|
| `endpoint` | The entity type (e.g., `"article"`, `"salesOrder"`, `"document"`) |
| `id` | Entity ID as a named parameter |
| `action` | Action/method name for special operations |
| `params` | Query parameters as a dict |
| `data` | Request body (JSON for post/put, bytes for upload) |

### URL Construction

URLs are constructed consistently based on the provided parameters:

| Parameters | Resulting URL Pattern |
|------------|----------------------|
| `endpoint`, `id`, `action` | `{endpoint}/id/{id}/{action}` |
| `endpoint`, `id` | `{endpoint}/id/{id}` |
| `endpoint`, `action` | `{endpoint}/{action}` |
| `endpoint` only | `{endpoint}` |

### Method Summary

```python
# CRUD Operations
client.get("article", id="123")                    # GET article/id/123
client.get("article")                              # GET article (list)
client.post("article", data={...})                 # POST article
client.put("article", id="123", data={...})        # PUT article/id/123
client.delete("article", id="123")                 # DELETE article/id/123

# Binary Operations
client.upload("article", id="123", action="uploadArticleImage", data=bytes)
client.download("document", id="456")              # GET document/id/456/download
client.download("salesInvoice", id="789", action="downloadLatestSalesInvoicePdf")

# Custom Methods
client.call_method("salesOrder", "createSalesInvoice", entity_id="123", method="POST", data={...})
```

### Return Types

| Response Type | Return Value |
|---------------|--------------|
| JSON | Parsed dict or list |
| Binary (PDF, images, etc.) | `{"content": bytes, "content_type": str}` |
| Structured | `WeclappResponse` (when `return_weclapp_response=True`) |

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.
