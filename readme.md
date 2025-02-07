# weclappy

The weclapp Python Client.

There is no lightweight, simple weclapp client library available for Python currently. Let's build it together.

## Overview

The goal of this library is to provide a minimal, threaded client that handles pagination effectively when fetching lists from the weclapp API. It is capable of retrieving large volumes of data by parallelizing page requests, significantly reducing wait times. This library is designed to be lean with no unnecessary bloat, allowing you to get started very quickly.

## Features

- **Threaded Pagination:** Fetch multiple pages concurrently for enhanced performance.
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

# Run the example of your choice, in this case, fetch all sales invoices from weclapp.
python get_all_sales_invoices.py
```

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

