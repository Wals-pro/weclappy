from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os

# Simple example: Count entities
# This demonstrates how to use the count endpoint

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # Count all articles
    logging.info("Counting all articles...")
    
    # Use the count endpoint
    count_response = weclapp.call_method("article", "count")
    
    # The count endpoint returns an integer
    article_count = count_response.get("count", 0)
    logging.info(f"Total number of articles: {article_count}")
    
    # Count articles with a filter
    logging.info("\nCounting active articles...")
    
    # Use the count endpoint with a filter parameter
    count_response = weclapp.call_method(
        "article", 
        "count", 
        params={"active-eq": "true"}
    )
    
    active_article_count = count_response.get("count", 0)
    logging.info(f"Number of active articles: {active_article_count}")
    
    # Calculate percentage of active articles
    if article_count > 0:
        percentage = (active_article_count / article_count) * 100
        logging.info(f"Percentage of active articles: {percentage:.1f}%")
    
except WeclappAPIError as e:
    logging.error(f"API Error: {e}")
