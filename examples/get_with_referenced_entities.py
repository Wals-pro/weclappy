from weclappy import Weclapp, WeclappAPIError, WeclappResponse
from dotenv import load_dotenv
import logging
import os

# Simple example: Fetch sales invoices with referenced entities
# This demonstrates how to use referencedEntities parameter

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # Fetch sales invoices with referenced entities
    logging.info("Fetching sales invoices with referenced entities...")
    
    # Get sales invoices with referenced entities
    response = weclapp.get_all(
        "salesInvoice",
        limit=5,  # Fetch only 5 invoices
        referenced_entities=["customerId"],  # Include customer data
        return_weclapp_response=True  # Return a WeclappResponse object
    )
    
    logging.info(f"Successfully fetched {len(response.result)} sales invoices")
    
    # Display the invoices with their referenced entities
    if response.result and response.referenced_entities:
        logging.info("\nSales invoices with customer information:")
        for i, invoice in enumerate(response.result, 1):
            invoice_number = invoice.get('invoiceNumber', 'N/A')
            customer_id = invoice.get('customerId')
            
            # Get customer name from referenced entities
            customer_name = "N/A"
            if "Customer" in response.referenced_entities and customer_id in response.referenced_entities["Customer"]:
                customer = response.referenced_entities["Customer"][customer_id]
                customer_name = customer.get('name', 'N/A')
            
            logging.info(f"  {i}. Invoice #{invoice_number}")
            logging.info(f"     Customer: {customer_name}")
    else:
        logging.info("No invoices or referenced entities found")
        
except WeclappAPIError as e:
    logging.error(f"Failed to fetch sales invoices: {e}")
