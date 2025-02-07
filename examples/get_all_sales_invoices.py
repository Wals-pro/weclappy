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
except WeclappAPIError as e:
    logging.error(f"Failed to fetch sales invoices: {e}")
