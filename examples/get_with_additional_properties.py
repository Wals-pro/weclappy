from weclappy import Weclapp, WeclappAPIError
from dotenv import load_dotenv
import logging
import os
import sys

# Load environment variables from .env file
load_dotenv()

# Initialize the logger
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # First, let's get a list of articles to use for our examples
    logging.info("Fetching a list of articles to use in examples...")
    articles = weclapp.get_all("article", limit=5)

    if not articles:
        logging.error("No articles found in your weclapp account. Please create at least one article.")
        sys.exit(1)

    # Use the first article for our examples
    sample_article_id = articles[0]['id']
    logging.info(f"Using article ID: {sample_article_id}\n")

    # Example 1: Get a single entity with additionalProperties and referencedEntities
    logging.info("\n=== Example 1: Get a single entity with additionalProperties and referencedEntities ===\n")

    # Get an article by ID
    # Note: additionalProperties and referencedEntities are not available when fetching by ID
    article = weclapp.get(
        "article",
        id=sample_article_id
    )

    # Print the article
    logging.info(f"Article: {article.get('articleNumber', 'N/A')} - {article.get('name', 'N/A')}")

    # Note: When fetching by ID, additionalProperties and referencedEntities are not available
    # We'll demonstrate these in the next examples

    # Example 2: Get all entities with additionalProperties and referencedEntities
    logging.info("\n=== Example 2: Get all entities with additionalProperties and referencedEntities ===\n")

    # Get all articles with additional properties, limited to 5 records
    # Example 1: Using lists for both parameters
    all_response = weclapp.get_all(
        "article",
        limit=5,
        additional_properties=["currentSalesPrice", "aggregateStock", "averagePrice"],  # List of property names
        referenced_entities=["unitId", "articleCategoryId"],  # List of property paths
        return_weclapp_response=True
    )

    # Example 2 (commented): Using strings for both parameters
    # all_response = weclapp.get_all(
    #     "article",
    #     limit=5,
    #     additional_properties="currentSalesPrice,aggregateStock,averagePrice",  # Comma-separated string of property names
    #     referenced_entities="unitId,articleCategoryId",  # Comma-separated string of property paths
    #     return_weclapp_response=True
    # )

    logging.info(f"Retrieved {len(all_response.result)} articles")

    # Show sample of the results
    if all_response.result:
        logging.info("\nSample of retrieved articles:")
        for i, article in enumerate(all_response.result[:3], 1):
            logging.info(f"  {i}. Article {article.get('articleNumber', 'N/A')} - {article.get('name', 'N/A')}")

    # Access additional properties from all records
    if all_response.additional_properties:
        logging.info("\nAdditional Properties:")
        for prop_name, prop_values in all_response.additional_properties.items():
            logging.info(f"  {prop_name}: {len(prop_values)} values")

            # Show a sample of the first property value if it exists
            if prop_values and isinstance(prop_values, list) and len(prop_values) > 0:
                sample = prop_values[0]
                if isinstance(sample, dict):
                    sample_keys = {k: sample.get(k) for k in ['id', 'name', 'number'] if k in sample}
                    if sample_keys:
                        logging.info(f"    Sample: {sample_keys}")
    else:
        logging.info("No additional properties returned")

    # Access referenced entities from all records
    if all_response.referenced_entities:
        logging.info("\nReferenced Entities:")
        for entity_type, entities in all_response.referenced_entities.items():
            logging.info(f"  {entity_type}: {len(entities)} entities")
    else:
        logging.info("No referenced entities returned")

    # Example 3: Using the raw response data
    logging.info("\n=== Example 3: Accessing the raw response data ===\n")

    if all_response.raw_response:
        logging.info("Raw response contains the following keys:")
        for key in all_response.raw_response.keys():
            logging.info(f"  - {key}")

except WeclappAPIError as e:
    logging.error(f"API Error: {e}")
