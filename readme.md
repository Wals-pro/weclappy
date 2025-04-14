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
    additional_properties=["customer", "positions"],  # List of property names
    referenced_entities=["customerId", "positions.articleId"],  # List of property paths
    return_weclapp_response=True
)

# Alternatively, you can use comma-separated strings for both parameters:
# sales_order_response = client.get_all(
#     "salesOrder",
#     limit=10,
#     additional_properties="customer,positions",  # Comma-separated string of property names
#     referenced_entities="customerId,positions.articleId",  # Comma-separated string of property paths
#     return_weclapp_response=True
# )

# Access the main result
sales_order = sales_order_response.result
print(f"Sales Order: {sales_order['orderNumber']}")

# Access additional properties if available
if sales_order_response.additional_properties:
    customer_data = sales_order_response.additional_properties.get("customer")
    if customer_data:
        print(f"Customer: {customer_data[0]['name']}")

# Access referenced entities if available
if sales_order_response.referenced_entities:
    for entity_type, entities in sales_order_response.referenced_entities.items():
        print(f"{entity_type}: {len(entities)} entities")
```

## Examples

You can find useful examples in the examples folder. Make sure to create a virtual environment and install the dependencies first and prepare your environment file that holds your weclapp url and api key.

```
cd examples
python3 -m venv venv

# On a Unix-based system
source venv/bin/activate

# On a Windows system
venv\Scripts\activate

pip install -r requirements.txt

# Copy the .env.example file to .env and fill in your weclapp url and api key
```

### Available Examples

1. **Basic Usage with Referenced Entities**
   ```
   python get_all_sales_invoices.py
   ```
   Demonstrates fetching sales invoices with referenced entities and downloading PDFs.

2. **Using additionalProperties and referencedEntities with Articles**
   ```
   python get_with_additional_properties.py
   ```
   Shows how to fetch articles with both additional properties (like currentSalesPrice, aggregateStock, averagePrice) and referenced entities, using the WeclappResponse class to access the structured data.

3. **Complete Example with Articles**
   ```
   python get_articles_with_properties.py
   ```
   Comprehensive example showing how to use both additionalProperties and referencedEntities with the article endpoint, including detailed handling of stock quantities, prices, and related entities.

4. **Threaded Fetching with 25 Threads**
   ```
   python get_all_sales_orders_threaded.py
   ```
   Demonstrates how to fetch all salesOrders using threaded fetching with 25 threads, comparing performance with sequential fetching and showing how to work with the results.

## Testing

The library includes comprehensive tests to verify all functionality:

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run unit tests
python -m pytest tests/test_weclappy_unit.py -v

# Run integration tests (requires API credentials)
python -m pytest tests/test_weclappy_integration.py -v
```

See the [tests/README.md](tests/README.md) file for more details on running tests.

## Changelog

See the [CHANGELOG.md](changelog.md) file for details on all changes in each release.

## Contributing

Contributions are very welcome. Any improvements, bug fixes, or new features are gladly accepted. Let’s build this client together to make working with the weclapp API as efficient as possible.


## License

This project is licensed under the MIT License. Feel free to use it in your commercial projects with no restrictions.

# Get in touch

If you are interested in working with us or want us to implement your integrations, then book a call. You can always book a call with me at
https://wals.pro/termin.

## Support

Feel free to use this library in all your projects for free. If you have a lot of fun and build something great with it, consider buying me a coffee.

## Follow me on:
- [LinkedIn](https://www.linkedin.com/in/markuswals)
- [YouTube](https://www.youtube.com/@wals-pro)

