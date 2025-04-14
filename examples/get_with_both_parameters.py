from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os

# Simple example: Fetch articles with both additional properties and referenced entities
# This demonstrates how to use both parameters together

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # Fetch articles with both additional properties and referenced entities
    logging.info("Fetching articles with both additional properties and referenced entities...")

    # Enable debug logging to see the actual request
    weclapp_logger = logging.getLogger('weclappy')
    weclapp_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    weclapp_logger.addHandler(handler)

    # Create a params dictionary with both parameters
    params = {
        "pageSize": 1,
        "additionalProperties": "averagePrice,currentSalesPrice",
        "includeReferencedEntities": "unitId"
    }

    # Use the get method with the params dictionary
    response = weclapp.get(
        "article",
        params=params,
        return_weclapp_response=True
    )

    # Display the articles with their additional properties and referenced entities
    if response.result:
        logging.info(f"Successfully fetched {len(response.result)} articles")

        # Check if additional properties were returned
        if response.additional_properties:
            logging.info("Additional properties were returned by the API")
            logging.info(f"Additional property types: {list(response.additional_properties.keys())}")
        else:
            logging.info("No additional properties were returned by the API")

        # Check if referenced entities were returned
        if response.referenced_entities:
            logging.info("Referenced entities were returned by the API")
            logging.info(f"Referenced entity types: {list(response.referenced_entities.keys())}")
        else:
            logging.info("No referenced entities were returned by the API")

        # Display the articles with their additional properties and referenced entities
        logging.info("\nArticles with their additional properties and referenced entities:")
        for i, article in enumerate(response.result, 1):
            article_name = article.get('name', 'N/A')
            article_number = article.get('articleNumber', 'N/A')
            unit_id = article.get('unitId', 'N/A')
            unit_name = article.get('unitName', 'N/A')

            logging.info(f"  {i}. Article: {article_name} (#{article_number})")
            logging.info(f"     Unit: {unit_name} (ID: {unit_id})")

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
                    if sales_price and isinstance(sales_price, dict):
                        price = sales_price.get('articleUnitPrice', 'N/A')
                        logging.info(f"     Current Sales Price: {price}")

            # Display referenced entity details if available
            if response.referenced_entities and 'unit' in response.referenced_entities:
                # Find the unit in the list of units
                unit = None
                for u in response.referenced_entities['unit']:
                    if u.get('id') == unit_id:
                        unit = u
                        break

                if unit:
                    description = unit.get('description', 'N/A')
                    logging.info(f"     Unit Description: {description}")
    else:
        logging.info("No articles found")

except WeclappAPIError as e:
    logging.error(f"Failed to fetch articles: {e}")
except Exception as e:
    logging.error(f"An error occurred: {e}")
