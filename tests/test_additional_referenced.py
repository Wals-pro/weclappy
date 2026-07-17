import unittest
from weclappy import Weclapp, WeclappResponse


class TestAdditionalPropertiesFix(unittest.TestCase):
    """Test the fix for additionalProperties handling with multiple pages."""

    def setUp(self):
        """Set up test fixtures."""
        self.base_url = "https://test.weclapp.com/webapp/api/v2"
        self.api_key = "test_api_key"
        self.weclapp = Weclapp(self.base_url, self.api_key)

    def test_fix_for_additional_properties(self):
        """Test that additionalProperties are properly extended across pages."""
        results = []
        all_additional_properties = {}
        all_referenced_entities = {}

        # Page 1 data
        page1_data = {
            "result": [{"id": "1"}, {"id": "2"}],
            "additionalProperties": {
                "totalStockQuantity": [
                    {"value": 10},
                    {"value": 20}
                ]
            }
        }

        # Page 2 data
        page2_data = {
            "result": [{"id": "3"}, {"id": "4"}],
            "additionalProperties": {
                "totalStockQuantity": [
                    {"value": 30},
                    {"value": 40}
                ]
            }
        }

        self.weclapp._merge_page_response(
            page1_data, results, all_additional_properties, all_referenced_entities
        )
        self.weclapp._merge_page_response(
            page2_data, results, all_additional_properties, all_referenced_entities
        )

        # Verify that all values were properly extended
        self.assertEqual(len(all_additional_properties["totalStockQuantity"]), 4)
        self.assertEqual(all_additional_properties["totalStockQuantity"][0]["value"], 10)
        self.assertEqual(all_additional_properties["totalStockQuantity"][2]["value"], 30)

    def test_fix_for_referenced_entities(self):
        """Test that referencedEntities are properly merged across pages."""
        results = []
        all_additional_properties = {}
        all_referenced_entities = {}

        # Page 1 data
        page1_data = {
            "result": [{"id": "1", "unitId": "unit1"}],
            "referencedEntities": {
                "unit": [
                    {"id": "unit1", "name": "Piece"}
                ]
            }
        }

        # Page 2 data
        page2_data = {
            "result": [{"id": "2", "unitId": "unit2"}],
            "referencedEntities": {
                "unit": [
                    {"id": "unit1", "name": "Piece"},  # Duplicate entity
                    {"id": "unit2", "name": "Box"}     # New entity
                ]
            }
        }

        self.weclapp._merge_page_response(
            page1_data, results, all_additional_properties, all_referenced_entities
        )
        self.weclapp._merge_page_response(
            page2_data, results, all_additional_properties, all_referenced_entities
        )
        response = self.weclapp._finalize_collection_response(
            results,
            all_additional_properties,
            all_referenced_entities,
            limit=None,
            return_weclapp_response=True,
        )

        # Verify that entities were properly merged
        self.assertEqual(len(response.referenced_entities["unit"]), 2)
        self.assertIn("unit1", response.referenced_entities["unit"])
        self.assertIn("unit2", response.referenced_entities["unit"])

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
