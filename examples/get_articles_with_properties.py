from weclappy import Weclapp, WeclappAPIError, WeclappResponse
from dotenv import load_dotenv
import logging
import os

# Simple example: Fetch articles with additional properties
# This demonstrates how to use additionalProperties parameter

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # Fetch articles with additional properties
    logging.info("Fetching articles with additional properties...")
    
    # Define the additional properties we want to include
    additional_props = [
        "totalStockQuantity",
        "currentSalesPrice"
    ]
    
    # Get articles with additional properties
    response = weclapp.get_all(
        "article",
        limit=10,  # Fetch only 10 articles
        additional_properties=additional_props,
        return_weclapp_response=True  # Return a WeclappResponse object
    )
    
    logging.info(f"Successfully fetched {len(response.result)} articles")
    logging.info(f"Additional properties: {response.additional_properties}")    
    
    # Display the articles with their additional properties
    if response.result and response.additional_properties:
        logging.info("\nArticles with additional properties:")
        for i, article in enumerate(zip(response.result[:5], response.additional_properties.get("totalStockQuantity", [])[:5]), 1):
            article_id = article[0]['id']
            article_name = article[0].get('name', 'N/A')
            article_number = article[0].get('articleNumber', 'N/A')

            logging.info(f"  {i}. Article #{article_number}: {article_name}")

            total_stock = article[1]
            logging.info(f"     Total Stock Quantity: {total_stock}")
    else:
        logging.info("No articles or additional properties found")
        
except WeclappAPIError as e:
    logging.error(f"Failed to fetch articles: {e}")
