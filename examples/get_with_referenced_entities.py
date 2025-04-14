from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os
import requests

# Simple example: Fetch articles with referenced entities
# This demonstrates how to use the includeReferencedEntities parameter

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # Fetch articles with their units as referenced entities
    logging.info("Fetching articles with their units as referenced entities...")

    # First, let's try a direct HTTP request to verify the API behavior
    logging.info("Making a direct HTTP request to the API...")
    direct_url = f"{os.environ['WECLAPP_BASE_URL']}/article"
    direct_params = {"pageSize": 1, "includeReferencedEntities": "unitId"}
    direct_headers = {"AuthenticationToken": os.environ["WECLAPP_API_KEY"]}

    direct_response = requests.get(direct_url, params=direct_params, headers=direct_headers)
    direct_data = direct_response.json()

    logging.info(f"Direct API response status: {direct_response.status_code}")
    if "referencedEntities" in direct_data:
        logging.info("Direct API response includes referencedEntities!")
        logging.info(f"Referenced entity types: {list(direct_data['referencedEntities'].keys())}")
    else:
        logging.info("Direct API response does NOT include referencedEntities")

    # Now try with the weclappy library but with a modified approach
    logging.info("\nNow trying with a modified approach using weclappy...")

    # Enable debug logging to see the actual request
    weclapp_logger = logging.getLogger('weclappy')
    weclapp_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    weclapp_logger.addHandler(handler)

    # Use the _send_request method directly to see the raw response
    url = f"{os.environ['WECLAPP_BASE_URL']}/article"
    params = {"pageSize": 1, "includeReferencedEntities": "unitId"}
    raw_response = weclapp._send_request("GET", url, params=params)

    logging.info("\nRaw response data from direct _send_request:")
    if "referencedEntities" in raw_response:
        logging.info("Direct _send_request response includes referencedEntities!")
        logging.info(f"Referenced entity types: {list(raw_response['referencedEntities'].keys())}")
    else:
        logging.info("Direct _send_request response does NOT include referencedEntities")

    # Now try with the includeReferencedEntities parameter
    logging.info("\nNow trying with the includeReferencedEntities parameter:")

    # Let's try a simpler approach
    # Create a params dictionary with the correct parameter name
    params = {"pageSize": 1, "includeReferencedEntities": "unitId"}

    # Use the get method with the params dictionary
    response = weclapp.get(
        "article",
        params=params,
        return_weclapp_response=True
    )

    # Display the articles with their unit information
    if response.result:
        logging.info(f"Successfully fetched {len(response.result)} articles")

        # Check if referenced entities were returned
        if response.referenced_entities:
            logging.info("Referenced entities were returned by the API")
            logging.info(f"Referenced entity types: {list(response.referenced_entities.keys())}")
        else:
            logging.info("No referenced entities were returned by the API")

        # Display the articles with their unit information (from the article object)
        logging.info("\nArticles with their unit information:")
        for i, article in enumerate(response.result, 1):
            article_name = article.get('name', 'N/A')
            article_number = article.get('articleNumber', 'N/A')
            unit_id = article.get('unitId', 'N/A')
            unit_name = article.get('unitName', 'N/A')

            logging.info(f"  {i}. Article: {article_name} (#{article_number})")
            logging.info(f"     Unit: {unit_name} (ID: {unit_id})")
    else:
        logging.info("No articles found")

except WeclappAPIError as e:
    logging.error(f"Failed to fetch articles: {e}")
except Exception as e:
    logging.error(f"An error occurred: {e}")
