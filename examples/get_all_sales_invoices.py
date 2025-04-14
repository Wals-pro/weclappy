from weclappy import Weclapp, WeclappAPIError, WeclappResponse
from dotenv import load_dotenv
import logging
import os

# This example demonstrates:
# 1. Basic fetching of sales invoices
# 2. Using referencedEntities to include related data
# 3. Downloading a PDF for a sales invoice

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO)

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

# Fetch all sales invoices
try:
    # Example 1: Basic usage (backward compatible)
    logging.info("\n=== Example 1: Basic Usage ===\n")
    sales_invoices = weclapp.get_all("salesInvoice", limit=5, threaded=True)
    logging.info(f"Fetched {len(sales_invoices)} sales invoices.")

    for sales_invoice in sales_invoices:
        logging.info(f"Sales Invoice {sales_invoice['id']} - {sales_invoice['invoiceNumber']}")

    # Example 2: Using referencedEntities
    logging.info("\n=== Example 2: Using referencedEntities ===\n")

    # Get sales invoices with referenced entities
    response = weclapp.get_all(
        "salesInvoice",
        limit=5,
        threaded=True,
        referenced_entities=["taxId", "customerId"],  # List of property paths
        return_weclapp_response=True
    )

    logging.info(f"Fetched {len(response.result)} sales invoices with additional data.")

    # Print the raw response structure for validation
    logging.info("\nRaw Response Structure:")
    if response.raw_response:
        logging.info("  Response contains the following keys:")
        for key in response.raw_response.keys():
            logging.info(f"  - {key}")

        # If referencedEntities exists, show its structure
        if 'referencedEntities' in response.raw_response:
            logging.info("\n  Referenced Entities contains the following entity types:")
            for entity_type in response.raw_response['referencedEntities'].keys():
                logging.info(f"  - {entity_type}")

    # Access the main results
    logging.info("\nSales Invoices:")
    for invoice in response.result:
        logging.info(f"  Sales Invoice {invoice['id']} - {invoice['invoiceNumber']}")
        # Print a few key fields from the invoice for validation
        logging.info(f"  Fields available in invoice: {', '.join(list(invoice.keys())[:5])}...")

    # Note: We're not using additionalProperties in this example

    # Access referenced entities - this is the main focus of this example
    if response.referenced_entities:
        logging.info("\nReferenced Entities:")
        for entity_type, entities in response.referenced_entities.items():
            logging.info(f"  {entity_type}: {len(entities)} entities")

            # Print the structure of the referenced entities dictionary
            logging.info(f"  Structure: Dictionary with entity IDs as keys and entity data as values")
            logging.info(f"  Example key (ID): {next(iter(entities.keys()))}")

            # Show a sample of the first entity if available
            if entities:
                entity_id = next(iter(entities.keys()))
                entity = entities[entity_id]
                logging.info(f"  Sample {entity_type} (ID: {entity_id}):")

                # Print all available keys in this entity
                logging.info(f"    Available fields: {', '.join(list(entity.keys()))}")

                # Display some key properties based on entity type
                if entity_type == "Customer":
                    logging.info(f"    Name: {entity.get('name', 'N/A')}")
                    logging.info(f"    Number: {entity.get('customerNumber', 'N/A')}")
                elif entity_type == "Article":
                    logging.info(f"    Name: {entity.get('name', 'N/A')}")
                    logging.info(f"    Number: {entity.get('articleNumber', 'N/A')}")
                else:
                    # For other entity types, show a few common fields if they exist
                    for field in ['name', 'number', 'description']:
                        if field in entity:
                            logging.info(f"    {field.capitalize()}: {entity[field]}")

            # Show how to access a referenced entity from a result item
            if entity_type == "Customer" and response.result:
                for invoice in response.result[:1]:  # Just the first invoice
                    customer_id = invoice.get('customerId')
                    if customer_id and customer_id in entities:
                        logging.info(f"\n  Example of accessing a Customer from an invoice:")
                        logging.info(f"    Invoice {invoice['invoiceNumber']} has customerId: {customer_id}")
                        customer = entities[customer_id]
                        logging.info(f"    Customer name: {customer.get('name', 'N/A')}")
                        logging.info(f"    This demonstrates how to link the result with its referenced entities")

    # Example 3: Download a PDF for the first invoice
    if response.result:
        logging.info("\n=== Example 3: Downloading PDF ===\n")
        first_invoice = response.result[0]
        invoice_doc = weclapp.call_method(
            "salesInvoice",
            "downloadLatestSalesInvoicePdf",
            first_invoice["id"],
            method="GET"
        )
        logging.info(f"Downloaded PDF for Sales Invoice {first_invoice['id']}")

except WeclappAPIError as e:
    logging.error(f"Failed to fetch sales invoices: {e}")
