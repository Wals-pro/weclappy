from weclappy import Weclapp, WeclappAPIError, WeclappResponse
from dotenv import load_dotenv
import logging
import os

# This example demonstrates:
# 1. Fetching articles with additionalProperties (stock quantities, prices)
# 2. Fetching articles with referencedEntities (units, categories, etc.)
# 3. Accessing and displaying the structured data from the response

# Load environment variables from .env file
load_dotenv()

# Initialize the logger with a more detailed format
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)

# Initialize the Weclapp client
weclapp = Weclapp(os.environ["WECLAPP_BASE_URL"], os.environ["WECLAPP_API_KEY"])

try:
    # Example 1: Basic fetch of articles
    logging.info("\n=== Example 1: Basic Fetch of Articles ===\n")

    # Fetch a few articles to work with
    articles = weclapp.get_all("article", limit=5)

    if not articles:
        logging.error("No articles found in your weclapp account. Please create at least one article.")
        exit(1)

    logging.info(f"Fetched {len(articles)} articles")
    for article in articles:
        logging.info(f"Article: {article.get('name', 'N/A')} (#{article.get('articleNumber', 'N/A')})")

    # Example 2: Fetch articles with additionalProperties
    logging.info("\n=== Example 2: Fetch Articles with additionalProperties ===\n")

    # Define the additional properties we want to include
    # These are specific to the article endpoint
    additional_props = [
        "totalStockQuantity",
        "pickableStockQuantity",
        "reservedStockQuantity",
        "averagePrice",
        "currentSalesPrice"
    ]

    # Fetch articles with additional properties
    articles_with_props = weclapp.get_all(
        "article",
        limit=5,
        additional_properties=additional_props,
        return_weclapp_response=True
    )

    logging.info(f"Fetched {len(articles_with_props.result)} articles with additional properties")

    # Print the raw response structure for validation
    logging.info("\nRaw Response Structure:")
    if articles_with_props.raw_response:
        logging.info("  Response contains the following keys:")
        for key in articles_with_props.raw_response.keys():
            logging.info(f"  - {key}")

    # Display the additional properties
    if articles_with_props.additional_properties:
        logging.info("\nAdditional Properties:")
        logging.info("  Structure: Dictionary with property names as keys and arrays of values as values")
        for prop_name, prop_values in articles_with_props.additional_properties.items():
            logging.info(f"  {prop_name}: {len(prop_values)} values")

            # Show a sample of the first property value if it exists
            if prop_values and len(prop_values) > 0:
                logging.info(f"  Sample data for {prop_name}:")

                # Handle different property types differently
                if prop_name == "totalStockQuantity" or prop_name == "pickableStockQuantity" or prop_name == "reservedStockQuantity":
                    # These are arrays of warehouse quantities
                    for article_idx, warehouses in enumerate(prop_values[:2]):
                        if warehouses and len(warehouses) > 0:
                            article_id = articles_with_props.result[article_idx]['id']
                            article_name = articles_with_props.result[article_idx]['name']
                            logging.info(f"    Article: {article_name} (ID: {article_id})")
                            for warehouse in warehouses:
                                logging.info(f"      Warehouse ID: {warehouse.get('warehouseId', 'N/A')}")
                                logging.info(f"      Quantity: {warehouse.get('quantity', '0')}")

                elif prop_name == "averagePrice":
                    # These are price values
                    for i, price in enumerate(prop_values[:2]):
                        if i < len(articles_with_props.result):
                            article_name = articles_with_props.result[i]['name']
                            logging.info(f"    Article: {article_name}")
                            logging.info(f"      Average Price: {price.get('amountInCompanyCurrency', 'N/A')}")

                elif prop_name == "currentSalesPrice":
                    # These are price objects with more details
                    for i, price in enumerate(prop_values[:2]):
                        if i < len(articles_with_props.result):
                            article_name = articles_with_props.result[i]['name']
                            logging.info(f"    Article: {article_name}")
                            logging.info(f"      Price: {price.get('articleUnitPrice', 'N/A')}")
                            logging.info(f"      Currency ID: {price.get('currencyId', 'N/A')}")

    # Example 3: Fetch articles with referencedEntities
    logging.info("\n=== Example 3: Fetch Articles with referencedEntities ===\n")

    # Define the referenced entities we want to include
    # These are paths to IDs in the article object that reference other entities
    referenced_entities = [
        "unitId",
        "articleCategoryId",
        "customsTariffNumberId",
        "accountId"
    ]

    # Fetch articles with referenced entities
    articles_with_refs = weclapp.get_all(
        "article",
        limit=5,
        referenced_entities=referenced_entities,
        return_weclapp_response=True
    )

    logging.info(f"Fetched {len(articles_with_refs.result)} articles with referenced entities")

    # Print the raw response structure for validation
    logging.info("\nRaw Response Structure:")
    if articles_with_refs.raw_response:
        logging.info("  Response contains the following keys:")
        for key in articles_with_refs.raw_response.keys():
            logging.info(f"  - {key}")

        # If referencedEntities exists, show its structure
        if 'referencedEntities' in articles_with_refs.raw_response:
            logging.info("\n  Referenced Entities contains the following entity types:")
            for entity_type in articles_with_refs.raw_response['referencedEntities'].keys():
                logging.info(f"  - {entity_type}")

    # Display the referenced entities
    if articles_with_refs.referenced_entities:
        logging.info("\nReferenced Entities:")
        logging.info("  Structure: Dictionary with entity types as keys and dictionaries of entities as values")
        for entity_type, entities in articles_with_refs.referenced_entities.items():
            logging.info(f"  {entity_type}: {len(entities)} entities")

            # Show a sample of the first entity
            if entities:
                entity_id = next(iter(entities.keys()))
                entity = entities[entity_id]
                logging.info(f"  Sample {entity_type} (ID: {entity_id}):")

                # Display entity properties based on type
                if entity_type == "Unit":
                    logging.info(f"    Name: {entity.get('name', 'N/A')}")
                    logging.info(f"    Abbreviation: {entity.get('abbreviation', 'N/A')}")
                elif entity_type == "ArticleCategory":
                    logging.info(f"    Name: {entity.get('name', 'N/A')}")
                    logging.info(f"    Description: {entity.get('description', 'N/A')}")
                else:
                    # For other entity types, show common fields
                    for field in ['name', 'number', 'description']:
                        if field in entity:
                            logging.info(f"    {field.capitalize()}: {entity[field]}")

    # Example 4: Fetch articles with BOTH additionalProperties AND referencedEntities
    logging.info("\n=== Example 4: Fetch Articles with BOTH additionalProperties AND referencedEntities ===\n")

    # Fetch articles with both additional properties and referenced entities
    articles_complete = weclapp.get_all(
        "article",
        limit=5,
        additional_properties=additional_props,
        referenced_entities=referenced_entities,
        return_weclapp_response=True
    )

    logging.info(f"Fetched {len(articles_complete.result)} articles with complete data")

    # Print the raw response structure for validation
    logging.info("\nRaw Response Structure:")
    if articles_complete.raw_response:
        logging.info("  Response contains the following keys:")
        for key in articles_complete.raw_response.keys():
            logging.info(f"  - {key}")

        # Show the structure of both additionalProperties and referencedEntities
        if 'additionalProperties' in articles_complete.raw_response:
            logging.info("\n  Additional Properties contains the following property types:")
            for prop_type in articles_complete.raw_response['additionalProperties'].keys():
                logging.info(f"  - {prop_type}")

        if 'referencedEntities' in articles_complete.raw_response:
            logging.info("\n  Referenced Entities contains the following entity types:")
            for entity_type in articles_complete.raw_response['referencedEntities'].keys():
                logging.info(f"  - {entity_type}")

    # Display a comprehensive view of the first article
    if articles_complete.result:
        first_article = articles_complete.result[0]
        article_id = first_article['id']

        logging.info("\nComprehensive View of First Article:")
        logging.info(f"  Name: {first_article.get('name', 'N/A')}")
        logging.info(f"  Article Number: {first_article.get('articleNumber', 'N/A')}")
        logging.info(f"  Description: {first_article.get('description', 'N/A')}")

        # Show stock information from additionalProperties
        logging.info("\n  Stock Information:")
        for prop_name in ['totalStockQuantity', 'pickableStockQuantity', 'reservedStockQuantity']:
            if prop_name in articles_complete.additional_properties:
                prop_values = articles_complete.additional_properties[prop_name]
                if prop_values and len(prop_values) > 0:
                    for article_idx, warehouses in enumerate(prop_values):
                        if article_idx == 0 and warehouses:  # Only for the first article
                            for warehouse in warehouses:
                                warehouse_id = warehouse.get('warehouseId', 'N/A')
                                quantity = warehouse.get('quantity', '0')
                                logging.info(f"    {prop_name}: {quantity} in warehouse {warehouse_id}")

        # Show price information from additionalProperties
        logging.info("\n  Price Information:")
        if 'averagePrice' in articles_complete.additional_properties:
            prices = articles_complete.additional_properties['averagePrice']
            if prices and len(prices) > 0:
                price = prices[0]  # First article's price
                logging.info(f"    Average Price: {price.get('amountInCompanyCurrency', 'N/A')}")

        if 'currentSalesPrice' in articles_complete.additional_properties:
            prices = articles_complete.additional_properties['currentSalesPrice']
            if prices and len(prices) > 0:
                price = prices[0]  # First article's price
                logging.info(f"    Current Sales Price: {price.get('articleUnitPrice', 'N/A')}")
                logging.info(f"    Currency: {price.get('currencyId', 'N/A')}")

        # Show referenced entities for this article
        logging.info("\n  Referenced Entities:")

        # Unit
        unit_id = first_article.get('unitId')
        if unit_id and 'Unit' in articles_complete.referenced_entities:
            units = articles_complete.referenced_entities['Unit']
            if unit_id in units:
                unit = units[unit_id]
                logging.info(f"    Unit: {unit.get('name', 'N/A')} ({unit.get('abbreviation', 'N/A')})")

        # Category
        category_id = first_article.get('articleCategoryId')
        if category_id and 'ArticleCategory' in articles_complete.referenced_entities:
            categories = articles_complete.referenced_entities['ArticleCategory']
            if category_id in categories:
                category = categories[category_id]
                logging.info(f"    Category: {category.get('name', 'N/A')}")

        # Account
        account_id = first_article.get('accountId')
        if account_id and 'Account' in articles_complete.referenced_entities:
            accounts = articles_complete.referenced_entities['Account']
            if account_id in accounts:
                account = accounts[account_id]
                logging.info(f"    Account: {account.get('name', 'N/A')}")

        # Customs Tariff Number
        tariff_id = first_article.get('customsTariffNumberId')
        if tariff_id and 'CustomsTariffNumber' in articles_complete.referenced_entities:
            tariffs = articles_complete.referenced_entities['CustomsTariffNumber']
            if tariff_id in tariffs:
                tariff = tariffs[tariff_id]
                logging.info(f"    Customs Tariff: {tariff.get('number', 'N/A')} - {tariff.get('description', 'N/A')}")

except WeclappAPIError as e:
    logging.error(f"API Error: {e}")
