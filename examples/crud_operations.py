from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os

# Simple example: Basic CRUD operations
# This demonstrates how to create, read, update, and delete entities

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # 1. CREATE: Create a new contact
    logging.info("Creating a new contact...")
    
    new_contact = weclapp.post("contact", {
        "partyType": "PERSON",
        "firstName": "John",
        "lastName": "Doe",
        "email": "john.doe@example.com"
    })
    
    contact_id = new_contact.get('id')
    logging.info(f"Created contact with ID: {contact_id}")
    
    # 2. READ: Get the contact by ID
    logging.info("\nRetrieving the contact...")
    
    contact = weclapp.get("contact", id=contact_id)
    logging.info(f"Retrieved contact: {contact.get('firstName')} {contact.get('lastName')}")
    
    # 3. UPDATE: Update the contact
    logging.info("\nUpdating the contact...")
    
    updated_contact = weclapp.put("contact", contact_id, {
        "firstName": "John",
        "lastName": "Doe",
        "email": "john.doe.updated@example.com"
    })
    
    logging.info(f"Updated contact email: {updated_contact.get('email')}")
    
    # 4. DELETE: Delete the contact
    logging.info("\nDeleting the contact...")
    
    weclapp.delete("contact", contact_id)
    logging.info("Contact deleted successfully")
    
except WeclappAPIError as e:
    logging.error(f"API Error: {e}")
