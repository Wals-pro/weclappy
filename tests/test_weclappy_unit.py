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
        """Single-entity GET routes via id-eq on the list endpoint."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "result": [{"id": "123", "name": "Test Entity"}]
        }
        mock_request.return_value = mock_response

        result = self.weclapp.get("article", id="123")

        mock_request.assert_called_once_with(
            "GET",
            "https://test.weclapp.com/webapp/api/v1/article",
            params={"id-eq": "123", "pageSize": 1},
            timeout=120,
        )

        self.assertEqual(result["id"], "123")
        self.assertEqual(result.name, "Test Entity")

    @patch('weclappy.requests.Session.request')
    def test_get_single_entity_not_found_raises_404(self, mock_request):
        """Empty result on id-eq raises a synthetic 404 to preserve the contract."""
        from weclappy import WeclappAPIError

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": []}
        mock_request.return_value = mock_response

        with self.assertRaises(WeclappAPIError) as ctx:
            self.weclapp.get("article", id="missing")

        self.assertTrue(ctx.exception.is_not_found)
        self.assertEqual(ctx.exception.status_code, 404)

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
            params={},
            timeout=120,
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
            params={"additionalProperties": "currentSalesPrice"},
            timeout=120,
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
            params={"additionalProperties": "currentSalesPrice,averagePrice"},
            timeout=120,
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
            params={"includeReferencedEntities": "unitId"},
            timeout=120,
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
            params={"includeReferencedEntities": "unitId,articleCategoryId"},
            timeout=120,
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
                "includeReferencedEntities": "unitId",
            },
            timeout=120,
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
            json=data,
            timeout=120,
        )

        # Verify the result
        self.assertEqual(result["id"], "123")
        self.assertEqual(result["name"], "New Article")

    @patch('weclappy.requests.Session.request')
    def test_post_with_params(self, mock_request):
        """Test post method with query params."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"id": "123", "name": "Draft Quotation"}
        mock_request.return_value = mock_response

        # Call the method
        data = {"name": "Draft Quotation"}
        result = self.weclapp.post("quotation", data, params={"dryRun": True})

        # Verify the request
        mock_request.assert_called_once_with(
            "POST",
            "https://test.weclapp.com/webapp/api/v1/quotation",
            json=data,
            params={"dryRun": True},
            timeout=120,
        )

        # Verify the result
        self.assertEqual(result["id"], "123")
        self.assertEqual(result["name"], "Draft Quotation")

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
            params={"ignoreMissingProperties": True},
            timeout=120,
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
            params={},
            timeout=120,
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
            params=None,
            timeout=120,
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


class TestInferContentType(unittest.TestCase):
    """Unit tests for the infer_content_type helper function."""

    def test_infer_pdf(self):
        """Test PDF content type inference."""
        from weclappy import infer_content_type
        self.assertEqual(infer_content_type("document.pdf"), "application/pdf")
        self.assertEqual(infer_content_type("DOCUMENT.PDF"), "application/pdf")

    def test_infer_images(self):
        """Test image content type inference."""
        from weclappy import infer_content_type
        self.assertEqual(infer_content_type("photo.jpg"), "image/jpeg")
        self.assertEqual(infer_content_type("photo.jpeg"), "image/jpeg")
        self.assertEqual(infer_content_type("image.png"), "image/png")
        self.assertEqual(infer_content_type("animation.gif"), "image/gif")
        self.assertEqual(infer_content_type("modern.webp"), "image/webp")

    def test_infer_office_documents(self):
        """Test Office document content type inference."""
        from weclappy import infer_content_type
        self.assertEqual(infer_content_type("doc.docx"),
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertEqual(infer_content_type("sheet.xlsx"),
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_infer_unknown_extension(self):
        """Test that unknown extensions return None."""
        from weclappy import infer_content_type
        self.assertIsNone(infer_content_type("file.unknown"))
        self.assertIsNone(infer_content_type("file.xyz123"))

    def test_infer_no_extension(self):
        """Test files without extension."""
        from weclappy import infer_content_type
        self.assertIsNone(infer_content_type("filename"))
        self.assertIsNone(infer_content_type(""))
        self.assertIsNone(infer_content_type(None))


class TestUploadMethod(unittest.TestCase):
    """Unit tests for the Weclapp.upload method."""

    def setUp(self):
        """Set up test fixtures."""
        self.base_url = "https://test.weclapp.com/webapp/api/v1"
        self.api_key = "test_api_key"
        self.weclapp = Weclapp(self.base_url, self.api_key)

    @patch('weclappy.requests.Session.request')
    def test_upload_document_with_inferred_content_type(self, mock_request):
        """Test uploading a document with content type inferred from filename."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = b'{"result": {"id": "doc123"}}'
        mock_response.json.return_value = {"result": {"id": "doc123"}}
        mock_request.return_value = mock_response

        data = b"PDF content here"
        result = self.weclapp.upload(
            "document",
            data=data,
            action="upload",
            filename="invoice.pdf",
            params={"entityName": "salesOrder", "entityId": "123", "name": "Invoice"}
        )

        # Verify the request
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        self.assertEqual(call_args[0][0], "POST")
        self.assertEqual(call_args[0][1], "https://test.weclapp.com/webapp/api/v1/document/upload")
        self.assertEqual(call_args[1]["data"], data)
        self.assertEqual(call_args[1]["headers"]["Content-Type"], "application/pdf")
        self.assertEqual(call_args[1]["params"]["entityName"], "salesOrder")

    @patch('weclappy.requests.Session.request')
    def test_upload_article_image_with_id(self, mock_request):
        """Test uploading an article image with entity ID."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.content = b'{"result": {"success": true}}'
        mock_response.json.return_value = {"result": {"success": True}}
        mock_request.return_value = mock_response

        data = b"JPEG image data"
        result = self.weclapp.upload(
            "article",
            data=data,
            id="art456",
            action="uploadArticleImage",
            filename="product.jpg",
            params={"name": "Main Image", "mainImage": True}
        )

        # Verify the URL construction
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        self.assertEqual(call_args[0][1], "https://test.weclapp.com/webapp/api/v1/article/id/art456/uploadArticleImage")
        self.assertEqual(call_args[1]["headers"]["Content-Type"], "image/jpeg")

    @patch('weclappy.requests.Session.request')
    def test_upload_with_explicit_content_type_override(self, mock_request):
        """Test that explicit content_type overrides inferred type."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": {"id": "doc123"}}
        mock_request.return_value = mock_response

        data = b"Some data"
        result = self.weclapp.upload(
            "document",
            data=data,
            action="upload",
            content_type="application/pdf",
            filename="file.unknown",
            params={"entityName": "contract", "entityId": "789", "name": "Contract"}
        )

        # Verify explicit content type is used
        call_args = mock_request.call_args
        self.assertEqual(call_args[1]["headers"]["Content-Type"], "application/pdf")

    @patch('weclappy.requests.Session.request')
    def test_upload_fallback_to_octet_stream(self, mock_request):
        """Test fallback to application/octet-stream when no type can be determined."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": {"id": "doc123"}}
        mock_request.return_value = mock_response

        data = b"Binary data"
        result = self.weclapp.upload(
            "document",
            data=data,
            action="upload",
            params={"entityName": "salesOrder", "entityId": "123", "name": "Data"}
        )

        # Verify fallback content type
        call_args = mock_request.call_args
        self.assertEqual(call_args[1]["headers"]["Content-Type"], "application/octet-stream")

    @patch('weclappy.logger')
    @patch('weclappy.requests.Session.request')
    def test_upload_logs_warning_on_content_type_mismatch(self, mock_request, mock_logger):
        """Test that a warning is logged when content_type doesn't match filename."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": {"id": "doc123"}}
        mock_request.return_value = mock_response

        data = b"Some data"
        self.weclapp.upload(
            "document",
            data=data,
            action="upload",
            content_type="application/pdf",
            filename="image.png",
            params={"entityName": "salesOrder", "entityId": "123", "name": "File"}
        )

        # Verify warning was logged
        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        self.assertIn("mismatch", warning_msg.lower())
        self.assertIn("application/pdf", warning_msg)
        self.assertIn("image/png", warning_msg)


class TestDownloadMethod(unittest.TestCase):
    """Unit tests for the Weclapp.download method."""

    def setUp(self):
        """Set up test fixtures."""
        self.base_url = "https://test.weclapp.com/webapp/api/v1"
        self.api_key = "test_api_key"
        self.weclapp = Weclapp(self.base_url, self.api_key)

    @patch('weclappy.requests.Session.request')
    def test_download_document_by_id(self, mock_request):
        """Test downloading a document by ID (default action is 'download')."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.content = b"PDF content"
        mock_request.return_value = mock_response

        result = self.weclapp.download("document", id="doc123")

        # Verify the URL construction
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        self.assertEqual(call_args[0][1], "https://test.weclapp.com/webapp/api/v1/document/id/doc123/download")

        # Verify binary response
        self.assertEqual(result["content"], b"PDF content")
        self.assertEqual(result["content_type"], "application/pdf")

    @patch('weclappy.requests.Session.request')
    def test_download_with_id_and_action(self, mock_request):
        """Test downloading with both id and custom action."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.content = b"Invoice PDF"
        mock_request.return_value = mock_response

        result = self.weclapp.download(
            "salesInvoice",
            id="inv123",
            action="downloadLatestSalesInvoicePdf"
        )

        # Verify the URL construction
        call_args = mock_request.call_args
        self.assertEqual(
            call_args[0][1],
            "https://test.weclapp.com/webapp/api/v1/salesInvoice/id/inv123/downloadLatestSalesInvoicePdf"
        )

    @patch('weclappy.requests.Session.request')
    def test_download_article_image(self, mock_request):
        """Test downloading an article image."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.content = b"JPEG image data"
        mock_request.return_value = mock_response

        result = self.weclapp.download(
            "article",
            id="art456",
            action="downloadArticleImage",
            params={"articleImageId": "img789"}
        )

        # Verify binary response for image
        self.assertEqual(result["content"], b"JPEG image data")
        self.assertIn("image/jpeg", result["content_type"])

    @patch('weclappy.requests.Session.request')
    def test_download_with_action_only(self, mock_request):
        """Test download with action but no id."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": "some data"}
        mock_request.return_value = mock_response

        result = self.weclapp.download("someEndpoint", action="someAction")

        call_args = mock_request.call_args
        self.assertEqual(call_args[0][1], "https://test.weclapp.com/webapp/api/v1/someEndpoint/someAction")


class TestRequestTimingLogging(unittest.TestCase):
    """Tests for HTTP request timing logging."""

    def setUp(self):
        self.base_url = "https://test.weclapp.com/webapp/api/v1"
        self.api_key = "test_api_key"
        self.weclapp = Weclapp(self.base_url, self.api_key)

    @patch('weclappy.time.monotonic')
    @patch('weclappy.logger')
    @patch('weclappy.requests.Session.request')
    def test_normal_request_logs_info_with_api_prefix(self, mock_request, mock_logger, mock_monotonic):
        """Normal request logs at INFO with [API] prefix and correct format."""
        mock_monotonic.side_effect = [0.0, 0.342]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "result": [{"id": "123", "name": "Test"}]
        }
        mock_request.return_value = mock_response

        self.weclapp.get("salesOrder", id="123")

        mock_logger.info.assert_any_call(
            "[API] Weclapp GET /webapp/api/v1/salesOrder -> 200 (342ms)"
        )

    @patch('weclappy.time.monotonic')
    @patch('weclappy.logger')
    @patch('weclappy.requests.Session.request')
    def test_slow_request_logs_warning_with_api_slow_prefix(self, mock_request, mock_logger, mock_monotonic):
        """Slow request (>= threshold) logs at WARNING with [API_SLOW] prefix."""
        mock_monotonic.side_effect = [0.0, 3.421]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": []}
        mock_request.return_value = mock_response

        self.weclapp.get("shipment")

        mock_logger.warning.assert_any_call(
            "[API_SLOW] Weclapp GET /webapp/api/v1/shipment -> 200 (3421ms)"
        )

    @patch('weclappy.time.monotonic')
    @patch('weclappy.logger')
    @patch('weclappy.requests.Session.request')
    def test_error_request_logs_warning_with_error_status(self, mock_request, mock_logger, mock_monotonic):
        """Error request logs at WARNING with ERROR status and exception info."""
        mock_monotonic.side_effect = [0.0, 5.123]
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection refused")

        with self.assertRaises(WeclappAPIError):
            self.weclapp.put("salesOrder", id="12345", data={"name": "Test"})

        mock_logger.warning.assert_any_call(
            "[API] Weclapp PUT /webapp/api/v1/salesOrder/id/12345 -> ERROR (5123ms) "
            "ConnectionError: Connection refused"
        )

    @patch('weclappy.time.monotonic')
    @patch('weclappy.logger')
    @patch('weclappy.requests.Session.request')
    def test_count_endpoint_in_threaded_get_all_is_logged(self, mock_request, mock_logger, mock_monotonic):
        """The count endpoint in threaded get_all is also timed and logged."""
        mock_monotonic.side_effect = [0.0, 0.156, 0.2, 0.5]

        count_response = MagicMock()
        count_response.status_code = 200
        count_response.json.return_value = {"result": 1}

        page_response = MagicMock()
        page_response.status_code = 200
        page_response.headers = {"Content-Type": "application/json"}
        page_response.json.return_value = {"result": [{"id": "1"}]}

        mock_request.side_effect = [count_response, page_response]

        self.weclapp.get_all("salesOrder", threaded=True)

        mock_logger.info.assert_any_call(
            "[API] Weclapp GET /webapp/api/v1/salesOrder/count -> 200 (156ms)"
        )

    def test_default_slow_threshold_ms(self):
        """Default slow_threshold_ms is 2000."""
        self.assertEqual(self.weclapp.slow_threshold_ms, 2000)

    def test_custom_slow_threshold_ms_in_constructor(self):
        """Custom slow_threshold_ms in constructor is respected."""
        weclapp = Weclapp(self.base_url, self.api_key, slow_threshold_ms=500)
        self.assertEqual(weclapp.slow_threshold_ms, 500)

    @patch('weclappy.time.monotonic')
    @patch('weclappy.logger')
    @patch('weclappy.requests.Session.request')
    def test_custom_slow_threshold_triggers_warning(self, mock_request, mock_logger, mock_monotonic):
        """Custom slow threshold triggers WARNING at the configured value."""
        weclapp = Weclapp(self.base_url, self.api_key, slow_threshold_ms=500)
        mock_monotonic.side_effect = [0.0, 0.6]  # 600ms > 500ms threshold

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": [{"id": "123"}]}
        mock_request.return_value = mock_response

        weclapp.get("article", id="123")

        mock_logger.warning.assert_any_call(
            "[API_SLOW] Weclapp GET /webapp/api/v1/article -> 200 (600ms)"
        )

    @patch('weclappy.time.monotonic')
    @patch('weclappy.logger')
    @patch('weclappy.requests.Session.request')
    def test_query_params_not_in_logged_path(self, mock_request, mock_logger, mock_monotonic):
        """Query params are never included in logged path."""
        mock_monotonic.side_effect = [0.0, 0.1]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": []}
        mock_request.return_value = mock_response

        self.weclapp.get("salesOrder", params={"token": "secret123", "filter": "active"})

        # Verify the exact log message contains only the path, no query params
        mock_logger.info.assert_any_call(
            "[API] Weclapp GET /webapp/api/v1/salesOrder -> 200 (100ms)"
        )

        # Verify no timing log call contains sensitive query params
        all_calls = mock_logger.info.call_args_list + mock_logger.warning.call_args_list
        for call_args in all_calls:
            if call_args[0]:
                msg = str(call_args[0][0])
                if "[API]" in msg or "[API_SLOW]" in msg:
                    self.assertNotIn("secret123", msg)
                    self.assertNotIn("token=", msg)


class TestWeclappEntity(unittest.TestCase):
    """Unit tests for the WeclappEntity dynamic model."""

    def _row(self):
        return {
            "id": "ship-1",
            "shipmentNumber": "S-1000",
            "customerId": "cust-1",
            "customAttributes": [
                {
                    "attributeDefinitionId": "def-1",
                    "internalName": "carrierTrackingId",
                    "stringValue": "TRACK-42",
                    "numberValue": None,
                    "booleanValue": None,
                },
                {
                    "attributeDefinitionId": "def-2",
                    "internalName": "fragile",
                    "stringValue": None,
                    "booleanValue": True,
                },
                {
                    "attributeDefinitionId": "def-3",
                    "internalName": "weightKg",
                    "numberValue": "12.5",
                    "stringValue": None,
                },
            ],
        }

    def test_dict_compat(self):
        """Existing dict-style access continues to work."""
        from weclappy import WeclappEntity

        entity = WeclappEntity.from_row(self._row())
        self.assertEqual(entity["id"], "ship-1")
        self.assertEqual(entity.get("shipmentNumber"), "S-1000")
        self.assertIn("customerId", entity)

    def test_attribute_access_for_built_in_field(self):
        from weclappy import WeclappEntity

        entity = WeclappEntity.from_row(self._row())
        self.assertEqual(entity.id, "ship-1")
        self.assertEqual(entity.shipmentNumber, "S-1000")

    def test_custom_attribute_flattening(self):
        from weclappy import WeclappEntity

        entity = WeclappEntity.from_row(self._row())
        self.assertEqual(entity.carrierTrackingId, "TRACK-42")
        self.assertEqual(entity.fragile, True)
        self.assertEqual(entity.weightKg, "12.5")
        # Original list still accessible.
        self.assertEqual(len(entity["customAttributes"]), 3)

    def test_custom_attribute_round_trip_via_to_payload(self):
        from weclappy import WeclappEntity

        entity = WeclappEntity.from_row(self._row())
        entity.carrierTrackingId = "TRACK-99"
        entity.fragile = False

        payload = entity.to_payload()

        # Top-level flattened keys are dropped from payload
        self.assertNotIn("carrierTrackingId", payload)
        self.assertNotIn("fragile", payload)
        self.assertNotIn("weightKg", payload)

        # customAttributes rebuilt with new values in the original slot/field
        cas_by_internal = {
            ca["internalName"]: ca for ca in payload["customAttributes"]
        }
        self.assertEqual(cas_by_internal["carrierTrackingId"]["stringValue"], "TRACK-99")
        self.assertEqual(cas_by_internal["fragile"]["booleanValue"], False)
        # Untouched custom attribute keeps its value
        self.assertEqual(cas_by_internal["weightKg"]["numberValue"], "12.5")

        # Other built-ins untouched
        self.assertEqual(payload["id"], "ship-1")
        self.assertEqual(payload["customerId"], "cust-1")

    def test_built_in_field_is_read_only(self):
        from weclappy import WeclappEntity

        entity = WeclappEntity.from_row(self._row())
        with self.assertRaises(AttributeError):
            entity.id = "other"

    def test_built_in_collision_built_in_wins(self):
        """If a customAttribute internalName collides with a built-in, built-in wins."""
        from weclappy import WeclappEntity

        row = {
            "id": "x",
            "shipmentNumber": "S-1",
            "customAttributes": [
                {
                    "attributeDefinitionId": "def-1",
                    "internalName": "shipmentNumber",
                    "stringValue": "OVERWRITE-ATTEMPT",
                }
            ],
        }
        with self.assertLogs("weclappy", level="WARNING") as ctx:
            entity = WeclappEntity.from_row(row)
        self.assertTrue(any("collides" in m for m in ctx.output))
        # Built-in retained.
        self.assertEqual(entity.shipmentNumber, "S-1")
        # No round-trip entry for this name.
        payload = entity.to_payload()
        cas_by_internal = {
            ca["internalName"]: ca for ca in payload["customAttributes"]
        }
        self.assertEqual(
            cas_by_internal["shipmentNumber"]["stringValue"], "OVERWRITE-ATTEMPT"
        )

    def test_additional_properties_merge_per_row(self):
        from weclappy import WeclappEntity

        entity = WeclappEntity.from_row(
            {"id": "ship-1"},
            additional_properties_for_row={"totalWeight": {"value": 12.5}},
        )
        self.assertEqual(entity.totalWeight, {"value": 12.5})
        # additionalProperties keys are dropped from to_payload output.
        payload = entity.to_payload()
        self.assertNotIn("totalWeight", payload)

    def test_unknown_attribute_raises(self):
        from weclappy import WeclappEntity

        entity = WeclappEntity.from_row({"id": "x"})
        with self.assertRaises(AttributeError):
            _ = entity.nonexistent

    @patch('weclappy.requests.Session.request')
    def test_get_by_id_returns_entity_with_resolved_reference(self, mock_request):
        """End-to-end: GET by id, customAttribute flatten, *Id auto-resolve, additional props merge."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {
            "result": [
                {
                    "id": "ship-1",
                    "shipmentNumber": "S-1000",
                    "customerId": "cust-1",
                    "customAttributes": [
                        {
                            "attributeDefinitionId": "def-1",
                            "internalName": "carrierTrackingId",
                            "stringValue": "TRACK-42",
                        },
                    ],
                }
            ],
            "additionalProperties": {
                "totalWeight": [{"value": 12.5}],
            },
            "referencedEntities": {
                "customer": [
                    {"id": "cust-1", "name": "Acme GmbH"},
                ],
            },
        }
        mock_request.return_value = mock_response

        weclapp = Weclapp("https://test.weclapp.com/webapp/api/v1", "test_api_key")
        shipment = weclapp.get("shipment", id="ship-1")

        # Flattened customAttribute
        self.assertEqual(shipment.carrierTrackingId, "TRACK-42")
        # Per-row additionalProperty
        self.assertEqual(shipment.totalWeight, {"value": 12.5})
        # Lazy referenced-entity resolve
        self.assertEqual(shipment.customer.name, "Acme GmbH")
        # Raw *Id still available
        self.assertEqual(shipment.customerId, "cust-1")

    def test_referenced_entity_resolution(self):
        from weclappy import WeclappEntity

        ref_map = {
            "customer": {
                "cust-1": {"id": "cust-1", "name": "Acme GmbH"},
            }
        }
        entity = WeclappEntity.from_row(
            {"id": "ship-1", "customerId": "cust-1"},
            referenced_entities=ref_map,
        )
        # Raw *Id still present
        self.assertEqual(entity.customerId, "cust-1")
        # Lazy resolved object via .customer
        self.assertEqual(entity.customer.id, "cust-1")
        self.assertEqual(entity.customer.name, "Acme GmbH")
        # Cached: same object on second access
        self.assertIs(entity.customer, entity.customer)

    def test_referenced_entity_flat_id_fallback(self):
        """weclapp uses unified types under different field names (customerId
        resolves to the party bucket). Flat-id fallback handles this."""
        from weclappy import WeclappEntity

        ref_map = {
            "party": {"p-1": {"id": "p-1", "company": "Acme GmbH"}},
        }
        entity = WeclappEntity.from_row(
            {"id": "x", "customerId": "p-1", "invoiceRecipientId": "p-1"},
            referenced_entities=ref_map,
        )
        self.assertEqual(entity.customer.company, "Acme GmbH")
        self.assertEqual(entity.invoiceRecipient.company, "Acme GmbH")

    def test_custom_attribute_flatten_via_attribute_definitions(self):
        """When entity-level customAttributes lack internalName (real weclapp
        shape), the attribute_definitions map is used to derive the field name
        from the definition's attributeKey."""
        from weclappy import WeclappEntity

        attr_defs = {
            "def-1": {"id": "def-1", "attributeKey": "tracking_id"},
            "def-2": {"id": "def-2", "attributeKey": "fragile"},
        }
        entity = WeclappEntity.from_row(
            {
                "id": "x",
                "customAttributes": [
                    {"attributeDefinitionId": "def-1", "stringValue": "T-1"},
                    {"attributeDefinitionId": "def-2", "booleanValue": True},
                ],
            },
            attribute_definitions=attr_defs,
        )
        self.assertEqual(entity.tracking_id, "T-1")
        self.assertEqual(entity.fragile, True)

        # Round-trip preserves values back into the customAttributes array.
        entity.tracking_id = "T-2"
        payload = entity.to_payload()
        cas_by_def = {ca["attributeDefinitionId"]: ca for ca in payload["customAttributes"]}
        self.assertEqual(cas_by_def["def-1"]["stringValue"], "T-2")


class TestWeclappEntityNested(unittest.TestCase):
    """Phase 5: recursive wrapping of nested entity values."""

    def _order_row(self):
        return {
            "id": "order-1",
            "orderNumber": "SO-1",
            "customerId": "cust-1",
            "recordAddress": {
                "street": "Main 1",
                "city": "Berlin",
                "countryCode": "DE",
            },
            "orderItems": [
                {
                    "id": "item-1",
                    "articleId": "art-1",
                    "unitId": "unit-1",
                    "quantity": "2",
                    "customAttributes": [
                        {
                            "attributeDefinitionId": "ndef-1",
                            "internalName": "lineNote",
                            "stringValue": "handle with care",
                        },
                    ],
                },
                {
                    "id": "item-2",
                    "articleId": "art-2",
                    "unitId": "unit-1",
                    "quantity": "1",
                    "customAttributes": [],
                },
            ],
            "tags": ["urgent", "vip"],
        }

    def _ref_map(self):
        return {
            "customer": {"cust-1": {"id": "cust-1", "name": "Acme GmbH"}},
            "article": {
                "art-1": {"id": "art-1", "articleNumber": "A-001", "name": "Widget"},
                "art-2": {"id": "art-2", "articleNumber": "A-002", "name": "Gadget"},
            },
            "unit": {"unit-1": {"id": "unit-1", "name": "Piece"}},
        }

    def test_nested_list_items_are_wrapped(self):
        from weclappy import WeclappEntity

        order = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        self.assertIsInstance(order.orderItems[0], WeclappEntity)
        self.assertEqual(order.orderItems[0].id, "item-1")
        # Raw *Id preserved.
        self.assertEqual(order.orderItems[0].articleId, "art-1")

    def test_nested_id_resolves_via_shared_ref_map(self):
        from weclappy import WeclappEntity

        order = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        self.assertEqual(order.orderItems[0].article.articleNumber, "A-001")
        self.assertEqual(order.orderItems[1].article.name, "Gadget")
        self.assertEqual(order.orderItems[0].unit.name, "Piece")

    def test_nested_custom_attribute_flatten(self):
        from weclappy import WeclappEntity

        order = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        self.assertEqual(order.orderItems[0].lineNote, "handle with care")

    def test_nested_custom_attribute_round_trip(self):
        from weclappy import WeclappEntity

        order = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        order.orderItems[0].lineNote = "fragile - rush"

        payload = order.to_payload()

        # Top-level untouched
        self.assertEqual(payload["id"], "order-1")
        # Nested customAttributes rebuilt with edited value under the original typed-value field
        item_payload = payload["orderItems"][0]
        self.assertNotIn("lineNote", item_payload)
        nested_cas = {ca["internalName"]: ca for ca in item_payload["customAttributes"]}
        self.assertEqual(nested_cas["lineNote"]["stringValue"], "fragile - rush")
        # Untouched second item retained.
        self.assertEqual(payload["orderItems"][1]["articleId"], "art-2")
        # Payload should be plain dicts, not WeclappEntity, all the way down.
        self.assertIs(type(payload["orderItems"][0]), dict)
        self.assertIs(type(payload["orderItems"][0]["customAttributes"][0]), dict)

    def test_top_level_dict_field_is_wrapped(self):
        from weclappy import WeclappEntity

        order = WeclappEntity.from_row(self._order_row())
        self.assertIsInstance(order.recordAddress, WeclappEntity)
        self.assertEqual(order.recordAddress.street, "Main 1")

    def test_identity_stable_for_nested_entities(self):
        from weclappy import WeclappEntity

        order = WeclappEntity.from_row(self._order_row())
        self.assertIs(order.orderItems[0], order.orderItems[0])
        self.assertIs(order.recordAddress, order.recordAddress)

    def test_mixed_list_wraps_dicts_only(self):
        from weclappy import WeclappEntity

        row = {
            "id": "x",
            "tags": ["a", "b", "c"],
            "entries": [{"id": "1"}, "scalar", {"id": "2"}, 42],
        }
        entity = WeclappEntity.from_row(row)
        self.assertEqual(entity.tags, ["a", "b", "c"])
        self.assertIsInstance(entity.entries[0], WeclappEntity)
        self.assertEqual(entity.entries[1], "scalar")
        self.assertIsInstance(entity.entries[2], WeclappEntity)
        self.assertEqual(entity.entries[3], 42)

    def test_dict_method_name_collision_falls_back_to_bracket_access(self):
        """Field names that collide with dict methods (items, keys, values, get,
        pop, update, ...) are only reachable via bracket access; attribute
        access returns the bound method. This is an inherent property of
        subclassing dict and applies at every nesting level."""
        from weclappy import WeclappEntity

        row = {"id": "x", "items": [{"id": "1"}]}
        entity = WeclappEntity.from_row(row)
        # Bracket access returns the wrapped list of entities.
        self.assertIsInstance(entity["items"][0], WeclappEntity)
        # Attribute access still resolves to the dict.items method.
        self.assertTrue(callable(entity.items))

    def test_custom_attributes_inner_items_remain_plain(self):
        """The raw customAttributes list itself is not wrapped — its dicts are metadata."""
        from weclappy import WeclappEntity

        row = {
            "id": "x",
            "customAttributes": [
                {
                    "attributeDefinitionId": "d",
                    "internalName": "foo",
                    "stringValue": "bar",
                }
            ],
        }
        entity = WeclappEntity.from_row(row)
        ca_item = entity["customAttributes"][0]
        self.assertIs(type(ca_item), dict)
        self.assertNotIsInstance(ca_item, WeclappEntity)

    def test_from_row_is_idempotent(self):
        from weclappy import WeclappEntity

        first = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        second = WeclappEntity.from_row(first)
        self.assertIs(first, second)

    def test_depth_guard(self):
        """Pathologically deep nesting raises a clear error rather than recursing forever."""
        from weclappy import WeclappEntity

        # Build a deeply nested chain via repeated dict-valued field.
        deep: Any = {"id": "leaf"}
        for _ in range(WeclappEntity._MAX_WRAP_DEPTH + 5):
            deep = {"id": "n", "child": deep}
        with self.assertRaises(ValueError):
            WeclappEntity.from_row(deep)

    def test_input_row_not_mutated(self):
        """Wrapping must not mutate the user's input row."""
        from weclappy import WeclappEntity

        row = self._order_row()
        original_items = row["orderItems"]
        original_first_item = original_items[0]

        WeclappEntity.from_row(row, referenced_entities=self._ref_map())

        # Input list and its inner dicts remain plain dicts; identity preserved.
        self.assertIs(row["orderItems"], original_items)
        self.assertIs(row["orderItems"][0], original_first_item)
        self.assertIs(type(row["orderItems"][0]), dict)


if __name__ == "__main__":
    unittest.main()
