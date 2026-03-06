from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os
import time

# Simple example: Basic CRUD operations
# This demonstrates how to create, read, update, and delete entities

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])
party_id = None
unique_suffix = str(int(time.time()))
customer_number = f"WEC{unique_suffix}"
initial_email = f"john.doe.{unique_suffix}@example.com"
updated_email = f"john.doe.updated.{unique_suffix}@example.com"

try:
    # 1. CREATE: Create a new party
    logging.info("Creating a new party...")

    new_party = weclapp.post("party", {
        "customerNumber": customer_number,
        "partyType": "PERSON",
        "firstName": "John",
        "lastName": "Doe",
        "email": initial_email
    })

    party_id = new_party.get('id')
    logging.info(f"Created party with ID: {party_id}")

    # 2. READ: Get the party by ID
    logging.info("\nRetrieving the party...")

    party = weclapp.get("party", id=party_id)
    logging.info(f"Retrieved party: {party.get('firstName')} {party.get('lastName')}")

    # 3. UPDATE: Update the party
    logging.info("\nUpdating the party...")

    updated_party = weclapp.put("party", party_id, {
        "firstName": "John",
        "lastName": "Doe Updated",
        "email": updated_email
    })

    logging.info(f"Updated party email: {updated_party.get('email')}")

    # 4. DELETE: Delete the party
    logging.info("\nDeleting the party...")

    weclapp.delete("party", party_id)
    party_id = None
    logging.info("Party deleted successfully")

except WeclappAPIError as e:
    logging.error(f"API Error: {e}")
finally:
    if party_id is not None:
        try:
            logging.info("\nCleaning up the temporary party...")
            weclapp.delete("party", party_id)
            logging.info("Cleanup delete successful")
        except WeclappAPIError as cleanup_error:
            logging.error(f"Cleanup API Error: {cleanup_error}")
