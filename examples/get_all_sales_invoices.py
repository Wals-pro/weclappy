from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.DEBUG)

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

# Fetch all sales invoices
try:
    sales_invoices = weclapp.get_all("salesInvoice", threaded=True)
    logging.info(f"Fetched {len(sales_invoices)} sales invoices.")

    for sales_invoice in sales_invoices:
        logging.info(f"Sales Invoice {sales_invoice['id']} - {sales_invoice['invoiceNumber']}")

        invoice_doc = weclapp.call_method("salesInvoice", "downloadLatestSalesInvoicePdf", sales_invoice["id"], method="GET")
        logging.info(f"Downloaded PDF for Sales Invoice {sales_invoice['id']}: {invoice_doc}")
        
except WeclappAPIError as e:
    logging.error(f"Failed to fetch sales invoices: {e}")
