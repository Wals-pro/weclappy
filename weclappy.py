"""
A Python client for the Weclapp API.
"""

import math
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Module-level constants
DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_WORKERS = 10

# Module-level logger
logger = logging.getLogger(__name__)


class WeclappAPIError(Exception):
    """Custom exception for Weclapp API errors."""
    pass


class Weclapp:
    """
    Client for interacting with the Weclapp API.
    """

    base_url: str
    session: requests.Session

    def __init__(self, base_url: str, api_key: str) -> None:
        """
        Initialize the Weclapp client.

        :param base_url: Base URL for the API.
        :param api_key: Authentication token.
        """
        self.base_url = base_url.rstrip('/') + '/'
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "AuthenticationToken": api_key
        })

        # Configure HTTP retry strategy.
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PUT", "DELETE"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _send_request(self, method: str, url: str, **kwargs: Any) -> Dict[str, Any]:
        """
        Send an HTTP request and return the JSON response.

        If the response status code is 204 or no content is present, return an empty dict.

        :param method: HTTP method.
        :param url: URL for the request.
        :param kwargs: Additional request parameters.
        :return: JSON response as a dict, or {} for 204 responses.
        :raises WeclappAPIError: on request failure.
        """
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            # Return {} if there is no content (204 No Content) or empty body
            if response.status_code == 204 or not response.content.strip():
                return {}
            else:
                return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP {method} request failed for {url}: {e}")
            raise WeclappAPIError(f"HTTP {method} request failed for {url}: {e}. Details: {response.text}") from e

    def get(
        self,
        endpoint: str,
        id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Union[List[Any], Dict[str, Any]]:
        """
        Perform a GET request. If an id is provided, fetch a single record using the
        URL pattern 'endpoint/id/{id}'. Otherwise, fetch records as a list from the endpoint.

        :param endpoint: API endpoint.
        :param id: Optional identifier to fetch a single record.
        :param params: Query parameters.
        :return: A single record as a dict if id is provided, or a list of records otherwise.
        :raises WeclappAPIError: on request failure.
        """
        if id is not None:
            new_endpoint = f"{endpoint}/id/{id}"
            url = urljoin(self.base_url, new_endpoint)
            logger.debug(f"GET single record from {url} with params {params}")
            return self._send_request("GET", url, params=params)
        else:
            url = urljoin(self.base_url, endpoint)
            logger.debug(f"GET {url} with params {params}")
            data = self._send_request("GET", url, params=params)
            return data.get('result', [])

    def get_all(
        self,
        entity: str,
        params: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        threaded: bool = False,
        max_workers: int = DEFAULT_MAX_WORKERS
    ) -> List[Any]:
        """
        Retrieve all records for the given entity with automatic pagination.

        :param entity: Entity name, e.g. 'salesOrder'.
        :param params: Query parameters.
        :param limit: Limit total records returned.
        :param threaded: Fetch pages in parallel if True.
        :param max_workers: Maximum parallel threads (default is 10).
        :return: List of records.
        :raises WeclappAPIError: on request failure.
        """
        params = params.copy() if params is not None else {}
        results: List[Any] = []

        if not threaded:
            # Sequential pagination.
            params['page'] = 1
            params['pageSize'] = limit if (limit is not None and limit < DEFAULT_PAGE_SIZE) else DEFAULT_PAGE_SIZE

            while True:
                url = urljoin(self.base_url, entity)
                logger.info(f"Fetching page {params['page']} for {entity}")
                logger.debug(f"GET {url} with params {params}")
                data = self._send_request("GET", url, params=params)
                current_page = data.get('result', [])
                results.extend(current_page)

                if len(current_page) < params['pageSize'] or (limit is not None and len(results) >= limit):
                    break
                params['page'] += 1

            return results[:limit] if limit is not None else results

        else:
            # Parallel pagination.
            count_endpoint = f"{entity}/count"
            logger.info(f"Fetching total count for {entity} with params {params}")
            total_count_data = self.get(count_endpoint, params=params)
            total_count = total_count_data if isinstance(total_count_data, int) else 0

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

            def fetch_page(page_number: int) -> List[Any]:
                # Fetch a single page.
                page_params = params.copy()
                page_params['page'] = page_number
                page_params['pageSize'] = page_size
                url = urljoin(self.base_url, entity)
                logger.info(f"[Threaded] Fetching page {page_number} of {total_pages} for {entity}")
                logger.debug(f"GET {url} with params {page_params}")
                data = self._send_request("GET", url, params=page_params)
                return data.get('result', [])

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_page = {executor.submit(fetch_page, page): page for page in range(1, total_pages + 1)}
                for future in as_completed(future_to_page):
                    page_number = future_to_page[future]
                    try:
                        page_results = future.result()
                        results.extend(page_results)
                    except Exception as e:
                        logger.error(f"Error fetching page {page_number} for {entity}: {e}")
                    else:
                        logger.info(f"[Threaded] Completed page {page_number}/{total_pages} for {entity}")

            return results[:limit] if limit is not None else results

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

    def put(self, endpoint: str, data: Dict[str, Any], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        url = urljoin(self.base_url, endpoint)
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