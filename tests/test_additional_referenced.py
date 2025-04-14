import unittest
from weclappy import Weclapp, WeclappResponse


class TestAdditionalPropertiesFix(unittest.TestCase):
    """Test the fix for additionalProperties handling with multiple pages."""

    def setUp(self):
        """Set up test fixtures."""
        self.base_url = "https://test.weclapp.com/webapp/api/v1"
        self.api_key = "test_api_key"
        self.weclapp = Weclapp(self.base_url, self.api_key)

    def test_fix_for_additional_properties(self):
        """Test that additionalProperties are properly extended across pages."""
        # Create a sample response with additionalProperties
        all_additional_properties = {}

        # Page 1 data
        page1_data = {
            "additionalProperties": {
                "totalStockQuantity": [
                    {"value": 10},
                    {"value": 20}
                ]
            }
        }

        # Page 2 data
        page2_data = {
            "additionalProperties": {
                "totalStockQuantity": [
                    {"value": 30},
                    {"value": 40}
                ]
            }
        }

        # Simulate processing page 1
        if 'additionalProperties' in page1_data and page1_data['additionalProperties']:
            for prop_name, prop_values in page1_data['additionalProperties'].items():
                if prop_name not in all_additional_properties:
                    all_additional_properties[prop_name] = []
                all_additional_properties[prop_name].extend(prop_values)

        # Simulate processing page 2
        if 'additionalProperties' in page2_data and page2_data['additionalProperties']:
            for prop_name, prop_values in page2_data['additionalProperties'].items():
                if prop_name not in all_additional_properties:
                    all_additional_properties[prop_name] = []
                all_additional_properties[prop_name].extend(prop_values)

        # Verify that all values were properly extended
        self.assertEqual(len(all_additional_properties["totalStockQuantity"]), 4)
        self.assertEqual(all_additional_properties["totalStockQuantity"][0]["value"], 10)
        self.assertEqual(all_additional_properties["totalStockQuantity"][2]["value"], 30)

    def test_fix_for_referenced_entities(self):
        """Test that referencedEntities are properly merged across pages."""
        # Create a sample response with referencedEntities
        all_referenced_entities = {}

        # Page 1 data
        page1_data = {
            "referencedEntities": {
                "unit": [
                    {"id": "unit1", "name": "Piece"}
                ]
            }
        }

        # Page 2 data
        page2_data = {
            "referencedEntities": {
                "unit": [
                    {"id": "unit1", "name": "Piece"},  # Duplicate entity
                    {"id": "unit2", "name": "Box"}     # New entity
                ]
            }
        }

        # Process referenced entities from page 1
        raw_referenced_entities = page1_data.get('referencedEntities')
        if raw_referenced_entities:
            for entity_type, entities_list in raw_referenced_entities.items():
                if entity_type not in all_referenced_entities:
                    all_referenced_entities[entity_type] = {}
                for entity in entities_list:
                    if 'id' in entity:
                        all_referenced_entities[entity_type][entity['id']] = entity

        # Process referenced entities from page 2
        raw_referenced_entities = page2_data.get('referencedEntities')
        if raw_referenced_entities:
            for entity_type, entities_list in raw_referenced_entities.items():
                if entity_type not in all_referenced_entities:
                    all_referenced_entities[entity_type] = {}
                for entity in entities_list:
                    if 'id' in entity:
                        all_referenced_entities[entity_type][entity['id']] = entity

        # Verify that entities were properly merged
        self.assertEqual(len(all_referenced_entities["unit"]), 2)
        self.assertTrue("unit1" in all_referenced_entities["unit"])
        self.assertTrue("unit2" in all_referenced_entities["unit"])

    def test_integration_with_weclapp_response(self):
        """Test integration with WeclappResponse class."""
        # Create a sample API response with both additionalProperties and referencedEntities
        api_response = {
            "result": [
                {"id": "1", "name": "Article 1"},
                {"id": "2", "name": "Article 2"}
            ],
            "additionalProperties": {
                "totalStockQuantity": [
                    {"value": 10},
                    {"value": 20}
                ],
                "currentSalesPrice": [
                    {"articleUnitPrice": "39.95"},
                    {"articleUnitPrice": "49.95"}
                ]
            },
            "referencedEntities": {
                "unit": [
                    {"id": "unit1", "name": "Piece"},
                    {"id": "unit2", "name": "Box"}
                ]
            }
        }

        # Create a WeclappResponse instance
        response = WeclappResponse.from_api_response(api_response)

        # Verify the properties
        self.assertEqual(len(response.result), 2)
        self.assertEqual(response.result[0]["name"], "Article 1")
        self.assertEqual(len(response.additional_properties["totalStockQuantity"]), 2)
        self.assertEqual(response.additional_properties["totalStockQuantity"][0]["value"], 10)
        self.assertEqual(len(response.referenced_entities["unit"]), 2)
        self.assertEqual(response.referenced_entities["unit"]["unit1"]["name"], "Piece")


if __name__ == "__main__":
    unittest.main()
