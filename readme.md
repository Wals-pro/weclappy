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
- **Additional Properties & Referenced Entities:** Support for weclapp API's additionalProperties and referencedEntities parameters.
- **Structured Response:** Optional WeclappResponse class to handle complex API responses.
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

The library raises `WeclappAPIError` for API-related errors:

```python
from weclappy import Weclapp, WeclappAPIError

client = Weclapp("https://acme.weclapp.com/webapp/api/v1", "your_api_key")

try:
    result = client.get("nonExistentEndpoint")
except WeclappAPIError as e:
    print(f"API Error: {e}")
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.
