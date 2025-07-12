import math
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_WORKERS = 10

class WeclappAPIError(Exception):
    """Custom exception for Weclapp API errors."""
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


@dataclass
class WeclappResponse:
    """Class to represent a structured response from the Weclapp API.

    This class handles the response structure when using additionalProperties
    and referencedEntities parameters in API requests.

    Attributes:
        result: The main result data from the API response.
        additional_properties: Optional dictionary containing additional properties if requested.
        referenced_entities: Optional dictionary containing referenced entities if requested.
        raw_response: The complete raw response from the API.
    """
    result: Union[List[Dict[str, Any]], Dict[str, Any]]
    additional_properties: Optional[Dict[str, Any]] = None
    referenced_entities: Optional[Dict[str, Any]] = None
    raw_response: Dict[str, Any] = None

    @classmethod
    def from_api_response(cls, response_data: Dict[str, Any]) -> 'WeclappResponse':
        """Create a WeclappResponse instance from an API response dictionary.

        Args:
            response_data: The raw API response dictionary.

        Returns:
            A WeclappResponse instance with parsed data.
        """
        result = response_data.get('result', [])
        additional_properties = response_data.get('additionalProperties')

        # Process referenced entities to convert from list to dictionary by ID
        raw_referenced_entities = response_data.get('referencedEntities')
        referenced_entities = None

        if raw_referenced_entities:
            referenced_entities = {}
            for entity_type, entities_list in raw_referenced_entities.items():
                referenced_entities[entity_type] = {}
                for entity in entities_list:
                    if 'id' in entity:
                        referenced_entities[entity_type][entity['id']] = entity

        return cls(
            result=result,
            additional_properties=additional_properties,
            referenced_entities=referenced_entities,
            raw_response=response_data
        )


class Weclapp:
    """
    Client for interacting with the Weclapp API.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        pool_connections: int = 100,
        pool_maxsize: int = 100
    ) -> None:
        """
        Initialize the Weclapp client.

        :param base_url: Base URL for the API, e.g. 'https://myorg.weclapp.com/webapp/api/v1/'.
        :param api_key: Authentication token / API key for the Weclapp instance.
        :param pool_connections: Total number of connection pools to maintain (default=100).
        :param pool_maxsize: Maximum number of connections per pool (default=100).
        """
        self.base_url = base_url.rstrip('/') + '/'
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "AuthenticationToken": api_key
        })

        # Configure HTTP retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PUT", "DELETE"]
        )

        # Create an adapter with bigger pool size
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
        )

        # Mount the adapter
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _check_response(self, response):
        """Check if the response is valid and raise an exception if not.

        :param response: Response object from requests.
        :raises WeclappAPIError: if the request fails or returns non-2xx status.
        """
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_message = str(e)
            try:
                error_data = response.json()
                if isinstance(error_data, dict) and 'error' in error_data:
                    error_message = f"{error_message} - {error_data['error']}"
            except (ValueError, KeyError):
                pass
            raise WeclappAPIError(error_message, response=response) from e

    def _send_request(self, method: str, url: str, **kwargs) -> Union[Dict[str, Any], bytes]:
        """
        Send an HTTP request and return parsed content.

        - If status code is 204 or body is empty, returns {}.
        - If Content-Type indicates JSON, returns the JSON as a dict.
        - If Content-Type indicates PDF or binary, returns {'content': <bytes>, 'filename': <str>, 'content_type': <str>}.
        - Otherwise, attempts to parse JSON; if that fails, returns text content.

        :param method: HTTP method (GET, POST, etc.).
        :param url: Full URL for the request.
        :param kwargs: Additional request parameters (headers, json=data, params, etc.).
        :return: Dict or binary dict structure (for files).
        :raises WeclappAPIError: if the request fails or returns non-2xx status.
        """
        try:
            response = self.session.request(method, url, **kwargs)
            self._check_response(response)

            # If no content or 204 No Content, return an empty dict
            if response.status_code == 204 or not response.content.strip():
                return {}

            content_type = response.headers.get("Content-Type", "")

            # Handle JSON content
            if "application/json" in content_type:
                return response.json()

            # Handle PDF or other binary downloads
            if any(ct in content_type for ct in ("application/pdf", "application/octet-stream", "binary")):
                return {
                    "content": response.content,
                    "content_type": content_type
                }

            # Attempt JSON parse if not purely recognized, otherwise return text
            try:
                return response.json()
            except ValueError:
                return {"content": response.text, "content_type": content_type}

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP {method} request failed for {url}: {e}")
            # Use response.text if available for error details
            error_detail = ""
            if 'response' in locals():
                error_detail = response.text
            raise WeclappAPIError(
                f"HTTP {method} request failed for {url}: {e}. Details: {error_detail}"
            ) from e

    def get(
        self,
        endpoint: str,
        id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        return_weclapp_response: bool = False
    ) -> Union[List[Any], Dict[str, Any], WeclappResponse]:
        """
        Perform a GET request. If an id is provided, fetch a single record using the
        URL pattern 'endpoint/id/{id}'. Otherwise, fetch records as a list from the endpoint.

        :param endpoint: API endpoint.
        :param id: Optional identifier to fetch a single record.
        :param params: Query parameters. Use this to add 'additionalProperties' and 'includeReferencedEntities' parameters directly.
        :param return_weclapp_response: If True, returns a WeclappResponse object instead of just the result.
        :return: A single record as a dict if id is provided, or a list of records otherwise.
                 If return_weclapp_response is True, returns a WeclappResponse object.
        :raises WeclappAPIError: on request failure.
        """
        params = params.copy() if params is not None else {}

        # Note: Users should add additionalProperties and includeReferencedEntities directly to params

        if id is not None:
            new_endpoint = f"{endpoint}/id/{id}"
            url = urljoin(self.base_url, new_endpoint)
            logger.debug(f"GET single record from {url} with params {params}")
            response_data = self._send_request("GET", url, params=params)
        else:
            url = urljoin(self.base_url, endpoint)
            logger.debug(f"GET {url} with params {params}")
            response_data = self._send_request("GET", url, params=params)

        # Return WeclappResponse object if requested
        if return_weclapp_response:
            return WeclappResponse.from_api_response(response_data)

        # Otherwise return just the result for backward compatibility
        if id is not None:
            return response_data
        else:
            return response_data.get('result', [])

    def get_all(
        self,
        entity: str,
        params: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        threaded: bool = False,
        max_workers: int = DEFAULT_MAX_WORKERS,
        return_weclapp_response: bool = False
    ) -> Union[List[Any], WeclappResponse]:
        """
        Retrieve all records for the given entity with automatic pagination.

        :param entity: Entity name, e.g. 'salesOrder'.
        :param params: Query parameters. Use this to add 'additionalProperties' and 'includeReferencedEntities' parameters directly.
        :param limit: Limit total records returned.
        :param threaded: Fetch pages in parallel if True.
        :param max_workers: Maximum parallel threads (default is 10).
        :param return_weclapp_response: If True, returns a WeclappResponse object instead of just the result.
        :return: List of records, or a WeclappResponse object if return_weclapp_response is True.
        :raises WeclappAPIError: on request failure.
        """
        params = params.copy() if params is not None else {}
        results: List[Any] = []
        all_response_data = {}

        # Note: Users should add additionalProperties and includeReferencedEntities directly to params

        if not threaded:
            # Sequential pagination.
            params['page'] = 1
            params['pageSize'] = limit if (limit is not None and limit < DEFAULT_PAGE_SIZE) else DEFAULT_PAGE_SIZE

            # Initialize response data containers
            all_additional_properties = {}
            all_referenced_entities = {}

            while True:
                url = urljoin(self.base_url, entity)
                logger.info(f"Fetching page {params['page']} for {entity}")
                logger.debug(f"GET {url} with params {params}")
                data = self._send_request("GET", url, params=params)
                current_page = data.get('result', [])
                results.extend(current_page)

                # Collect additional properties and referenced entities if present
                if 'additionalProperties' in data and data['additionalProperties']:
                    # For additionalProperties, we need to extend each property array
                    # as there should be one entry per record
                    for prop_name, prop_values in data['additionalProperties'].items():
                        if prop_name not in all_additional_properties:
                            all_additional_properties[prop_name] = []
                        all_additional_properties[prop_name].extend(prop_values)

                if 'referencedEntities' in data and data['referencedEntities']:
                    # For referencedEntities, we can use update as they are likely redundant
                    all_referenced_entities.update(data['referencedEntities'])

                if len(current_page) < params['pageSize'] or (limit is not None and len(results) >= limit):
                    break
                params['page'] += 1

            # Apply limit if specified
            if limit is not None:
                results = results[:limit]

            # Prepare the complete response data
            all_response_data = {
                'result': results
            }

            if all_additional_properties:
                all_response_data['additionalProperties'] = all_additional_properties

            if all_referenced_entities:
                all_response_data['referencedEntities'] = all_referenced_entities

            # Return WeclappResponse object if requested, otherwise just the results
            if return_weclapp_response:
                return WeclappResponse.from_api_response(all_response_data)
            else:
                return results

        else:
            # Parallel pagination.
            count_endpoint = f"{entity}/count"
            logger.info(f"Fetching total count for {entity} with params {params}")
            # Special handling for count endpoint which returns an integer directly
            url = urljoin(self.base_url, count_endpoint)
            logger.debug(f"GET {url} with params {params}")
            response = self.session.request("GET", url, params=params)
            self._check_response(response)
            total_count = response.json().get('result', 0) if response.status_code == 200 else 0

            if total_count == 0:
                logger.info(f"No records found for entity '{entity}'")
                return results

            page_size = limit if (limit is not None and limit < DEFAULT_PAGE_SIZE) else DEFAULT_PAGE_SIZE
            total_for_pages = total_count if (limit is None or limit > total_count) else limit
            total_pages = math.ceil(total_for_pages / page_size)

            logger.info(
                f"Total {total_count} records for {entity}, fetching up to {total_for_pages} "
                f"records across {total_pages} pages in parallel."
            )

            # Initialize response data containers for threaded mode
            all_additional_properties = {}
            all_referenced_entities = {}

            def fetch_page(page_number: int) -> Dict[str, Any]:
                # Fetch a single page and return the full response data.
                page_params = params.copy()
                page_params['page'] = page_number
                page_params['pageSize'] = page_size
                url = urljoin(self.base_url, entity)
                logger.info(f"[Threaded] Fetching page {page_number} of {total_pages} for {entity}")
                logger.debug(f"GET {url} with params {page_params}")
                data = self._send_request("GET", url, params=page_params)
                return data

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_page = {executor.submit(fetch_page, page): page for page in range(1, total_pages + 1)}
                for future in as_completed(future_to_page):
                    page_number = future_to_page[future]
                    try:
                        page_data = future.result()
                        page_results = page_data.get('result', [])
                        results.extend(page_results)

                        # Collect additional properties and referenced entities if present
                        if 'additionalProperties' in page_data and page_data['additionalProperties']:
                            # For additionalProperties, we need to extend each property array
                            # as there should be one entry per record
                            for prop_name, prop_values in page_data['additionalProperties'].items():
                                if prop_name not in all_additional_properties:
                                    all_additional_properties[prop_name] = []
                                all_additional_properties[prop_name].extend(prop_values)

                        if 'referencedEntities' in page_data and page_data['referencedEntities']:
                            # For referencedEntities, we can use update as they are likely redundant
                            all_referenced_entities.update(page_data['referencedEntities'])

                    except Exception as e:
                        logger.error(f"Error fetching page {page_number} for {entity}: {e}")
                    else:
                        logger.info(f"[Threaded] Completed page {page_number}/{total_pages} for {entity}")

            # Apply limit if specified
            if limit is not None:
                results = results[:limit]

            # Prepare the complete response data
            all_response_data = {
                'result': results
            }

            if all_additional_properties:
                all_response_data['additionalProperties'] = all_additional_properties

            if all_referenced_entities:
                all_response_data['referencedEntities'] = all_referenced_entities

            # Return WeclappResponse object if requested, otherwise just the results
            if return_weclapp_response:
                return WeclappResponse.from_api_response(all_response_data)
            else:
                return results

    def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform a POST request to the given endpoint.

        :param endpoint: API endpoint.
        :param data: Data to post.
        :return: JSON response.
        :raises WeclappAPIError: on request failure.
        """
        url = urljoin(self.base_url, endpoint)
        logger.debug(f"POST {url} - Data: {data}")
        return self._send_request("POST", url, json=data)

    def put(self, endpoint: str, id: str, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Perform a PUT request to the given endpoint.

        :param endpoint: API endpoint.
        :param data: Data to put.
        :param params: Query parameters.
        :return: JSON response.
        :raises WeclappAPIError: on request failure.
        """
        params = params.copy() if params is not None else {}
        params.setdefault("ignoreMissingProperties", True)
        url = urljoin(self.base_url, f"{endpoint}/id/{id}")
        logger.debug(f"PUT {url} - Data: {data} - Params: {params}")
        return self._send_request("PUT", url, json=data, params=params)

    def delete(
        self,
        endpoint: str,
        id: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform a DELETE request to delete a record.

        Since the DELETE endpoint returns a 204 No Content response, this method
        returns an empty dict when deletion is successful.

        :param endpoint: API endpoint.
        :param id: The identifier of the record to delete.
        :param params: Query parameters (e.g., dryRun).
        :return: An empty dict.
        :raises WeclappAPIError: on request failure.
        """
        params = params.copy() if params is not None else {}
        new_endpoint = f"{endpoint}/id/{id}"
        url = urljoin(self.base_url, new_endpoint)
        logger.debug(f"DELETE {url} with params {params}")
        return self._send_request("DELETE", url, params=params)

    def call_method(
        self,
        entity: str,
        action: str,
        entity_id: str = None,
        method: str = "GET",
        data: dict = None,
        params: dict = None
    ) -> Dict[str, Any]:
        """
        Calls any API method dynamically by constructing the URL from the given entity, action, and (optional) ID.

        :param entity: The entity name (e.g., 'salesInvoice' or 'salesOrder').
        :param action: The action/method to perform (e.g., 'downloadLatestSalesInvoicePdf' or 'createPrepaymentFinalInvoice').
        :param entity_id: (Optional) ID of the entity if needed.
        :param method: HTTP method ('GET' or 'POST' supported).
        :param data: (Optional) JSON payload for POST requests.
        :param params: (Optional) Query parameters for GET requests.
        :return: JSON response (dict) or empty dict for 204, or downloaded file content if PDF/binary.
        """
        path = f"{entity}/id/{entity_id}/{action}" if entity_id else f"{entity}/{action}"
        url = urljoin(self.base_url, path)

        method = method.upper()
        if method not in ("GET", "POST"):
            raise ValueError("Only GET and POST methods are supported by call_method().")

        # Reuse the unified request approach
        return self._send_request(method, url, json=data, params=params)