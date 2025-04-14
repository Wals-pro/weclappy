from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os

# Simple example: Fetch articles with additional properties
# This demonstrates how to use the additionalProperties parameter

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # Fetch articles with additional properties
    logging.info("Fetching articles with additional properties...")

    # Enable debug logging to see the actual request
    weclapp_logger = logging.getLogger('weclappy')
    weclapp_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    weclapp_logger.addHandler(handler)

    # Create a params dictionary with the additionalProperties parameter
    params = {
        "pageSize": 1,
        "additionalProperties": "averagePrice,currentSalesPrice,totalStockQuantity"
    }

    # Use the get method with the params dictionary
    response = weclapp.get(
        "article",
        params=params,
        return_weclapp_response=True
    )

    # Display the articles with their additional properties
    if response.result:
        logging.info(f"Successfully fetched {len(response.result)} articles")

        # Check if additional properties were returned
        if response.additional_properties:
            logging.info("Additional properties were returned by the API")
            logging.info(f"Additional property types: {list(response.additional_properties.keys())}")
        else:
            logging.info("No additional properties were returned by the API")

        # Display the articles with their additional properties
        logging.info("\nArticles with their additional properties:")
        for i, article in enumerate(response.result, 1):
            article_name = article.get('name', 'N/A')
            article_number = article.get('articleNumber', 'N/A')

            logging.info(f"  {i}. Article: {article_name} (#{article_number})")

            # Display additional properties if available
            if response.additional_properties:
                # Average price
                if 'averagePrice' in response.additional_properties:
                    avg_price = response.additional_properties['averagePrice'][i-1]
                    if avg_price:
                        price = avg_price.get('amountInCompanyCurrency', 'N/A')
                        logging.info(f"     Average Price: {price}")

                # Current sales price
                if 'currentSalesPrice' in response.additional_properties:
                    sales_price = response.additional_properties['currentSalesPrice'][i-1]
                    if sales_price:
                        price = sales_price.get('articleUnitPrice', 'N/A')
                        logging.info(f"     Current Sales Price: {price}")

                # Total stock quantity
                if 'totalStockQuantity' in response.additional_properties:
                    stock_list = response.additional_properties['totalStockQuantity'][i-1]
                    if stock_list and isinstance(stock_list, list):
                        total_quantity = sum(float(item.get('quantity', 0)) for item in stock_list if isinstance(item, dict))
                        logging.info(f"     Total Stock Quantity: {total_quantity}")
    else:
        logging.info("No articles found")

except WeclappAPIError as e:
    logging.error(f"Failed to fetch articles: {e}")
except Exception as e:
    logging.error(f"An error occurred: {e}")
