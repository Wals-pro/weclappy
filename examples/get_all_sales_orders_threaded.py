from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os

# Simple example: Fetch sales orders using threaded mode
# This demonstrates how to use threaded fetching to improve performance

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # Fetch sales orders with threaded mode
    logging.info("Fetching sales orders using threaded mode...")

    sales_orders = weclapp.get_all(
        "salesOrder",
        limit=10000,  # Fetch up to 100 records
        threaded=True,  # Enable threaded fetching
        max_workers=10  # Use 10 threads for parallel fetching
    )

    logging.info(f"Successfully fetched {len(sales_orders)} sales orders")

    # Display the first 5 sales orders
    if sales_orders:
        logging.info("\nFirst 5 sales orders:")
        for i, order in enumerate(sales_orders[:5], 1):
            logging.info(f"  {i}. Order #{order.get('orderNumber', 'N/A')}")
    else:
        logging.info("No sales orders found")

except WeclappAPIError as e:
    logging.error(f"Failed to fetch sales orders: {e}")
