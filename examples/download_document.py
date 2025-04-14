from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os

# Simple example: Download a document
# This demonstrates how to download a PDF document from weclapp

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # First, get a sales invoice to use for the example
    logging.info("Fetching a sales invoice...")
    
    sales_invoices = weclapp.get_all("salesInvoice", limit=1)
    
    if not sales_invoices:
        logging.error("No sales invoices found in your weclapp account.")
        exit(1)
    
    # Get the ID of the first invoice
    invoice_id = sales_invoices[0]['id']
    invoice_number = sales_invoices[0]['invoiceNumber']
    logging.info(f"Using invoice #{invoice_number} (ID: {invoice_id})")
    
    # Download the PDF for the invoice
    logging.info("\nDownloading the invoice PDF...")
    
    invoice_pdf = weclapp.call_method(
        "salesInvoice",
        "downloadLatestSalesInvoicePdf",
        invoice_id,
        method="GET"
    )
    
    # Save the PDF to a file
    if "content" in invoice_pdf:
        filename = f"invoice_{invoice_number}.pdf"
        with open(filename, "wb") as f:
            f.write(invoice_pdf["content"])
        logging.info(f"PDF saved as {filename}")
    else:
        logging.error("Failed to download PDF")
    
except WeclappAPIError as e:
    logging.error(f"API Error: {e}")
