import unittest
from unittest.mock import patch, MagicMock
import requests
from weclappy import Weclapp, WeclappResponse, WeclappAPIError


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

    @patch('weclappy.DEFAULT_PAGE_SIZE', 2)
    @patch('weclappy.Weclapp._send_request')
    def test_get_all_merges_referenced_entities_sequential(self, mock_send_request):
        """Test that get_all properly merges referencedEntities across multiple pages in sequential mode."""
        # Mock responses for 3 pages with different referenced entities
        mock_send_request.side_effect = [
            # Page 1: 2 open items referencing 2 invoices
            {
                "result": [
                    {"id": "1", "salesInvoiceId": "inv1"},
                    {"id": "2", "salesInvoiceId": "inv2"}
                ],
                "referencedEntities": {
                    "salesInvoice": [
                        {"id": "inv1", "invoiceNumber": "INV-001"},
                        {"id": "inv2", "invoiceNumber": "INV-002"}
                    ]
                }
            },
            # Page 2: 2 more open items referencing 2 different invoices
            {
                "result": [
                    {"id": "3", "salesInvoiceId": "inv3"},
                    {"id": "4", "salesInvoiceId": "inv4"}
                ],
                "referencedEntities": {
                    "salesInvoice": [
                        {"id": "inv3", "invoiceNumber": "INV-003"},
                        {"id": "inv4", "invoiceNumber": "INV-004"}
                    ]
                }
            },
            # Page 3: 1 more open item referencing another invoice (last page, incomplete)
            {
                "result": [
                    {"id": "5", "salesInvoiceId": "inv5"}
                ],
                "referencedEntities": {
                    "salesInvoice": [
                        {"id": "inv5", "invoiceNumber": "INV-005"}
                    ]
                }
            }
        ]

        # Call get_all with sequential pagination
        result = self.weclapp.get_all(
            "accountOpenItem",
            params={"includeReferencedEntities": "salesInvoiceId"},
            threaded=False,
            return_weclapp_response=True
        )

        # Verify all items were fetched
        self.assertIsInstance(result, WeclappResponse)
        self.assertEqual(len(result.result), 5)

        # Verify ALL referenced entities from ALL pages are present
        self.assertIsNotNone(result.referenced_entities)
        self.assertIn("salesInvoice", result.referenced_entities)
        
        # Critical: All 5 invoices should be present, not just the last page
        self.assertEqual(len(result.referenced_entities["salesInvoice"]), 5)
        
        # Verify specific invoices from each page
        self.assertIn("inv1", result.referenced_entities["salesInvoice"])
        self.assertIn("inv2", result.referenced_entities["salesInvoice"])
        self.assertIn("inv3", result.referenced_entities["salesInvoice"])
        self.assertIn("inv4", result.referenced_entities["salesInvoice"])
        self.assertIn("inv5", result.referenced_entities["salesInvoice"])
        
        # Verify invoice data
        self.assertEqual(result.referenced_entities["salesInvoice"]["inv1"]["invoiceNumber"], "INV-001")
        self.assertEqual(result.referenced_entities["salesInvoice"]["inv5"]["invoiceNumber"], "INV-005")

    @patch('weclappy.DEFAULT_PAGE_SIZE', 2)
    @patch('weclappy.Weclapp._send_request')
    @patch('weclappy.requests.Session.request')
    def test_get_all_merges_referenced_entities_threaded(self, mock_session_request, mock_send_request):
        """Test that get_all properly merges referencedEntities across multiple pages in threaded mode."""
        # Mock the count endpoint
        count_response = MagicMock()
        count_response.status_code = 200
        count_response.json.return_value = {"result": 5}
        mock_session_request.return_value = count_response

        # Mock responses for 3 pages with different referenced entities
        # Note: In threaded mode, pages may be fetched in any order
        mock_send_request.side_effect = [
            # Page 1
            {
                "result": [
                    {"id": "1", "salesInvoiceId": "inv1"},
                    {"id": "2", "salesInvoiceId": "inv2"}
                ],
                "referencedEntities": {
                    "salesInvoice": [
                        {"id": "inv1", "invoiceNumber": "INV-001"},
                        {"id": "inv2", "invoiceNumber": "INV-002"}
                    ]
                }
            },
            # Page 2
            {
                "result": [
                    {"id": "3", "salesInvoiceId": "inv3"},
                    {"id": "4", "salesInvoiceId": "inv4"}
                ],
                "referencedEntities": {
                    "salesInvoice": [
                        {"id": "inv3", "invoiceNumber": "INV-003"},
                        {"id": "inv4", "invoiceNumber": "INV-004"}
                    ]
                }
            },
            # Page 3
            {
                "result": [
                    {"id": "5", "salesInvoiceId": "inv5"}
                ],
                "referencedEntities": {
                    "salesInvoice": [
                        {"id": "inv5", "invoiceNumber": "INV-005"}
                    ]
                }
            }
        ]

        # Call get_all with threaded pagination
        result = self.weclapp.get_all(
            "accountOpenItem",
            params={"includeReferencedEntities": "salesInvoiceId"},
            threaded=True,
            return_weclapp_response=True
        )

        # Verify all items were fetched
        self.assertIsInstance(result, WeclappResponse)
        self.assertEqual(len(result.result), 5)

        # Verify ALL referenced entities from ALL pages are present
        self.assertIsNotNone(result.referenced_entities)
        self.assertIn("salesInvoice", result.referenced_entities)
        
        # Critical: All 5 invoices should be present, not just the last page
        self.assertEqual(len(result.referenced_entities["salesInvoice"]), 5)
        
        # Verify specific invoices from each page
        self.assertIn("inv1", result.referenced_entities["salesInvoice"])
        self.assertIn("inv2", result.referenced_entities["salesInvoice"])
        self.assertIn("inv3", result.referenced_entities["salesInvoice"])
        self.assertIn("inv4", result.referenced_entities["salesInvoice"])
        self.assertIn("inv5", result.referenced_entities["salesInvoice"])
        
        # Verify invoice data
        self.assertEqual(result.referenced_entities["salesInvoice"]["inv1"]["invoiceNumber"], "INV-001")
        self.assertEqual(result.referenced_entities["salesInvoice"]["inv5"]["invoiceNumber"], "INV-005")

    @patch('weclappy.DEFAULT_PAGE_SIZE', 2)
    @patch('weclappy.Weclapp._send_request')
    def test_get_all_merges_multiple_entity_types(self, mock_send_request):
        """Test that get_all properly merges multiple types of referencedEntities across pages."""
        # Mock responses with multiple entity types
        mock_send_request.side_effect = [
            # Page 1: Full page with 2 results
            {
                "result": [
                    {"id": "1", "salesInvoiceId": "inv1", "customerId": "cust1"},
                    {"id": "2", "salesInvoiceId": "inv2", "customerId": "cust2"}
                ],
                "referencedEntities": {
                    "salesInvoice": [
                        {"id": "inv1", "invoiceNumber": "INV-001"},
                        {"id": "inv2", "invoiceNumber": "INV-002"}
                    ],
                    "customer": [
                        {"id": "cust1", "name": "Customer 1"},
                        {"id": "cust2", "name": "Customer 2"}
                    ]
                }
            },
            # Page 2: Incomplete page with 1 result (signals end of pagination)
            {
                "result": [
                    {"id": "3", "salesInvoiceId": "inv3", "customerId": "cust3"}
                ],
                "referencedEntities": {
                    "salesInvoice": [{"id": "inv3", "invoiceNumber": "INV-003"}],
                    "customer": [{"id": "cust3", "name": "Customer 3"}]
                }
            }
        ]

        # Call get_all
        result = self.weclapp.get_all(
            "accountOpenItem",
            params={"includeReferencedEntities": "salesInvoiceId,customerId"},
            threaded=False,
            return_weclapp_response=True
        )

        # Verify both entity types are properly merged
        self.assertEqual(len(result.referenced_entities["salesInvoice"]), 3)
        self.assertEqual(len(result.referenced_entities["customer"]), 3)
        
        # Verify entities from both pages
        self.assertIn("inv1", result.referenced_entities["salesInvoice"])
        self.assertIn("inv2", result.referenced_entities["salesInvoice"])
        self.assertIn("inv3", result.referenced_entities["salesInvoice"])
        self.assertIn("cust1", result.referenced_entities["customer"])
        self.assertIn("cust2", result.referenced_entities["customer"])
        self.assertIn("cust3", result.referenced_entities["customer"])


    @patch('weclappy.requests.Session.request')
    def test_api_error_includes_response_text(self, mock_request):
        """Test that WeclappAPIError includes raw response text on HTTP errors."""
        # Mock a 400 error response with JSON body
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"error": "Invalid request", "details": "Missing required field: name"}'
        mock_response.json.return_value = {"error": "Invalid request", "details": "Missing required field: name"}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("400 Client Error")
        mock_request.return_value = mock_response

        # Call the method and expect an exception
        with self.assertRaises(WeclappAPIError) as context:
            self.weclapp.get("article")

        # Verify the exception contains the raw response text
        exception = context.exception
        self.assertIn("Invalid request", str(exception))
        self.assertIn("Response body:", str(exception))
        self.assertEqual(exception.response_text, mock_response.text)
        self.assertEqual(exception.status_code, 400)
        self.assertIsNotNone(exception.response)

    @patch('weclappy.requests.Session.request')
    def test_api_error_includes_response_text_non_json(self, mock_request):
        """Test that WeclappAPIError includes raw response text even for non-JSON error responses."""
        # Mock a 500 error response with non-JSON body
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = '<html><body>Internal Server Error</body></html>'
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_request.return_value = mock_response

        # Call the method and expect an exception
        with self.assertRaises(WeclappAPIError) as context:
            self.weclapp.post("article", {"name": "Test"})

        # Verify the exception contains the raw response text
        exception = context.exception
        self.assertIn("Internal Server Error", str(exception))
        self.assertIn("Response body:", str(exception))
        self.assertEqual(exception.response_text, mock_response.text)
        self.assertEqual(exception.status_code, 500)

    @patch('weclappy.requests.Session.request')
    def test_api_error_includes_response_text_on_put(self, mock_request):
        """Test that WeclappAPIError includes raw response text on PUT errors."""
        # Mock a 404 error response
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = '{"error": "Entity not found", "entityId": "nonexistent123"}'
        mock_response.json.return_value = {"error": "Entity not found", "entityId": "nonexistent123"}
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
        mock_request.return_value = mock_response

        # Call the method and expect an exception
        with self.assertRaises(WeclappAPIError) as context:
            self.weclapp.put("article", id="nonexistent123", data={"name": "Updated"})

        # Verify the exception contains the raw response text
        exception = context.exception
        self.assertIn("Entity not found", str(exception))
        self.assertEqual(exception.response_text, mock_response.text)
        self.assertEqual(exception.status_code, 404)

    def test_weclapp_api_error_attributes(self):
        """Test WeclappAPIError exception attributes."""
        # Create a mock response
        mock_response = MagicMock()
        mock_response.text = '{"error": "Test error"}'
        mock_response.status_code = 422
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article"

        # Create exception with response
        exc = WeclappAPIError("Test message", response=mock_response)
        self.assertEqual(str(exc), "Test message")
        self.assertEqual(exc.response, mock_response)
        self.assertEqual(exc.response_text, '{"error": "Test error"}')
        self.assertEqual(exc.status_code, 422)
        self.assertEqual(exc.error, "Test error")

        # Create exception without response
        exc_no_response = WeclappAPIError("Test message without response")
        self.assertIsNone(exc_no_response.response)
        self.assertIsNone(exc_no_response.response_text)
        self.assertIsNone(exc_no_response.status_code)

        # Create exception with explicit response_text
        exc_explicit = WeclappAPIError("Test", response=mock_response, response_text="Custom text")
        self.assertEqual(exc_explicit.response_text, "Custom text")

    def test_weclapp_api_error_structured_fields(self):
        """Test WeclappAPIError parses structured error fields from JSON response."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/salesOrder"
        mock_response.text = '''{
            "error": "Validation failed",
            "detail": "One or more fields have invalid values",
            "title": "Bad Request",
            "type": "VALIDATION_ERROR",
            "validationErrors": [
                {"field": "customerNumber", "message": "Customer number is required"},
                {"field": "orderDate", "message": "Invalid date format"}
            ],
            "messages": [
                {"severity": "ERROR", "message": "Please check all required fields"},
                {"severity": "WARNING", "message": "Some optional data is missing"}
            ]
        }'''

        exc = WeclappAPIError("Validation failed", response=mock_response)

        # Check structured fields
        self.assertEqual(exc.error, "Validation failed")
        self.assertEqual(exc.detail, "One or more fields have invalid values")
        self.assertEqual(exc.title, "Bad Request")
        self.assertEqual(exc.error_type, "VALIDATION_ERROR")
        self.assertEqual(len(exc.validation_errors), 2)
        self.assertEqual(exc.validation_errors[0]["field"], "customerNumber")
        self.assertEqual(len(exc.messages), 2)
        self.assertEqual(exc.messages[0]["severity"], "ERROR")

    def test_weclapp_api_error_is_optimistic_lock(self):
        """Test WeclappAPIError detects optimistic lock errors."""
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article/id/123"
        mock_response.text = '{"detail": "Optimistic lock error", "error": "Version conflict"}'

        exc = WeclappAPIError("Version conflict", response=mock_response)
        self.assertTrue(exc.is_optimistic_lock)

        # Test without optimistic lock
        mock_response2 = MagicMock()
        mock_response2.status_code = 400
        mock_response2.url = "https://test.weclapp.com/webapp/api/v1/article"
        mock_response2.text = '{"error": "Invalid data"}'

        exc2 = WeclappAPIError("Invalid data", response=mock_response2)
        self.assertFalse(exc2.is_optimistic_lock)

    def test_weclapp_api_error_is_not_found(self):
        """Test WeclappAPIError detects 404 errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article/id/123"
        mock_response.text = '{"error": "Entity not found"}'

        exc = WeclappAPIError("Not found", response=mock_response)
        self.assertTrue(exc.is_not_found)
        self.assertFalse(exc.is_rate_limited)

    def test_weclapp_api_error_is_rate_limited(self):
        """Test WeclappAPIError detects rate limit errors."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article"
        mock_response.text = '{"error": "Too many requests"}'

        exc = WeclappAPIError("Rate limited", response=mock_response)
        self.assertTrue(exc.is_rate_limited)
        self.assertFalse(exc.is_not_found)

    def test_weclapp_api_error_is_validation_error(self):
        """Test WeclappAPIError detects validation errors."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/salesOrder"
        mock_response.text = '''{
            "error": "Validation failed",
            "validationErrors": [{"field": "name", "message": "Name is required"}]
        }'''

        exc = WeclappAPIError("Validation failed", response=mock_response)
        self.assertTrue(exc.is_validation_error)

        # Test without validation errors
        mock_response2 = MagicMock()
        mock_response2.status_code = 500
        mock_response2.url = "https://test.weclapp.com/webapp/api/v1/article"
        mock_response2.text = '{"error": "Internal server error"}'

        exc2 = WeclappAPIError("Server error", response=mock_response2)
        self.assertFalse(exc2.is_validation_error)

    def test_weclapp_api_error_get_validation_messages(self):
        """Test WeclappAPIError extracts validation messages."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/salesOrder"
        mock_response.text = '''{
            "validationErrors": [
                {"field": "name", "message": "Name is required"},
                {"field": "date", "message": "Invalid date"}
            ]
        }'''

        exc = WeclappAPIError("Validation failed", response=mock_response)
        messages = exc.get_validation_messages()

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0], "Name is required")
        self.assertEqual(messages[1], "Invalid date")

    def test_weclapp_api_error_get_all_messages(self):
        """Test WeclappAPIError collects all error messages."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/salesOrder"
        mock_response.text = '''{
            "error": "Request failed",
            "detail": "Multiple issues found",
            "validationErrors": [{"message": "Field A is invalid"}],
            "messages": [{"severity": "ERROR", "message": "Check field B"}]
        }'''

        exc = WeclappAPIError("Failed", response=mock_response)
        all_messages = exc.get_all_messages()

        self.assertIn("Request failed", all_messages)
        self.assertIn("Multiple issues found", all_messages)
        self.assertIn("Field A is invalid", all_messages)
        self.assertIn("[ERROR] Check field B", all_messages)

    def test_weclapp_api_error_non_json_response(self):
        """Test WeclappAPIError handles non-JSON responses gracefully."""
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article"
        mock_response.text = '<html><body>Bad Gateway</body></html>'

        exc = WeclappAPIError("Bad Gateway", response=mock_response)

        # Structured fields should be None/empty for non-JSON
        self.assertIsNone(exc.error)
        self.assertIsNone(exc.detail)
        self.assertEqual(exc.validation_errors, [])
        self.assertEqual(exc.messages, [])
        self.assertFalse(exc.is_validation_error)
        self.assertFalse(exc.is_optimistic_lock)


if __name__ == "__main__":
    unittest.main()
