from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os

# Example: Enhanced Error Handling
# This demonstrates how to use the structured error fields

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

# Example 1: Handle a 404 Not Found error
logging.info("=" * 50)
logging.info("Example 1: Handling a 404 Not Found error")
logging.info("=" * 50)

try:
    # Try to get a non-existent entity
    result = weclapp.get("article", id="nonexistent-id-12345")
except WeclappAPIError as e:
    logging.info(f"Caught WeclappAPIError!")
    logging.info(f"  Status Code: {e.status_code}")
    logging.info(f"  Is Not Found: {e.is_not_found}")
    logging.info(f"  Is Optimistic Lock: {e.is_optimistic_lock}")
    logging.info(f"  Is Rate Limited: {e.is_rate_limited}")
    logging.info(f"  Error: {e.error}")
    logging.info(f"  Detail: {e.detail}")
    logging.info(f"  URL: {e.url}")
    logging.info(f"  Raw Response: {e.response_text[:200] if e.response_text else 'None'}...")

# Example 2: Handle validation errors
logging.info("\n" + "=" * 50)
logging.info("Example 2: Handling validation errors")
logging.info("=" * 50)

try:
    # Try to create an invalid entity
    result = weclapp.post("article", {"articleNumber": ""})
except WeclappAPIError as e:
    logging.info(f"Caught WeclappAPIError!")
    logging.info(f"  Status Code: {e.status_code}")
    logging.info(f"  Is Validation Error: {e.is_validation_error}")
    logging.info(f"  Error: {e.error}")
    logging.info(f"  Detail: {e.detail}")
    
    # Get validation messages
    if e.validation_errors:
        logging.info(f"  Validation Errors:")
        for err in e.get_validation_messages():
            logging.info(f"    - {err}")
    
    # Get all messages
    all_msgs = e.get_all_messages()
    if all_msgs:
        logging.info(f"  All Messages:")
        for msg in all_msgs:
            logging.info(f"    - {msg}")

# Example 3: Programmatic error handling
logging.info("\n" + "=" * 50)
logging.info("Example 3: Programmatic error handling pattern")
logging.info("=" * 50)

def safe_get_article(article_id: str):
    """Example of programmatic error handling."""
    try:
        return weclapp.get("article", id=article_id)
    except WeclappAPIError as e:
        if e.is_not_found:
            logging.info(f"Article {article_id} not found")
            return None
        elif e.is_rate_limited:
            logging.info("Rate limited - should retry with backoff")
            raise
        elif e.is_optimistic_lock:
            logging.info("Version conflict - entity was modified")
            raise
        elif e.is_validation_error:
            logging.info(f"Validation errors: {e.get_validation_messages()}")
            raise
        else:
            logging.info(f"Unexpected error: {e}")
            raise

# Test the programmatic pattern
result = safe_get_article("fake-id-999")
logging.info(f"Result: {result}")

logging.info("\n" + "=" * 50)
logging.info("Error handling examples completed!")
logging.info("=" * 50)
