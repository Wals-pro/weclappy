"""Unit tests for the Weclapp client, its errors and the WeclappEntity model.

Every test mocks the transport (``session.request``); no credentials needed.
"""

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from weclappy import (
    Weclapp,
    WeclappAPIError,
    WeclappEntity,
    WeclappNotFoundError,
    WeclappPaginationError,
    WeclappResponse,
    WeclappTransportError,
    WeclappValidationError,
    __version__,
    infer_content_type,
)

BASE_URL = "https://test.weclapp.com/webapp/api/v1"
API_ROOT = f"{BASE_URL}/"


@pytest.fixture
def api(make_client):
    return make_client(BASE_URL, api_key="test_api_key")


def assert_sent(transport, method, url, **expected):
    """The last request went to ``method url`` with (at least) ``expected`` kwargs."""
    sent = transport.call_args
    assert sent.args == (method, url)
    assert sent.kwargs["allow_redirects"] is False
    for key, value in expected.items():
        assert sent.kwargs[key] == value, key


class TestWeclappClient:
    """Request construction and response handling for the public methods."""

    def test_init(self, api):
        assert api.base_url == API_ROOT
        assert api.timeout == 120
        headers = api.session.headers
        assert headers["AuthenticationToken"] == "test_api_key"
        assert headers["Content-Type"] == "application/json"
        assert headers["User-Agent"] == f"weclappy/{__version__}"
        assert headers["X-Weclapp-Wait-Timeout-Ms"] == "30000"
        assert headers["X-Weclapp-Request-Timeout-Ms"] == "110000"

    def test_for_tenant_builds_the_v2_api_root(self):
        assert Weclapp.for_tenant("acme", "key").base_url == (
            "https://acme.weclapp.com/webapp/api/v2/"
        )
        assert Weclapp.for_tenant("erp.example.com", "key", api_version=1).base_url == (
            "https://erp.example.com/webapp/api/v1/"
        )

    @pytest.mark.parametrize(
        ("base_url", "api_key"),
        [("ftp://test.weclapp.com", "key"), ("https://x.test/api?a=1", "key"), (BASE_URL, " ")],
    )
    def test_init_rejects_invalid_configuration(self, base_url, api_key):
        with pytest.raises(ValueError, match=r"base_url|api_key"):
            Weclapp(base_url, api_key)

    def test_get_single_entity(self, api, fake_transport):
        """Single-entity GET routes via id-eq on the list endpoint."""
        transport = fake_transport(api, {"result": [{"id": "123", "name": "Test Entity"}]})

        result = api.get("article", entity_id="123")

        assert_sent(
            transport,
            "GET",
            f"{API_ROOT}article",
            params={"id-eq": "123", "page": 1, "pageSize": 1},
            timeout=120,
        )
        assert result["id"] == "123"
        assert result.name == "Test Entity"

    def test_get_single_entity_not_found_raises_404(self, api, fake_transport):
        """Empty result on id-eq raises a synthetic 404 to preserve the contract."""
        fake_transport(api, {"result": []})

        with pytest.raises(WeclappNotFoundError) as exc_info:
            api.get("article", "missing")

        assert exc_info.value.is_not_found
        assert exc_info.value.status_code == 404
        assert exc_info.value.url == f"{API_ROOT}article"

    def test_get_entity_list(self, api, fake_transport):
        rows = [{"id": "123", "name": "Entity 1"}, {"id": "456", "name": "Entity 2"}]
        transport = fake_transport(api, {"result": rows})

        result = api.get("article")

        assert_sent(transport, "GET", f"{API_ROOT}article", params={}, timeout=120)
        assert result == rows

    @pytest.mark.parametrize(
        "params",
        [
            {"additionalProperties": "currentSalesPrice"},
            {"additionalProperties": "currentSalesPrice,averagePrice"},
            {"includeReferencedEntities": "unitId"},
            {"includeReferencedEntities": "unitId,articleCategoryId"},
            {"additionalProperties": "currentSalesPrice", "includeReferencedEntities": "unitId"},
        ],
    )
    def test_get_passes_projection_params_through_unchanged(self, api, fake_transport, params):
        transport = fake_transport(api, {"result": []})

        api.get("article", params=params)

        assert_sent(transport, "GET", f"{API_ROOT}article", params=params)

    def test_get_with_additional_properties(self, api, fake_transport):
        fake_transport(
            api,
            {
                "result": [{"id": "123", "name": "Article 1"}, {"id": "456", "name": "Article 2"}],
                "additionalProperties": {
                    "currentSalesPrice": [
                        {"articleUnitPrice": "39.95", "currencyId": "256"},
                        {"articleUnitPrice": "49.95", "currencyId": "256"},
                    ],
                    "averagePrice": [{"amountInCompanyCurrency": "35.00"}, None],
                },
            },
        )

        result = api.get(
            "article",
            params={"additionalProperties": "currentSalesPrice,averagePrice"},
            return_weclapp_response=True,
        )

        assert isinstance(result, WeclappResponse)
        assert len(result.result) == 2
        assert result.result[0]["name"] == "Article 1"
        prices = result.additional_properties["currentSalesPrice"]
        assert prices[0]["articleUnitPrice"] == "39.95"
        assert result.additional_properties["averagePrice"][0]["amountInCompanyCurrency"] == (
            "35.00"
        )
        assert result.result[1].currentSalesPrice["articleUnitPrice"] == "49.95"

    def test_get_with_referenced_entities(self, api, fake_transport):
        fake_transport(
            api,
            {
                "result": [
                    {"id": "123", "name": "Article 1", "unitId": "456", "articleCategoryId": "789"},
                    {"id": "790", "name": "Article 2", "unitId": "456"},
                ],
                "referencedEntities": {
                    "unit": [{"id": "456", "name": "Piece", "abbreviation": "pc"}],
                    "articleCategory": [{"id": "789", "name": "Category 1"}],
                },
            },
        )

        result = api.get(
            "article",
            params={"includeReferencedEntities": "unitId,articleCategoryId"},
            return_weclapp_response=True,
        )

        assert isinstance(result, WeclappResponse)
        assert len(result.result) == 2
        assert result.result[0]["unitId"] == "456"
        assert result.referenced_entities["unit"]["456"]["name"] == "Piece"
        assert result.referenced_entities["articleCategory"]["789"]["name"] == "Category 1"
        assert result.result[1].unit.name == "Piece"

    def test_get_with_both_parameters(self, api, fake_transport):
        fake_transport(
            api,
            {
                "result": [{"id": "123", "name": "Article 1", "unitId": "456"}],
                "additionalProperties": {"currentSalesPrice": [{"articleUnitPrice": "39.95"}]},
                "referencedEntities": {"unit": [{"id": "456", "name": "Piece"}]},
            },
        )

        result = api.get(
            "article",
            params={
                "additionalProperties": "currentSalesPrice",
                "includeReferencedEntities": "unitId",
            },
            return_weclapp_response=True,
        )

        assert isinstance(result, WeclappResponse)
        assert result.result[0]["name"] == "Article 1"
        assert result.additional_properties["currentSalesPrice"][0]["articleUnitPrice"] == "39.95"
        assert result.referenced_entities["unit"]["456"]["name"] == "Piece"

    def test_get_all_sequential(self, api, fake_transport):
        transport = fake_transport(
            api,
            {"result": [{"id": "1", "name": "Item 1"}, {"id": "2", "name": "Item 2"}]},
            {"result": [{"id": "3", "name": "Item 3"}]},
        )

        result = api.get_all("article", {"pageSize": 2}, threaded=False)

        assert [row["name"] for row in result] == ["Item 1", "Item 2", "Item 3"]
        assert transport.call_count == 2
        first, second = (c.kwargs["params"] for c in transport.call_args_list)
        assert first == {"pageSize": 2, "sort": "id", "page": 1}
        assert second["page"] == 2

    def test_get_all_with_additional_properties(self, api, fake_transport):
        fake_transport(
            api,
            {
                "result": [{"id": "123", "name": "Article 1"}, {"id": "456", "name": "Article 2"}],
                "additionalProperties": {
                    "currentSalesPrice": [
                        {"articleUnitPrice": "39.95"},
                        {"articleUnitPrice": "49.95"},
                    ]
                },
            },
        )

        result = api.get_all(
            "article",
            params={"additionalProperties": "currentSalesPrice"},
            threaded=False,
            return_weclapp_response=True,
        )

        assert isinstance(result, WeclappResponse)
        assert len(result.result) == 2
        assert result.result[0]["name"] == "Article 1"
        assert result.additional_properties["currentSalesPrice"][0]["articleUnitPrice"] == "39.95"

    def test_get_all_with_referenced_entities(self, api, fake_transport):
        fake_transport(
            api,
            {
                "result": [
                    {"id": "123", "name": "Article 1", "unitId": "456"},
                    {"id": "789", "name": "Article 2", "unitId": "456"},
                ],
                "referencedEntities": {
                    "unit": [{"id": "456", "name": "Piece", "abbreviation": "pc"}]
                },
            },
        )

        result = api.get_all(
            "article",
            params={"includeReferencedEntities": "unitId"},
            threaded=False,
            return_weclapp_response=True,
        )

        assert isinstance(result, WeclappResponse)
        assert len(result.result) == 2
        assert result.result[0]["unitId"] == "456"
        assert result.referenced_entities["unit"]["456"]["name"] == "Piece"

    @staticmethod
    def _invoice_page(*numbers):
        return {
            "result": [{"id": str(n), "salesInvoiceId": f"inv{n}"} for n in numbers],
            "referencedEntities": {
                "salesInvoice": [{"id": f"inv{n}", "invoiceNumber": f"INV-00{n}"} for n in numbers]
            },
        }

    def _assert_all_invoices_merged(self, result):
        assert isinstance(result, WeclappResponse)
        assert len(result.result) == 5
        invoices = result.referenced_entities["salesInvoice"]
        # All five invoices must be present, not only those of the last page.
        assert set(invoices) == {"inv1", "inv2", "inv3", "inv4", "inv5"}
        assert invoices["inv1"]["invoiceNumber"] == "INV-001"
        assert invoices["inv5"]["invoiceNumber"] == "INV-005"

    def test_get_all_merges_referenced_entities_sequential(self, api, fake_transport):
        fake_transport(
            api, self._invoice_page(1, 2), self._invoice_page(3, 4), self._invoice_page(5)
        )

        result = api.get_all(
            "accountOpenItem",
            params={"pageSize": 2, "includeReferencedEntities": "salesInvoiceId"},
            threaded=False,
            return_weclapp_response=True,
        )

        self._assert_all_invoices_merged(result)

    @pytest.mark.parametrize("threaded", [True, "auto"])
    def test_get_all_merges_referenced_entities_threaded(self, api, fake_transport, threaded):
        pages = {1: (1, 2), 2: (3, 4), 3: (5,)}

        def handler(method, url, **kwargs):
            if url.endswith("/accountOpenItem/count"):
                return {"result": 5}
            return self._invoice_page(*pages[kwargs["params"]["page"]])

        transport = fake_transport(api, handler=handler)

        result = api.get_all(
            "accountOpenItem",
            params={"pageSize": 2, "includeReferencedEntities": "salesInvoiceId"},
            threaded=threaded,
            return_weclapp_response=True,
        )

        self._assert_all_invoices_merged(result)
        # Page 1 first, then the count, then the remaining pages.
        urls = [c.args[1] for c in transport.call_args_list]
        assert urls[:2] == [f"{API_ROOT}accountOpenItem", f"{API_ROOT}accountOpenItem/count"]
        assert len(urls) == 4

    def test_get_all_merges_multiple_entity_types(self, api, fake_transport):
        def page(*numbers):
            return {
                "result": [
                    {"id": str(n), "salesInvoiceId": f"inv{n}", "customerId": f"cust{n}"}
                    for n in numbers
                ],
                "referencedEntities": {
                    "salesInvoice": [{"id": f"inv{n}"} for n in numbers],
                    "customer": [{"id": f"cust{n}", "name": f"Customer {n}"} for n in numbers],
                },
            }

        fake_transport(api, page(1, 2), page(3))

        result = api.get_all(
            "accountOpenItem",
            params={"pageSize": 2, "includeReferencedEntities": "salesInvoiceId,customerId"},
            threaded=False,
            return_weclapp_response=True,
        )

        assert set(result.referenced_entities["salesInvoice"]) == {"inv1", "inv2", "inv3"}
        assert set(result.referenced_entities["customer"]) == {"cust1", "cust2", "cust3"}

    def test_get_all_shortfall_against_count_raises(self, api, fake_transport):
        def handler(method, url, **kwargs):
            if url.endswith("/article/count"):
                return {"result": 5}
            page = kwargs["params"]["page"]
            return {"result": [{"id": "1"}, {"id": "2"}]} if page == 1 else {"result": []}

        fake_transport(api, handler=handler)

        with pytest.raises(WeclappPaginationError, match="2 of 5"):
            api.get_all("article", {"pageSize": 2})

    def test_post(self, api, fake_transport, make_response):
        transport = fake_transport(api, make_response(201, {"id": "123", "name": "New Article"}))
        data = {"name": "New Article", "articleNumber": "A123"}

        result = api.post("article", data)

        assert_sent(transport, "POST", f"{API_ROOT}article", json=data, timeout=120)
        assert "params" not in transport.call_args.kwargs
        assert result == {"id": "123", "name": "New Article"}

    def test_post_with_params(self, api, fake_transport, make_response):
        transport = fake_transport(api, make_response(201, {"id": "123", "name": "Draft"}))
        data = {"name": "Draft Quotation"}

        result = api.post("quotation", data, params={"dryRun": True})

        assert_sent(transport, "POST", f"{API_ROOT}quotation", json=data, params={"dryRun": True})
        assert result["id"] == "123"

    def test_put(self, api, fake_transport):
        transport = fake_transport(api, {"id": "123", "name": "Updated Article"})
        data = {"name": "Updated Article"}

        result = api.put("article", entity_id="123", data=data)

        assert_sent(
            transport,
            "PUT",
            f"{API_ROOT}article/id/123",
            json=data,
            params={"ignoreMissingProperties": True},
            timeout=120,
        )
        assert result["name"] == "Updated Article"

    def test_put_lets_the_caller_override_ignore_missing_properties(self, api, fake_transport):
        transport = fake_transport(api, {"id": "123"})

        api.put("article", "123", {"name": "x"}, params={"ignoreMissingProperties": False})

        assert transport.call_args.kwargs["params"] == {"ignoreMissingProperties": False}

    def test_delete(self, api, fake_transport, make_response):
        transport = fake_transport(api, make_response(204, content=b"", content_type=None))

        result = api.delete("article", entity_id="123")

        assert_sent(transport, "DELETE", f"{API_ROOT}article/id/123", timeout=120)
        assert result == {}

    def test_entity_ids_are_percent_encoded(self, api, fake_transport):
        transport = fake_transport(api, {})

        api.delete("article", "a b%")

        assert transport.call_args.args[1] == f"{API_ROOT}article/id/a%20b%25"

    def test_call_method(self, api, fake_transport):
        transport = fake_transport(api, {"result": "success"})

        result = api.call_method(
            "salesInvoice", "downloadLatestSalesInvoicePdf", entity_id="123", method="GET"
        )

        assert_sent(
            transport,
            "GET",
            f"{API_ROOT}salesInvoice/id/123/downloadLatestSalesInvoicePdf",
            timeout=120,
        )
        assert "json" not in transport.call_args.kwargs
        assert result["result"] == "success"

    def test_call_method_rejects_other_http_methods(self, api):
        with pytest.raises(ValueError, match="GET and POST"):
            api.call_method("article", "x", method="DELETE")

    def test_weclapp_response_class(self):
        api_response = {
            "result": [{"id": "123", "name": "Article 1", "unitId": "456"}],
            "additionalProperties": {"currentSalesPrice": [{"articleUnitPrice": "39.95"}]},
            "referencedEntities": {"unit": [{"id": "456", "name": "Piece"}]},
        }

        response = WeclappResponse.from_api_response(api_response)

        assert len(response.result) == 1
        assert response.result[0]["name"] == "Article 1"
        assert response.additional_properties["currentSalesPrice"][0]["articleUnitPrice"] == (
            "39.95"
        )
        assert response.referenced_entities["unit"]["456"]["name"] == "Piece"
        assert response.raw_response == api_response

    def test_api_error_includes_response_text(self, api, fake_transport, make_response):
        error_response = make_response(
            400, {"error": "Invalid request", "details": "Missing required field: name"}
        )
        fake_transport(api, error_response)

        with pytest.raises(WeclappAPIError) as exc_info:
            api.get("article")

        exception = exc_info.value
        assert "Invalid request" in str(exception)
        assert "Response body:" in str(exception)
        assert exception.response_text == error_response.text
        assert exception.status_code == 400
        assert exception.response is error_response

    def test_api_error_includes_response_text_non_json(self, api, fake_transport, make_response):
        body = "<html><body>Internal Server Error</body></html>"
        fake_transport(api, make_response(500, content=body.encode(), content_type="text/html"))

        with pytest.raises(WeclappAPIError) as exc_info:
            api.post("article", {"name": "Test"})

        exception = exc_info.value
        assert "Internal Server Error" in str(exception)
        assert "Response body:" in str(exception)
        assert exception.response_text == body
        assert exception.status_code == 500

    def test_api_error_includes_response_text_on_put(self, api, fake_transport, make_response):
        error_response = make_response(
            404, {"error": "Entity not found", "entityId": "nonexistent123"}
        )
        fake_transport(api, error_response)

        with pytest.raises(WeclappNotFoundError) as exc_info:
            api.put("article", entity_id="nonexistent123", data={"name": "Updated"})

        assert "Entity not found" in str(exc_info.value)
        assert exc_info.value.response_text == error_response.text
        assert exc_info.value.status_code == 404

    def test_http_errors_map_to_typed_subclasses(self, api, fake_transport, make_problem):
        fake_transport(api, make_problem(400, "validation"))

        with pytest.raises(WeclappValidationError):
            api.post("article", {"name": "x"})


class TestWeclappAPIErrorAttributes:
    """WeclappAPIError parses weclapp problem documents."""

    def test_weclapp_api_error_attributes(self):
        """Test WeclappAPIError exception attributes."""
        # Create a mock response
        mock_response = MagicMock()
        mock_response.text = '{"error": "Test error"}'
        mock_response.status_code = 422
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article"

        # Create exception with response
        exc = WeclappAPIError("Test message", response=mock_response)
        assert str(exc) == "Test message"
        assert exc.response == mock_response
        assert exc.response_text == '{"error": "Test error"}'
        assert exc.status_code == 422
        assert exc.error == "Test error"

        # Create exception without response
        exc_no_response = WeclappAPIError("Test message without response")
        assert exc_no_response.response is None
        assert exc_no_response.response_text is None
        assert exc_no_response.status_code is None

        # Create exception with explicit response_text
        exc_explicit = WeclappAPIError("Test", response=mock_response, response_text="Custom text")
        assert exc_explicit.response_text == "Custom text"

    def test_weclapp_api_error_structured_fields(self):
        """Test WeclappAPIError parses structured error fields from JSON response."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/salesOrder"
        mock_response.text = """{
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
        }"""

        exc = WeclappAPIError("Validation failed", response=mock_response)

        # Check structured fields
        assert exc.error == "Validation failed"
        assert exc.detail == "One or more fields have invalid values"
        assert exc.title == "Bad Request"
        assert exc.error_type == "VALIDATION_ERROR"
        assert len(exc.validation_errors) == 2
        assert exc.validation_errors[0]["field"] == "customerNumber"
        assert len(exc.messages) == 2
        assert exc.messages[0]["severity"] == "ERROR"

    def test_weclapp_api_error_is_optimistic_lock(self):
        """Test WeclappAPIError detects optimistic lock errors."""
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article/id/123"
        mock_response.text = '{"detail": "Optimistic lock error", "error": "Version conflict"}'

        exc = WeclappAPIError("Version conflict", response=mock_response)
        assert exc.is_optimistic_lock

        # Test without optimistic lock
        mock_response2 = MagicMock()
        mock_response2.status_code = 400
        mock_response2.url = "https://test.weclapp.com/webapp/api/v1/article"
        mock_response2.text = '{"error": "Invalid data"}'

        exc2 = WeclappAPIError("Invalid data", response=mock_response2)
        assert not exc2.is_optimistic_lock

    def test_weclapp_api_error_is_not_found(self):
        """Test WeclappAPIError detects 404 errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article/id/123"
        mock_response.text = '{"error": "Entity not found"}'

        exc = WeclappAPIError("Not found", response=mock_response)
        assert exc.is_not_found
        assert not exc.is_rate_limited

    def test_weclapp_api_error_is_rate_limited(self):
        """Test WeclappAPIError detects rate limit errors."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article"
        mock_response.text = '{"error": "Too many requests"}'

        exc = WeclappAPIError("Rate limited", response=mock_response)
        assert exc.is_rate_limited
        assert not exc.is_not_found

    def test_weclapp_api_error_is_validation_error(self):
        """Test WeclappAPIError detects validation errors."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/salesOrder"
        mock_response.text = """{
            "error": "Validation failed",
            "validationErrors": [{"field": "name", "message": "Name is required"}]
        }"""

        exc = WeclappAPIError("Validation failed", response=mock_response)
        assert exc.is_validation_error

        # Test without validation errors
        mock_response2 = MagicMock()
        mock_response2.status_code = 500
        mock_response2.url = "https://test.weclapp.com/webapp/api/v1/article"
        mock_response2.text = '{"error": "Internal server error"}'

        exc2 = WeclappAPIError("Server error", response=mock_response2)
        assert not exc2.is_validation_error

    def test_weclapp_api_error_get_validation_messages(self):
        """Test WeclappAPIError extracts validation messages."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/salesOrder"
        mock_response.text = """{
            "validationErrors": [
                {"field": "name", "message": "Name is required"},
                {"field": "date", "message": "Invalid date"}
            ]
        }"""

        exc = WeclappAPIError("Validation failed", response=mock_response)
        messages = exc.get_validation_messages()

        assert len(messages) == 2
        assert messages[0] == "Name is required"
        assert messages[1] == "Invalid date"

    def test_weclapp_api_error_get_all_messages(self):
        """Test WeclappAPIError collects all error messages."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/salesOrder"
        mock_response.text = """{
            "error": "Request failed",
            "detail": "Multiple issues found",
            "validationErrors": [{"message": "Field A is invalid"}],
            "messages": [{"severity": "ERROR", "message": "Check field B"}]
        }"""

        exc = WeclappAPIError("Failed", response=mock_response)
        all_messages = exc.get_all_messages()

        assert "Request failed" in all_messages
        assert "Multiple issues found" in all_messages
        assert "Field A is invalid" in all_messages
        assert "[ERROR] Check field B" in all_messages

    def test_weclapp_api_error_non_json_response(self):
        """Test WeclappAPIError handles non-JSON responses gracefully."""
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.url = "https://test.weclapp.com/webapp/api/v1/article"
        mock_response.text = "<html><body>Bad Gateway</body></html>"

        exc = WeclappAPIError("Bad Gateway", response=mock_response)

        # Structured fields should be None/empty for non-JSON
        assert exc.error is None
        assert exc.detail is None
        assert exc.validation_errors == []
        assert exc.messages == []
        assert not exc.is_validation_error
        assert not exc.is_optimistic_lock


class TestInferContentType:
    """Unit tests for the infer_content_type helper function."""

    def test_infer_pdf(self):
        """Test PDF content type inference."""
        assert infer_content_type("document.pdf") == "application/pdf"
        assert infer_content_type("DOCUMENT.PDF") == "application/pdf"

    def test_infer_images(self):
        """Test image content type inference."""
        assert infer_content_type("photo.jpg") == "image/jpeg"
        assert infer_content_type("photo.jpeg") == "image/jpeg"
        assert infer_content_type("image.png") == "image/png"
        assert infer_content_type("animation.gif") == "image/gif"
        assert infer_content_type("modern.webp") == "image/webp"

    def test_infer_office_documents(self):
        """Test Office document content type inference."""
        office = "application/vnd.openxmlformats-officedocument"
        assert infer_content_type("doc.docx") == f"{office}.wordprocessingml.document"
        assert infer_content_type("sheet.xlsx") == f"{office}.spreadsheetml.sheet"

    def test_infer_unknown_extension(self):
        """Test that unknown extensions return None."""
        assert infer_content_type("file.unknown") is None
        assert infer_content_type("file.xyz123") is None

    def test_infer_no_extension(self):
        """Test files without extension."""
        assert infer_content_type("filename") is None
        assert infer_content_type("") is None
        assert infer_content_type(None) is None


class TestUploadMethod:
    """Unit tests for the Weclapp.upload method."""

    def test_upload_document_with_inferred_content_type(self, api, fake_transport):
        transport = fake_transport(api, {"result": {"id": "doc123"}})
        data = b"PDF content here"

        result = api.upload(
            "document",
            data=data,
            action="upload",
            filename="invoice.pdf",
            params={"entityName": "salesOrder", "entityId": "123", "name": "Invoice"},
        )

        assert_sent(transport, "POST", f"{API_ROOT}document/upload", data=data)
        assert transport.call_args.kwargs["headers"]["Content-Type"] == "application/pdf"
        assert transport.call_args.kwargs["params"]["entityName"] == "salesOrder"
        assert result == {"result": {"id": "doc123"}}

    def test_upload_article_image_with_id(self, api, fake_transport):
        transport = fake_transport(api, {"result": {"success": True}})

        api.upload(
            "article",
            data=b"JPEG image data",
            entity_id="art456",
            action="uploadArticleImage",
            filename="product.jpg",
            params={"name": "Main Image", "mainImage": True},
        )

        assert transport.call_args.args[1] == f"{API_ROOT}article/id/art456/uploadArticleImage"
        assert transport.call_args.kwargs["headers"]["Content-Type"] == "image/jpeg"

    def test_upload_with_explicit_content_type_override(self, api, fake_transport):
        transport = fake_transport(api, {"result": {"id": "doc123"}})

        api.upload(
            "document",
            data=b"Some data",
            action="upload",
            content_type="application/pdf",
            filename="file.unknown",
            params={"entityName": "contract", "entityId": "789", "name": "Contract"},
        )

        assert transport.call_args.kwargs["headers"]["Content-Type"] == "application/pdf"

    def test_upload_fallback_to_octet_stream(self, api, fake_transport):
        transport = fake_transport(api, {"result": {"id": "doc123"}})

        api.upload(
            "document",
            data=b"Binary data",
            action="upload",
            params={"entityName": "salesOrder", "entityId": "123", "name": "Data"},
        )

        assert transport.call_args.kwargs["headers"]["Content-Type"] == ("application/octet-stream")

    def test_upload_logs_warning_on_content_type_mismatch(self, api, fake_transport, caplog):
        fake_transport(api, {"result": {"id": "doc123"}})

        with caplog.at_level(logging.WARNING, logger="weclappy"):
            api.upload(
                "document",
                data=b"Some data",
                action="upload",
                content_type="application/pdf",
                filename="image.png",
                params={"entityName": "salesOrder", "entityId": "123", "name": "File"},
            )

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "mismatch" in warnings[0].lower()
        assert "application/pdf" in warnings[0]
        assert "image/png" in warnings[0]


class TestDownloadMethod:
    """Unit tests for the Weclapp.download method."""

    def test_download_document_by_id(self, api, fake_transport, make_response):
        transport = fake_transport(
            api, make_response(content=b"PDF content", content_type="application/pdf")
        )

        result = api.download("document", entity_id="doc123")

        assert_sent(transport, "GET", f"{API_ROOT}document/id/doc123/download")
        assert result["content"] == b"PDF content"
        assert result["content_type"] == "application/pdf"

    def test_download_with_id_and_action(self, api, fake_transport, make_response):
        transport = fake_transport(
            api, make_response(content=b"Invoice PDF", content_type="application/pdf")
        )

        api.download("salesInvoice", entity_id="inv123", action="downloadLatestSalesInvoicePdf")

        assert transport.call_args.args[1] == (
            f"{API_ROOT}salesInvoice/id/inv123/downloadLatestSalesInvoicePdf"
        )

    def test_download_article_image(self, api, fake_transport, make_response):
        fake_transport(
            api,
            make_response(
                content=b"JPEG image data",
                content_type="image/jpeg",
                headers={"Content-Disposition": 'attachment; filename="photo.jpg"'},
            ),
        )

        result = api.download(
            "article",
            entity_id="art456",
            action="downloadArticleImage",
            params={"articleImageId": "img789"},
        )

        assert result["content"] == b"JPEG image data"
        assert "image/jpeg" in result["content_type"]
        assert result["filename"] == "photo.jpg"

    def test_download_with_action_only(self, api, fake_transport):
        transport = fake_transport(api, {"result": "some data"})

        api.download("someEndpoint", action="someAction")

        assert transport.call_args.args[1] == f"{API_ROOT}someEndpoint/someAction"


class TestRequestTimingLogging:
    """HTTP request timing logs: ``[API]``, ``[API_SLOW]`` and errors."""

    @pytest.fixture(autouse=True)
    def _capture(self, caplog):
        caplog.set_level(logging.INFO, logger="weclappy")
        self.caplog = caplog

    def test_normal_request_logs_info_with_api_prefix(self, api, fake_transport):
        fake_transport(api, {"result": [{"id": "123", "name": "Test"}]})

        with patch("weclappy.client.time") as fake_time:
            fake_time.monotonic.side_effect = [0.0, 0.342]
            api.get("salesOrder", entity_id="123")

        assert "[API] Weclapp GET /webapp/api/v1/salesOrder -> 200 (342ms)" in self.caplog.messages

    def test_slow_request_logs_warning_with_api_slow_prefix(self, api, fake_transport):
        fake_transport(api, {"result": []})

        with patch("weclappy.client.time") as fake_time:
            fake_time.monotonic.side_effect = [0.0, 3.421]
            api.get("shipment")

        record = next(r for r in self.caplog.records if "[API_SLOW]" in r.getMessage())
        assert record.levelno == logging.WARNING
        assert record.getMessage() == (
            "[API_SLOW] Weclapp GET /webapp/api/v1/shipment -> 200 (3421ms)"
        )

    def test_error_request_logs_warning_with_error_status(self, api, fake_transport):
        fake_transport(api, requests.exceptions.ConnectionError("Connection refused"))

        with patch("weclappy.client.time") as fake_time:
            fake_time.monotonic.side_effect = [0.0, 5.123]
            with pytest.raises(WeclappTransportError):
                api.put("salesOrder", entity_id="12345", data={"name": "Test"})

        record = next(r for r in self.caplog.records if "ERROR" in r.getMessage())
        assert record.levelno == logging.WARNING
        assert record.getMessage() == (
            "[API] Weclapp PUT /webapp/api/v1/salesOrder/id/12345 -> ERROR (5123ms) ConnectionError"
        )

    def test_count_endpoint_in_threaded_get_all_is_logged(self, api, fake_transport):
        fake_transport(api, {"result": [{"id": "1"}]}, {"result": 1})

        with patch("weclappy.client.time") as fake_time:
            fake_time.monotonic.side_effect = [0.0, 0.1, 0.2, 0.356]
            api.get_all("salesOrder", {"pageSize": 1}, threaded=True)

        assert (
            "[API] Weclapp GET /webapp/api/v1/salesOrder/count -> 200 (156ms)"
            in self.caplog.messages
        )

    def test_retry_is_logged_with_api_retry_prefix(self, api, fake_transport, make_response):
        fake_transport(api, make_response(503), {"result": []})

        with patch("weclappy.client.time.sleep"):
            api.get("article")

        assert any(m.startswith("[API_RETRY] Weclapp GET") for m in self.caplog.messages)

    def test_queue_headers_are_logged(self, api, fake_transport, make_response):
        fake_transport(
            api,
            make_response(
                body={"result": []},
                headers={"X-Weclapp-Wait-Ms": "12", "X-Weclapp-Wait-Reason": "concurrency"},
            ),
        )

        api.get("article")

        assert any(
            m.startswith("[API_QUEUE]") and "wait_ms=12" in m and "reason=concurrency" in m
            for m in self.caplog.messages
        )

    def test_default_slow_threshold_ms(self, api):
        assert api.slow_threshold_ms == 2000

    def test_custom_slow_threshold_ms_in_constructor(self, make_client):
        assert make_client(BASE_URL, slow_threshold_ms=500).slow_threshold_ms == 500

    def test_custom_slow_threshold_triggers_warning(self, make_client, fake_transport):
        api = make_client(BASE_URL, slow_threshold_ms=500)
        fake_transport(api, {"result": [{"id": "123"}]})

        with patch("weclappy.client.time") as fake_time:
            fake_time.monotonic.side_effect = [0.0, 0.6]  # 600 ms > 500 ms threshold
            api.get("article", entity_id="123")

        assert "[API_SLOW] Weclapp GET /webapp/api/v1/article -> 200 (600ms)" in (
            self.caplog.messages
        )

    def test_query_params_and_token_never_logged(self, api, fake_transport):
        fake_transport(api, {"result": []})

        with patch("weclappy.client.time") as fake_time:
            fake_time.monotonic.side_effect = [0.0, 0.1]
            api.get("salesOrder", params={"token": "secret123", "filter": "active"})

        assert "[API] Weclapp GET /webapp/api/v1/salesOrder -> 200 (100ms)" in self.caplog.messages
        for message in self.caplog.messages:
            assert "secret123" not in message
            assert "token=" not in message
            assert "test_api_key" not in message


class TestWeclappEntity:
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

        entity = WeclappEntity.from_row(self._row())
        assert entity["id"] == "ship-1"
        assert entity.get("shipmentNumber") == "S-1000"
        assert "customerId" in entity

    def test_attribute_access_for_built_in_field(self):

        entity = WeclappEntity.from_row(self._row())
        assert entity.id == "ship-1"
        assert entity.shipmentNumber == "S-1000"

    def test_custom_attribute_flattening(self):

        entity = WeclappEntity.from_row(self._row())
        assert entity.carrierTrackingId == "TRACK-42"
        assert entity.fragile
        assert entity.weightKg == "12.5"
        # Original list still accessible.
        assert len(entity["customAttributes"]) == 3

    def test_custom_attribute_round_trip_via_to_payload(self):

        entity = WeclappEntity.from_row(self._row())
        entity.carrierTrackingId = "TRACK-99"
        entity.fragile = False

        payload = entity.to_payload()

        # Top-level flattened keys are dropped from payload
        assert "carrierTrackingId" not in payload
        assert "fragile" not in payload
        assert "weightKg" not in payload

        # customAttributes rebuilt with new values in the original slot/field
        cas_by_definition = {ca["attributeDefinitionId"]: ca for ca in payload["customAttributes"]}
        assert cas_by_definition["def-1"]["stringValue"] == "TRACK-99"
        assert not cas_by_definition["def-2"]["booleanValue"]
        # Untouched custom attribute keeps its value
        assert cas_by_definition["def-3"]["numberValue"] == "12.5"
        assert all("internalName" not in item for item in payload["customAttributes"])

        # Other built-ins untouched
        assert payload["id"] == "ship-1"
        assert payload["customerId"] == "cust-1"

    def test_built_in_field_is_read_only(self):

        entity = WeclappEntity.from_row(self._row())
        with pytest.raises(AttributeError):
            entity.id = "other"

    def test_built_in_collision_built_in_wins(self, caplog):
        """If a customAttribute internalName collides with a built-in, built-in wins."""

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
        with caplog.at_level(logging.WARNING, logger="weclappy"):
            entity = WeclappEntity.from_row(row)
        assert any("collides" in m for m in caplog.messages)
        # Built-in retained.
        assert entity.shipmentNumber == "S-1"
        # No round-trip entry for this name.
        payload = entity.to_payload()
        cas_by_definition = {ca["attributeDefinitionId"]: ca for ca in payload["customAttributes"]}
        assert cas_by_definition["def-1"]["stringValue"] == "OVERWRITE-ATTEMPT"
        assert "internalName" not in cas_by_definition["def-1"]

    def test_additional_properties_merge_per_row(self):

        entity = WeclappEntity.from_row(
            {"id": "ship-1"},
            additional_properties_for_row={"totalWeight": {"value": 12.5}},
        )
        assert entity.totalWeight == {"value": 12.5}
        # additionalProperties keys are dropped from to_payload output.
        payload = entity.to_payload()
        assert "totalWeight" not in payload

    def test_unknown_attribute_raises(self):

        entity = WeclappEntity.from_row({"id": "x"})
        with pytest.raises(AttributeError):
            _ = entity.nonexistent

    def test_get_by_id_returns_entity_with_resolved_reference(self, api, fake_transport):
        """GET by id: customAttribute flatten, *Id auto-resolve, additional props merge."""
        fake_transport(
            api,
            {
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
            },
        )

        shipment = api.get("shipment", entity_id="ship-1")

        # Flattened customAttribute
        assert shipment.carrierTrackingId == "TRACK-42"
        # Per-row additionalProperty
        assert shipment.totalWeight == {"value": 12.5}
        # Lazy referenced-entity resolve
        assert shipment.customer.name == "Acme GmbH"
        # Raw *Id still available
        assert shipment.customerId == "cust-1"

    def test_referenced_entity_resolution(self):

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
        assert entity.customerId == "cust-1"
        # Lazy resolved object via .customer
        assert entity.customer.id == "cust-1"
        assert entity.customer.name == "Acme GmbH"
        # Cached: same object on second access
        assert entity.customer is entity.customer

    def test_referenced_entity_flat_id_fallback(self):
        """weclapp uses unified types under different field names (customerId
        resolves to the party bucket). Flat-id fallback handles this."""

        ref_map = {
            "party": {"p-1": {"id": "p-1", "company": "Acme GmbH"}},
        }
        entity = WeclappEntity.from_row(
            {"id": "x", "customerId": "p-1", "invoiceRecipientId": "p-1"},
            referenced_entities=ref_map,
        )
        assert entity.customer.company == "Acme GmbH"
        assert entity.invoiceRecipient.company == "Acme GmbH"

    def test_custom_attribute_flatten_via_attribute_definitions(self):
        """When entity-level customAttributes lack internalName (real weclapp
        shape), the attribute_definitions map is used to derive the field name
        from the definition's attributeKey."""

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
        assert entity.tracking_id == "T-1"
        assert entity.fragile

        # Round-trip preserves values back into the customAttributes array.
        entity.tracking_id = "T-2"
        payload = entity.to_payload()
        cas_by_def = {ca["attributeDefinitionId"]: ca for ca in payload["customAttributes"]}
        assert cas_by_def["def-1"]["stringValue"] == "T-2"


class TestWeclappEntityNested:
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

        order = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        assert isinstance(order.orderItems[0], WeclappEntity)
        assert order.orderItems[0].id == "item-1"
        # Raw *Id preserved.
        assert order.orderItems[0].articleId == "art-1"

    def test_nested_id_resolves_via_shared_ref_map(self):

        order = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        assert order.orderItems[0].article.articleNumber == "A-001"
        assert order.orderItems[1].article.name == "Gadget"
        assert order.orderItems[0].unit.name == "Piece"

    def test_nested_custom_attribute_flatten(self):

        order = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        assert order.orderItems[0].lineNote == "handle with care"

    def test_nested_custom_attribute_round_trip(self):

        order = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        order.orderItems[0].lineNote = "fragile - rush"

        payload = order.to_payload()

        # Top-level untouched
        assert payload["id"] == "order-1"
        # Nested customAttributes rebuilt with edited value under the original typed-value field
        item_payload = payload["orderItems"][0]
        assert "lineNote" not in item_payload
        nested_cas = {ca["attributeDefinitionId"]: ca for ca in item_payload["customAttributes"]}
        assert nested_cas["ndef-1"]["stringValue"] == "fragile - rush"
        # Untouched second item retained.
        assert payload["orderItems"][1]["articleId"] == "art-2"
        # Payload should be plain dicts, not WeclappEntity, all the way down.
        assert type(payload["orderItems"][0]) is dict
        assert type(payload["orderItems"][0]["customAttributes"][0]) is dict

    def test_top_level_dict_field_is_wrapped(self):

        order = WeclappEntity.from_row(self._order_row())
        assert isinstance(order.recordAddress, WeclappEntity)
        assert order.recordAddress.street == "Main 1"

    def test_identity_stable_for_nested_entities(self):

        order = WeclappEntity.from_row(self._order_row())
        assert order.orderItems[0] is order.orderItems[0]
        assert order.recordAddress is order.recordAddress

    def test_mixed_list_wraps_dicts_only(self):

        row = {
            "id": "x",
            "tags": ["a", "b", "c"],
            "entries": [{"id": "1"}, "scalar", {"id": "2"}, 42],
        }
        entity = WeclappEntity.from_row(row)
        assert entity.tags == ["a", "b", "c"]
        assert isinstance(entity.entries[0], WeclappEntity)
        assert entity.entries[1] == "scalar"
        assert isinstance(entity.entries[2], WeclappEntity)
        assert entity.entries[3] == 42

    def test_dict_method_name_collision_falls_back_to_bracket_access(self):
        """Field names that collide with dict methods (items, keys, values, get,
        pop, update, ...) are only reachable via bracket access; attribute
        access returns the bound method. This is an inherent property of
        subclassing dict and applies at every nesting level."""

        row = {"id": "x", "items": [{"id": "1"}]}
        entity = WeclappEntity.from_row(row)
        # Bracket access returns the wrapped list of entities.
        assert isinstance(entity["items"][0], WeclappEntity)
        # Attribute access still resolves to the dict.items method.
        assert callable(entity.items)

    def test_custom_attributes_inner_items_remain_plain(self):
        """The raw customAttributes list itself is not wrapped — its dicts are metadata."""

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
        assert type(ca_item) is dict
        assert not isinstance(ca_item, WeclappEntity)

    def test_from_row_is_idempotent(self):

        first = WeclappEntity.from_row(self._order_row(), referenced_entities=self._ref_map())
        second = WeclappEntity.from_row(first)
        assert first is second

    def test_depth_guard(self):
        """Pathologically deep nesting raises a clear error rather than recursing forever."""

        # Build a deeply nested chain via repeated dict-valued field.
        deep: Any = {"id": "leaf"}
        for _ in range(WeclappEntity._MAX_WRAP_DEPTH + 5):
            deep = {"id": "n", "child": deep}
        with pytest.raises(ValueError, match="depth"):
            WeclappEntity.from_row(deep)

    def test_input_row_not_mutated(self):
        """Wrapping must not mutate the user's input row."""

        row = self._order_row()
        original_items = row["orderItems"]
        original_first_item = original_items[0]

        WeclappEntity.from_row(row, referenced_entities=self._ref_map())

        # Input list and its inner dicts remain plain dicts; identity preserved.
        assert row["orderItems"] is original_items
        assert row["orderItems"][0] is original_first_item
        assert type(row["orderItems"][0]) is dict
