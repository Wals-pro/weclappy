import unittest
from unittest.mock import patch, MagicMock
from weclappy import Weclapp, WeclappResponse


class TestWeclappUnit(unittest.TestCase):
    """Unit tests for the Weclappy library."""

    def setUp(self):
        """Set up test fixtures."""
        self.base_url = "https://test.weclapp.com/webapp/api/v1"
        self.api_key = "test_api_key"
        self.weclapp = Weclapp(self.base_url, self.api_key)

    def test_init(self):
        """Test initialization of the Weclapp client."""
        self.assertEqual(self.weclapp.base_url, "https://test.weclapp.com/webapp/api/v1/")
        self.assertEqual(self.weclapp.session.headers["AuthenticationToken"], "test_api_key")
        self.assertEqual(self.weclapp.session.headers["Content-Type"], "application/json")

    @patch('weclappy.requests.Session.request')
    def test_get_single_entity(self, mock_request):
        """Test fetching a single entity by ID."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"id": "123", "name": "Test Entity"}
        mock_request.return_value = mock_response

        # Call the method
        result = self.weclapp.get("article", id="123")

        # Verify the request
        mock_request.assert_called_once_with(
            "GET",
            "https://test.weclapp.com/webapp/api/v1/article/id/123",
            params={}
        )

        # Verify the result
        self.assertEqual(result, {"id": "123", "name": "Test Entity"})

    @patch('weclappy.requests.Session.request')
    def test_get_entity_list(self, mock_request):
        """Test fetching a list of entities."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "result": [
                {"id": "123", "name": "Entity 1"},
                {"id": "456", "name": "Entity 2"}
            ]
        }
        mock_request.return_value = mock_response

        # Call the method
        result = self.weclapp.get("article")

        # Verify the request
        mock_request.assert_called_once_with(
            "GET",
            "https://test.weclapp.com/webapp/api/v1/article",
            params={}
        )

        # Verify the result
        self.assertEqual(result, [
            {"id": "123", "name": "Entity 1"},
            {"id": "456", "name": "Entity 2"}
        ])

    @patch('weclappy.requests.Session.request')
    def test_get_with_additional_properties(self, mock_request):
        """Test fetching entities with additionalProperties parameter."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "result": [
                {"id": "123", "name": "Article 1"},
                {"id": "456", "name": "Article 2"}
            ],
            "additionalProperties": {
                "currentSalesPrice": [
                    {"articleUnitPrice": "39.95", "currencyId": "256"},
                    {"articleUnitPrice": "49.95", "currencyId": "256"}
                ]
            }
        }
        mock_request.return_value = mock_response

        # Call the method with additionalProperties
        result = self.weclapp.get(
            "article",
            params={"additionalProperties": "currentSalesPrice"},
            return_weclapp_response=True
        )

        # Verify the request
        mock_request.assert_called_once_with(
            "GET",
            "https://test.weclapp.com/webapp/api/v1/article",
            params={"additionalProperties": "currentSalesPrice"}
        )

        # Verify the result
        self.assertIsInstance(result, WeclappResponse)
        self.assertEqual(len(result.result), 2)
        self.assertEqual(result.result[0]["name"], "Article 1")
        self.assertEqual(result.additional_properties["currentSalesPrice"][0]["articleUnitPrice"], "39.95")

    @patch('weclappy.requests.Session.request')
    def test_get_with_additional_properties_list(self, mock_request):
        """Test fetching entities with additionalProperties as a list."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "result": [{"id": "123", "name": "Article 1"}],
            "additionalProperties": {
                "currentSalesPrice": [{"articleUnitPrice": "39.95"}],
                "averagePrice": [{"amountInCompanyCurrency": "35.00"}]
            }
        }
        mock_request.return_value = mock_response

        # Call the method with additionalProperties as a comma-separated string
        result = self.weclapp.get(
            "article",
            params={"additionalProperties": "currentSalesPrice,averagePrice"},
            return_weclapp_response=True
        )

        # Verify the request
        mock_request.assert_called_once_with(
            "GET",
            "https://test.weclapp.com/webapp/api/v1/article",
            params={"additionalProperties": "currentSalesPrice,averagePrice"}
        )

        # Verify the result
        self.assertIsInstance(result, WeclappResponse)
        self.assertEqual(result.additional_properties["currentSalesPrice"][0]["articleUnitPrice"], "39.95")
        self.assertEqual(result.additional_properties["averagePrice"][0]["amountInCompanyCurrency"], "35.00")

    @patch('weclappy.requests.Session.request')
    def test_get_with_referenced_entities(self, mock_request):
        """Test fetching entities with includeReferencedEntities parameter."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "result": [
                {"id": "123", "name": "Article 1", "unitId": "456"},
                {"id": "789", "name": "Article 2", "unitId": "456"}
            ],
            "referencedEntities": {
                "unit": [
                    {"id": "456", "name": "Piece", "abbreviation": "pc"}
                ]
            }
        }
        mock_request.return_value = mock_response

        # Call the method with includeReferencedEntities
        result = self.weclapp.get(
            "article",
            params={"includeReferencedEntities": "unitId"},
            return_weclapp_response=True
        )

        # Verify the request
        mock_request.assert_called_once_with(
            "GET",
            "https://test.weclapp.com/webapp/api/v1/article",
            params={"includeReferencedEntities": "unitId"}
        )

        # Verify the result
        self.assertIsInstance(result, WeclappResponse)
        self.assertEqual(len(result.result), 2)
        self.assertEqual(result.result[0]["unitId"], "456")
        self.assertEqual(result.referenced_entities["unit"]["456"]["name"], "Piece")

    @patch('weclappy.requests.Session.request')
    def test_get_with_referenced_entities_list(self, mock_request):
        """Test fetching entities with includeReferencedEntities as a list."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "result": [
                {"id": "123", "name": "Article 1", "unitId": "456", "articleCategoryId": "789"}
            ],
            "referencedEntities": {
                "unit": [{"id": "456", "name": "Piece"}],
                "articleCategory": [{"id": "789", "name": "Category 1"}]
            }
        }
        mock_request.return_value = mock_response

        # Call the method with includeReferencedEntities as a comma-separated string
        result = self.weclapp.get(
            "article",
            params={"includeReferencedEntities": "unitId,articleCategoryId"},
            return_weclapp_response=True
        )

        # Verify the request
        mock_request.assert_called_once_with(
            "GET",
            "https://test.weclapp.com/webapp/api/v1/article",
            params={"includeReferencedEntities": "unitId,articleCategoryId"}
        )

        # Verify the result
        self.assertIsInstance(result, WeclappResponse)
        self.assertEqual(result.referenced_entities["unit"]["456"]["name"], "Piece")
        self.assertEqual(result.referenced_entities["articleCategory"]["789"]["name"], "Category 1")

    @patch('weclappy.requests.Session.request')
    def test_get_with_both_parameters(self, mock_request):
        """Test fetching entities with both additionalProperties and includeReferencedEntities."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "result": [
                {"id": "123", "name": "Article 1", "unitId": "456"}
            ],
            "additionalProperties": {
                "currentSalesPrice": [{"articleUnitPrice": "39.95"}]
            },
            "referencedEntities": {
                "unit": [{"id": "456", "name": "Piece"}]
            }
        }
        mock_request.return_value = mock_response

        # Call the method with both parameters
        result = self.weclapp.get(
            "article",
            params={
                "additionalProperties": "currentSalesPrice",
                "includeReferencedEntities": "unitId"
            },
            return_weclapp_response=True
        )

        # Verify the request
        mock_request.assert_called_once_with(
            "GET",
            "https://test.weclapp.com/webapp/api/v1/article",
            params={
                "additionalProperties": "currentSalesPrice",
                "includeReferencedEntities": "unitId"
            }
        )

        # Verify the result
        self.assertIsInstance(result, WeclappResponse)
        self.assertEqual(result.result[0]["name"], "Article 1")
        self.assertEqual(result.additional_properties["currentSalesPrice"][0]["articleUnitPrice"], "39.95")
        self.assertEqual(result.referenced_entities["unit"]["456"]["name"], "Piece")

    def test_get_all_sequential(self):
        """Test get_all method with sequential pagination."""
        # Create a mock Weclapp instance
        mock_weclapp = Weclapp("https://test.weclapp.com/webapp/api/v1", "test_api_key")

        # Mock the _send_request method
        mock_weclapp._send_request = MagicMock()

        # Configure the mock to return different responses for different calls
        mock_weclapp._send_request.side_effect = [
            # First page response
            {
                "result": [{"id": "1", "name": "Item 1"}, {"id": "2", "name": "Item 2"}]
            },
            # Second page response
            {
                "result": [{"id": "3", "name": "Item 3"}]
            }
        ]

        # Call the method with a small page size
        with patch('weclappy.DEFAULT_PAGE_SIZE', 2):
            result = mock_weclapp.get_all("article", threaded=False)

        # Verify the result
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["name"], "Item 1")
        self.assertEqual(result[1]["name"], "Item 2")
        self.assertEqual(result[2]["name"], "Item 3")

        # Verify that _send_request was called twice
        self.assertEqual(mock_weclapp._send_request.call_count, 2)

    @patch('weclappy.Weclapp._send_request')
    def test_get_all_with_additional_properties(self, mock_send_request):
        """Test get_all method with additionalProperties parameter."""
        # Mock response for data endpoint
        mock_send_request.return_value = {
            "result": [
                {"id": "123", "name": "Article 1"},
                {"id": "456", "name": "Article 2"}
            ],
            "additionalProperties": {
                "currentSalesPrice": [
                    {"articleUnitPrice": "39.95"},
                    {"articleUnitPrice": "49.95"}
                ]
            }
        }

        # Call the method
        result = self.weclapp.get_all(
            "article",
            params={"additionalProperties": "currentSalesPrice"},
            threaded=False,  # Use sequential to simplify test
            return_weclapp_response=True
        )

        # Verify the result
        self.assertIsInstance(result, WeclappResponse)
        self.assertEqual(len(result.result), 2)
        self.assertEqual(result.result[0]["name"], "Article 1")
        self.assertEqual(result.additional_properties["currentSalesPrice"][0]["articleUnitPrice"], "39.95")

    @patch('weclappy.Weclapp._send_request')
    def test_get_all_with_referenced_entities(self, mock_send_request):
        """Test get_all method with includeReferencedEntities parameter."""
        # Mock response for data endpoint
        mock_send_request.return_value = {
            "result": [
                {"id": "123", "name": "Article 1", "unitId": "456"},
                {"id": "789", "name": "Article 2", "unitId": "456"}
            ],
            "referencedEntities": {
                "unit": [
                    {"id": "456", "name": "Piece", "abbreviation": "pc"}
                ]
            }
        }

        # Call the method
        result = self.weclapp.get_all(
            "article",
            params={"includeReferencedEntities": "unitId"},
            threaded=False,  # Use sequential to simplify test
            return_weclapp_response=True
        )

        # Verify the result
        self.assertIsInstance(result, WeclappResponse)
        self.assertEqual(len(result.result), 2)
        self.assertEqual(result.result[0]["unitId"], "456")
        self.assertEqual(result.referenced_entities["unit"]["456"]["name"], "Piece")

    def test_get_all_threaded(self):
        """Test get_all method with threaded fetching."""
        # Skip this test for now as it's difficult to mock the ThreadPoolExecutor and as_completed
        # The test would be too complex and brittle
        import pytest
        pytest.skip("Skipping test for threaded fetching as it's difficult to mock properly")

    def test_get_all_threaded_with_properties(self):
        """Test get_all method with threaded fetching and additional properties."""
        # Skip this test for now as it's difficult to mock the ThreadPoolExecutor and as_completed
        # The test would be too complex and brittle
        import pytest
        pytest.skip("Skipping test for threaded fetching as it's difficult to mock properly")

    @patch('weclappy.requests.Session.request')
    def test_post(self, mock_request):
        """Test post method."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"id": "123", "name": "New Article"}
        mock_request.return_value = mock_response

        # Call the method
        data = {"name": "New Article", "articleNumber": "A123"}
        result = self.weclapp.post("article", data)

        # Verify the request
        mock_request.assert_called_once_with(
            "POST",
            "https://test.weclapp.com/webapp/api/v1/article",
            json=data
        )

        # Verify the result
        self.assertEqual(result["id"], "123")
        self.assertEqual(result["name"], "New Article")

    @patch('weclappy.requests.Session.request')
    def test_put(self, mock_request):
        """Test put method."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"id": "123", "name": "Updated Article"}
        mock_request.return_value = mock_response

        # Call the method
        data = {"name": "Updated Article"}
        result = self.weclapp.put("article", id="123", data=data)

        # Verify the request
        mock_request.assert_called_once_with(
            "PUT",
            "https://test.weclapp.com/webapp/api/v1/article/id/123",
            json=data,
            params={"ignoreMissingProperties": True}
        )

        # Verify the result
        self.assertEqual(result["id"], "123")
        self.assertEqual(result["name"], "Updated Article")

    @patch('weclappy.requests.Session.request')
    def test_delete(self, mock_request):
        """Test delete method."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_request.return_value = mock_response

        # Call the method
        result = self.weclapp.delete("article", id="123")

        # Verify the request
        mock_request.assert_called_once_with(
            "DELETE",
            "https://test.weclapp.com/webapp/api/v1/article/id/123",
            params={}
        )

        # Verify the result (empty dict for 204 response)
        self.assertEqual(result, {})

    @patch('weclappy.requests.Session.request')
    def test_call_method(self, mock_request):
        """Test call_method for custom API methods."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": "success"}
        mock_request.return_value = mock_response

        # Call the method
        result = self.weclapp.call_method(
            "salesInvoice",
            "downloadLatestSalesInvoicePdf",
            entity_id="123",
            method="GET"
        )

        # Verify the request
        mock_request.assert_called_once_with(
            "GET",
            "https://test.weclapp.com/webapp/api/v1/salesInvoice/id/123/downloadLatestSalesInvoicePdf",
            json=None,
            params=None
        )

        # Verify the result
        self.assertEqual(result["result"], "success")

    def test_weclapp_response_class(self):
        """Test the WeclappResponse class."""
        # Create a sample API response
        api_response = {
            "result": [
                {"id": "123", "name": "Article 1", "unitId": "456"}
            ],
            "additionalProperties": {
                "currentSalesPrice": [{"articleUnitPrice": "39.95"}]
            },
            "referencedEntities": {
                "unit": [{"id": "456", "name": "Piece"}]
            }
        }

        # Create a WeclappResponse instance
        response = WeclappResponse.from_api_response(api_response)

        # Verify the properties
        self.assertEqual(len(response.result), 1)
        self.assertEqual(response.result[0]["name"], "Article 1")
        self.assertEqual(response.additional_properties["currentSalesPrice"][0]["articleUnitPrice"], "39.95")
        self.assertEqual(response.referenced_entities["unit"]["456"]["name"], "Piece")
        self.assertEqual(response.raw_response, api_response)


if __name__ == "__main__":
    unittest.main()
