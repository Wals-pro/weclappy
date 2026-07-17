import json
import math
import logging
import os
import random
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple, Union, overload
from urllib.parse import urljoin, urlparse, urlsplit

import requests
from requests.adapters import HTTPAdapter

__all__ = [
    "Weclapp",
    "WeclappAPIError",
    "WeclappEntity",
    "WeclappResponse",
    "MIME_TYPES",
    "infer_content_type",
]

logger = logging.getLogger(__name__)

# MIME type mapping from file extensions
MIME_TYPES: Dict[str, str] = {
    '.pdf': 'application/pdf',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
    '.bmp': 'image/bmp',
    '.tiff': 'image/tiff',
    '.tif': 'image/tiff',
    '.ico': 'image/x-icon',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.csv': 'text/csv',
    '.txt': 'text/plain',
    '.xml': 'application/xml',
    '.json': 'application/json',
    '.zip': 'application/zip',
    '.gz': 'application/gzip',
    '.tar': 'application/x-tar',
    '.rar': 'application/vnd.rar',
    '.7z': 'application/x-7z-compressed',
    '.html': 'text/html',
    '.htm': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.mp3': 'audio/mpeg',
    '.mp4': 'video/mp4',
    '.wav': 'audio/wav',
    '.avi': 'video/x-msvideo',
    '.mov': 'video/quicktime',
    '.eml': 'message/rfc822',
    '.msg': 'application/vnd.ms-outlook',
}


def infer_content_type(filename: Optional[str]) -> Optional[str]:
    """Infer MIME type from filename extension.

    Args:
        filename: The filename to infer content type from.

    Returns:
        The inferred MIME type, or None if the extension is not recognized.
    """
    if not filename:
        return None
    ext = os.path.splitext(filename)[1].lower()
    return MIME_TYPES.get(ext)

DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_WORKERS = 10
DEFAULT_REQUEST_TIMEOUT = 120  # seconds; weclapp may queue requests up to ~30s before 429
DEFAULT_WAIT_TIMEOUT_MS = 30_000
DEFAULT_API_REQUEST_TIMEOUT_MS = 120_000
DEFAULT_MAX_RETRIES = 3
DEFAULT_PROBLEM_RETRIES = 1
DEFAULT_BACKOFF_FACTOR = 0.3  # exponential backoff between retries (seconds)
SLOW_REQUEST_THRESHOLD_MS = 2000
MAX_ERROR_MESSAGE_BODY_CHARS = 4000
SAFE_RETRY_METHODS = frozenset({"HEAD", "GET", "OPTIONS"})
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _problem_type_suffix(value: Optional[str]) -> str:
    """Return the normalized final segment of a weclapp problem type."""
    if not value:
        return ""
    normalized = str(value).lower().rstrip("/")
    return normalized.rsplit("/", 1)[-1]


class _WeclappSession(requests.Session):
    """Session that never forwards AuthenticationToken across origins."""

    def rebuild_auth(self, prepared_request, response) -> None:
        super().rebuild_auth(prepared_request, response)
        previous = urlsplit(response.request.url)
        current = urlsplit(prepared_request.url)
        if (
            previous.scheme.lower(),
            previous.netloc.lower(),
        ) != (
            current.scheme.lower(),
            current.netloc.lower(),
        ):
            prepared_request.headers.pop("AuthenticationToken", None)


class _AdaptiveReadController:
    """Small, client-wide feedback controller for concurrent safe reads."""

    def __init__(self, ceiling: int = DEFAULT_MAX_WORKERS) -> None:
        self.ceiling = ceiling
        self._target = min(2, ceiling)
        self._active = 0
        self._cooldown_until = 0.0
        self._closed = False
        self._condition = threading.Condition()

    @property
    def target(self) -> int:
        with self._condition:
            return self._target

    def acquire(self) -> bool:
        """Wait for a read permit and return whether the window was saturated."""
        with self._condition:
            while True:
                if self._closed:
                    raise RuntimeError("weclapp read controller is closed")
                if self._cooldown_until:
                    now = time.monotonic()
                    if now < self._cooldown_until:
                        self._condition.wait(self._cooldown_until - now)
                        continue
                if self._active < self._target:
                    saturated = self._active >= max(1, self._target - 1)
                    self._active += 1
                    return saturated
                self._condition.wait()

    def release(self) -> None:
        with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    @staticmethod
    def _wait_ms(response) -> Optional[float]:
        value = response.headers.get("X-Weclapp-Wait-Ms")
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) and parsed >= 0 else None

    def observe(
        self,
        response,
        retry_delay: Optional[float] = None,
        saturated: bool = False,
    ) -> None:
        """Apply queue/load feedback from one physical response attempt."""
        wait_ms = self._wait_ms(response)
        reasons = {
            item.strip().lower()
            for item in str(response.headers.get("X-Weclapp-Wait-Reason", "")).split(",")
            if item.strip()
        }
        status = getattr(response, "status_code", None)
        with self._condition:
            if status == 429:
                self._target = 1
                delay = retry_delay if retry_delay is not None else 0.0
                self._cooldown_until = max(
                    self._cooldown_until,
                    time.monotonic() + max(0.0, delay),
                )
            elif "load" in reasons or (wait_ms is not None and wait_ms >= SLOW_REQUEST_THRESHOLD_MS):
                self._target = max(1, math.ceil(self._target / 2))
            elif "concurrency" in reasons or (wait_ms is not None and wait_ms >= 250):
                self._target = max(1, self._target - 1)
            elif status is not None and 200 <= status < 300:
                # Only grow after a request that was part of a full window.
                # The caller marks this through the lightweight response flag.
                if saturated:
                    self._target = min(self.ceiling, self._target + 1)
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class WeclappAPIError(Exception):
    """Custom exception for Weclapp API errors.

    Provides structured access to error details from the Weclapp API response.

    Attributes:
        response: The raw requests.Response object (if available).
        response_text: The raw response body text (if available).
        status_code: The HTTP status code (if available).
        error: The error message from the API response.
        detail: Detailed error description from the API.
        title: Error title from the API.
        error_type: Error type identifier from the API.
        validation_errors: List of validation error details.
        messages: List of additional error messages with severity.
        url: The request URL that caused the error.
    """

    # Identifier for optimistic lock errors in Weclapp
    OPTIMISTIC_LOCK_IDENTIFIER = "Optimistic lock error"

    def __init__(self, message, response=None, response_text=None):
        self.response = response
        self.response_text = response_text if response_text is not None else (
            response.text if response is not None else None
        )
        self.status_code = response.status_code if response is not None else None
        self.url = str(response.url) if response is not None else None

        # Initialize structured error fields
        self.error = None
        self.detail = None
        self.title = None
        self.error_type = None
        self.validation_errors = []
        self.messages = []

        # Parse JSON error response if available
        self._parse_error_response()

        super().__init__(message)

    def _parse_error_response(self):
        """Parse the JSON error response and populate structured fields."""
        if not self.response_text:
            return

        try:
            error_data = json.loads(self.response_text)
            if not isinstance(error_data, dict):
                return

            self.error = error_data.get('error')
            self.detail = error_data.get('detail')
            self.title = error_data.get('title')
            self.error_type = error_data.get('type')
            validation_errors = error_data.get('validationErrors') or []
            messages = error_data.get('messages') or []
            self.validation_errors = (
                validation_errors if isinstance(validation_errors, list) else []
            )
            self.messages = messages if isinstance(messages, list) else []

        except (json.JSONDecodeError, ValueError):
            # Not a JSON response, leave fields as None/empty
            pass

    @property
    def is_optimistic_lock(self) -> bool:
        """Check if this error is an optimistic lock (version conflict) error.

        Returns:
            True if this is an optimistic lock error, False otherwise.
        """
        if _problem_type_suffix(self.error_type) == "optimistic_lock":
            return True
        if self.detail and self.OPTIMISTIC_LOCK_IDENTIFIER.lower() in str(self.detail).lower():
            return True
        if self.error and self.OPTIMISTIC_LOCK_IDENTIFIER.lower() in str(self.error).lower():
            return True
        return False

    @property
    def is_not_found(self) -> bool:
        """Check if this error is a 404 Not Found error.

        Returns:
            True if this is a not found error, False otherwise.
        """
        return self.status_code == 404

    @property
    def is_validation_error(self) -> bool:
        """Check if this error contains validation errors.

        Returns:
            True if validation errors are present, False otherwise.
        """
        return (
            _problem_type_suffix(self.error_type) == "validation"
            or bool(self.validation_errors)
        )

    @property
    def is_rate_limited(self) -> bool:
        """Check if this error is a rate limit (429) error.

        Returns:
            True if this is a rate limit error, False otherwise.
        """
        return self.status_code == 429

    @property
    def is_request_timeout(self) -> bool:
        """Whether weclapp classified the response as a transient request timeout."""
        return _problem_type_suffix(self.error_type) == "request_timeout"

    @property
    def is_persistence_error(self) -> bool:
        """Whether weclapp classified the response as a persistence conflict."""
        return _problem_type_suffix(self.error_type) == "persistence"

    @property
    def is_retryable(self) -> bool:
        """Whether the response is transient in principle.

        Callers must still consider whether repeating the HTTP operation is safe.
        """
        return (
            self.status_code in TRANSIENT_STATUS_CODES
            or self.is_request_timeout
            or self.is_persistence_error
        )

    @property
    def retry_after(self) -> Optional[str]:
        """Return the raw Retry-After header, if the response supplied one."""
        return self._response_header("Retry-After")

    @property
    def wait_ms(self) -> Optional[str]:
        """Return weclapp's reported queue wait time in milliseconds."""
        return self._response_header("X-Weclapp-Wait-Ms")

    @property
    def wait_reason(self) -> Optional[str]:
        """Return weclapp's reported queue reason, if present."""
        return self._response_header("X-Weclapp-Wait-Reason")

    @property
    def correlation_id(self) -> Optional[str]:
        """Return a commonly used request/correlation identifier header."""
        for header in (
            "X-Correlation-ID",
            "X-Correlation-Id",
            "X-Request-ID",
            "X-Request-Id",
        ):
            value = self._response_header(header)
            if value:
                return value
        return None

    def _response_header(self, name: str) -> Optional[str]:
        if self.response is None:
            return None
        headers = getattr(self.response, "headers", None)
        if not headers or not hasattr(headers, "get"):
            return None
        value = headers.get(name)
        return str(value) if value is not None else None

    def get_validation_messages(self) -> List[str]:
        """Get a list of validation error messages.

        Returns:
            List of validation error message strings.
        """
        messages = []
        for error in self.validation_errors:
            if isinstance(error, dict):
                msg = error.get('message') or error.get('error') or str(error)
                messages.append(msg)
            else:
                messages.append(str(error))
        return messages

    def get_all_messages(self) -> List[str]:
        """Get all error messages including validation errors and additional messages.

        Returns:
            List of all error message strings.
        """
        all_messages = []

        if self.error:
            all_messages.append(self.error)
        if self.detail and self.detail != self.error:
            all_messages.append(self.detail)

        all_messages.extend(self.get_validation_messages())

        for msg in self.messages:
            if isinstance(msg, dict):
                text = msg.get('message', str(msg))
                severity = msg.get('severity', '')
                if severity:
                    all_messages.append(f"[{severity}] {text}")
                else:
                    all_messages.append(text)
            else:
                all_messages.append(str(msg))

        return all_messages


@dataclass
class WeclappResponse:
    """Class to represent a structured response from the Weclapp API.

    This class handles the response structure when using additionalProperties
    and referencedEntities parameters in API requests.

    Attributes:
        result: The main result data from the API response.
        additional_properties: Optional dictionary containing additional properties if requested.
        referenced_entities: Optional dictionary containing referenced entities if requested.
        raw_referenced_entities: Native referenced-entity lists exactly as returned
            by weclapp, including valid colon projections that omit ``id``.
        raw_response: The complete raw response from the API.
    """
    result: Union[List[Dict[str, Any]], Dict[str, Any]]
    additional_properties: Optional[Dict[str, Any]] = None
    referenced_entities: Optional[Dict[str, Any]] = None
    raw_response: Optional[Dict[str, Any]] = None

    @property
    def raw_referenced_entities(self) -> Optional[Dict[str, Any]]:
        """Return weclapp's native ``referencedEntities`` mapping.

        ``referenced_entities`` remains the backwards-compatible ID-indexed
        view used by lazy ``*Id`` resolution.  Colon projections are allowed
        to omit the referenced entity's ``id``; those entries cannot be
        indexed, but remain available through this raw view.
        """
        if not isinstance(self.raw_response, dict):
            return None
        value = self.raw_response.get('referencedEntities')
        return value if isinstance(value, dict) else None

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

        if isinstance(raw_referenced_entities, dict) and raw_referenced_entities:
            referenced_entities = {}
            for entity_type, entities_list in raw_referenced_entities.items():
                referenced_entities[entity_type] = {}
                if not isinstance(entities_list, list):
                    continue
                for entity in entities_list:
                    if isinstance(entity, dict) and entity.get('id') is not None:
                        referenced_entities[entity_type][entity['id']] = entity

        return cls(
            result=result,
            additional_properties=additional_properties,
            referenced_entities=referenced_entities,
            raw_response=response_data
        )


class WeclappEntity(dict):
    """A weclapp entity with attribute-style access.

    Wraps a single result row from a weclapp API response. Subclasses ``dict``
    so existing dict-style access (``entity['id']``, ``entity.get('foo')``)
    keeps working.

    Behavior on top of ``dict``:

    - ``customAttributes`` are flattened to top-level fields keyed by their
      resolved attribute-definition key. The original list remains under
      ``entity['customAttributes']``.
    - Per-row ``additionalProperties`` values are merged in at the top level.
    - ``*Id`` fields lazily resolve to the matching object from the response's
      ``referencedEntities`` map (e.g. ``entity.customer`` looks up the
      object referenced by ``entity['customerId']``).

    Mutability:

    - Only existing, writable flattened customAttribute fields are writable
      via attribute or item assignment. Reassigning them and then calling
      :meth:`to_payload` rebuilds the original ``customAttributes`` array with
      the new values. Definitions marked ``readOnly`` are rejected locally.
    - The flattened interface deliberately does not add customAttributes that
      are absent from the entity. Construct an explicit v2 ``customAttributes``
      item when adding one.
    - All other fields are read-only via attribute syntax (``entity.id = ...``
      raises ``AttributeError``). Item assignment on the underlying dict is
      not blocked, but is not a supported pattern.
    """

    _CUSTOM_ATTRIBUTE_VALUE_FIELDS = (
        'stringValue',
        'numberValue',
        'booleanValue',
        'dateValue',
        'entityId',
        'entityReferences',
        'selectedValueId',
        'selectedValues',
    )

    # ``customAttribute`` is a closed v2 schema. Legacy responses can contain
    # helper metadata such as ``internalName``; forwarding that metadata makes
    # an otherwise valid PUT fail with ``platform.unknown_property``.
    _CUSTOM_ATTRIBUTE_FIELDS = (
        'attributeDefinitionId',
    ) + _CUSTOM_ATTRIBUTE_VALUE_FIELDS

    _CUSTOM_ATTRIBUTE_NESTED_FIELDS = {
        'entityReferences': ('entityId', 'entityName'),
        'selectedValues': ('id',),
    }

    _CUSTOM_ATTRIBUTE_TYPE_FIELDS = {
        'BOOLEAN': 'booleanValue',
        'DATE': 'dateValue',
        'DECIMAL': 'numberValue',
        'INTEGER': 'numberValue',
        'ENTITY': 'entityId',
        'REFERENCE': 'entityReferences',
        'LIST': 'selectedValueId',
        'MULTISELECT_LIST': 'selectedValues',
        'LARGE_TEXT': 'stringValue',
        'STRING': 'stringValue',
        'URL': 'stringValue',
    }

    _MAX_WRAP_DEPTH = 64

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        object.__setattr__(self, '_custom_attr_index', {})
        object.__setattr__(self, '_referenced_entities', {})
        object.__setattr__(self, '_ref_cache', {})
        object.__setattr__(self, '_original_keys', set(self.keys()))
        object.__setattr__(self, '_additional_property_keys', set())
        object.__setattr__(self, '_attribute_definitions', {})
        object.__setattr__(self, '_defined_custom_attr_names', set())
        object.__setattr__(self, '_read_only_custom_attrs', set())
        object.__setattr__(self, '_read_only_custom_attr_positions', {})

    @classmethod
    def from_row(
        cls,
        row: Dict[str, Any],
        additional_properties_for_row: Optional[Dict[str, Any]] = None,
        referenced_entities: Optional[Dict[str, Dict[str, Any]]] = None,
        attribute_definitions: Optional[Dict[str, Dict[str, Any]]] = None,
        _depth: int = 0,
    ) -> 'WeclappEntity':
        """Build a WeclappEntity from a single result row.

        Nested dict and list-of-dict values are recursively wrapped as
        ``WeclappEntity`` so attribute access, customAttribute flattening, and
        ``*Id`` resolution work uniformly at every level.

        :param row: Raw entity dict from the API ``result`` list.
        :param additional_properties_for_row: Per-row slice of the response's
            ``additionalProperties`` (i.e. ``{prop_name: value_for_this_row}``).
        :param referenced_entities: Shared referenced-entities map produced by
            ``WeclappResponse.from_api_response`` (``{type: {id: entity_dict}}``).
        :param attribute_definitions: Map of ``attributeDefinitionId`` to the
            full definition dict (must contain ``attributeKey``). weclapp does
            not include ``internalName`` on entity-level customAttributes, so
            this map is used to derive flattened field names.
        """
        if isinstance(row, WeclappEntity):
            return row
        if _depth > cls._MAX_WRAP_DEPTH:
            raise ValueError(
                f"WeclappEntity wrap depth exceeded {cls._MAX_WRAP_DEPTH}; "
                "input row is too deeply nested or cyclic."
            )

        entity = cls(row)
        object.__setattr__(entity, '_original_keys', set(entity.keys()))

        if referenced_entities:
            object.__setattr__(entity, '_referenced_entities', referenced_entities)
        if attribute_definitions:
            object.__setattr__(entity, '_attribute_definitions', attribute_definitions)
            object.__setattr__(
                entity,
                '_defined_custom_attr_names',
                {
                    name
                    for definition in attribute_definitions.values()
                    if isinstance(definition, dict)
                    for name in (
                        definition.get('attributeKey')
                        or definition.get('internalName'),
                    )
                    if isinstance(name, str) and name
                },
            )

        custom_attributes = entity.get('customAttributes')
        if isinstance(custom_attributes, list):
            cls._flatten_custom_attributes(entity, custom_attributes, attribute_definitions)

        if additional_properties_for_row:
            cls._merge_additional_properties(entity, additional_properties_for_row)

        # Recursively wrap nested dict / list-of-dict values. The raw
        # customAttributes list is metadata (definitions + values), not entities,
        # so it stays untouched and is fully owned by the flatten/round-trip pass.
        for key in list(entity.keys()):
            if key == 'customAttributes':
                continue
            current = entity[key]
            wrapped = cls._wrap_nested_value(
                current, referenced_entities, attribute_definitions, _depth + 1
            )
            if wrapped is not current:
                dict.__setitem__(entity, key, wrapped)

        return entity

    @classmethod
    def _wrap_nested_value(
        cls,
        value: Any,
        referenced_entities: Optional[Dict[str, Dict[str, Any]]],
        attribute_definitions: Optional[Dict[str, Dict[str, Any]]],
        depth: int,
    ) -> Any:
        """Wrap dicts (and dicts inside lists) as ``WeclappEntity``; pass scalars through."""
        if isinstance(value, WeclappEntity):
            return value
        if isinstance(value, dict):
            if depth > cls._MAX_WRAP_DEPTH:
                raise ValueError(
                    f"WeclappEntity wrap depth exceeded {cls._MAX_WRAP_DEPTH}"
                )
            return cls.from_row(
                value,
                referenced_entities=referenced_entities,
                attribute_definitions=attribute_definitions,
                _depth=depth,
            )
        if isinstance(value, list):
            if depth > cls._MAX_WRAP_DEPTH:
                raise ValueError(
                    f"WeclappEntity wrap depth exceeded {cls._MAX_WRAP_DEPTH}"
                )
            return [
                cls._wrap_nested_value(item, referenced_entities, attribute_definitions, depth + 1)
                for item in value
            ]
        return value

    @classmethod
    def _flatten_custom_attributes(
        cls,
        entity: 'WeclappEntity',
        custom_attributes: List[Any],
        attribute_definitions: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        index = entity._custom_attr_index
        for position, item in enumerate(custom_attributes):
            if not isinstance(item, dict):
                continue
            attr_def_id = item.get('attributeDefinitionId')
            definition = (
                attribute_definitions.get(attr_def_id)
                if attr_def_id and attribute_definitions
                else None
            )
            is_read_only = bool(
                isinstance(definition, dict) and definition.get('readOnly') is True
            )
            if is_read_only:
                entity._read_only_custom_attr_positions[position] = cls._unwrap(item)
            # v2 definition metadata is authoritative; ``internalName`` only
            # exists on legacy response shapes and is a fallback when no
            # definition was available.
            name = (
                definition.get('attributeKey') or definition.get('internalName')
                if definition
                else None
            )
            if not name:
                name = item.get('internalName')
            if not name:
                logger.debug(
                    "customAttribute at position %d has no resolvable name; skipping flatten",
                    position,
                )
                continue
            value, value_field = cls._extract_custom_attribute_value(item, definition)
            if name in entity:
                logger.warning(
                    "customAttribute name '%s' collides with existing field; "
                    "built-in wins. Raw value remains under entity['customAttributes'].",
                    name,
                )
                continue
            # Keep flattened mutable containers independent from the raw
            # metadata list so in-place edits can be detected for read-only
            # definitions and folded back deterministically for writable ones.
            dict.__setitem__(entity, name, cls._unwrap(value))
            index[name] = (position, value_field, attr_def_id)
            if is_read_only:
                entity._read_only_custom_attrs.add(name)

    @classmethod
    def _extract_custom_attribute_value(
        cls,
        item: Dict[str, Any],
        definition: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, str]:
        # The definition is authoritative. Legacy payloads occasionally carry
        # several typed slots, so scanning for the first non-null value before
        # consulting ``attributeType`` can expose the wrong field.
        if definition:
            attribute_type = str(definition.get('attributeType') or '').upper()
            value_field = cls._CUSTOM_ATTRIBUTE_TYPE_FIELDS.get(attribute_type)
            if value_field:
                return item.get(value_field), value_field

        for field in cls._CUSTOM_ATTRIBUTE_VALUE_FIELDS:
            if field in item and item[field] is not None:
                return item[field], field

        # Legacy responses may expose just one typed field with a null value.
        present_fields = [
            field for field in cls._CUSTOM_ATTRIBUTE_VALUE_FIELDS if field in item
        ]
        if len(present_fields) == 1:
            return item.get(present_fields[0]), present_fields[0]
        return None, 'stringValue'

    @classmethod
    def _merge_additional_properties(
        cls, entity: 'WeclappEntity', additional_props: Dict[str, Any]
    ) -> None:
        ap_keys = entity._additional_property_keys
        for name, value in additional_props.items():
            if name in entity:
                logger.warning(
                    "additionalProperty '%s' collides with existing entity field; "
                    "built-in wins.",
                    name,
                )
                continue
            dict.__setitem__(entity, name, value)
            ap_keys.add(name)

    @property
    def additional_properties(self) -> Dict[str, Any]:
        """Return the actually merged additionalProperties as a plain copy.

        The convenience namespace is read-only and excludes response values
        that collided with built-in entity fields and therefore were not
        merged. Nested containers are copied so callers cannot mutate the
        entity through the returned mapping.
        """
        return {
            name: self._unwrap(value)
            for name, value in self.items()
            if name in self._additional_property_keys
        }

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        if name in self:
            return self[name]
        id_key = name + 'Id'
        if id_key in self:
            resolved = self._resolve_reference(name, self[id_key])
            if resolved is not None:
                return resolved
        raise AttributeError(name)

    def _resolve_reference(self, name: str, ref_id: Any):
        """Resolve a stripped ``*Id`` accessor against the shared ref map.

        Tries name-based buckets first (``customer`` / ``customers``); falls
        back to a flat id lookup across all buckets because weclapp uses
        unified types under different field names (e.g. ``customerId`` and
        ``invoiceRecipientId`` both resolve to the ``party`` bucket).
        """
        if ref_id is None:
            return None
        cache = self._ref_cache
        if name in cache:
            return cache[name]
        ref_map = self._referenced_entities or {}
        for type_key in (name, name + 's'):
            type_bucket = ref_map.get(type_key)
            if type_bucket and ref_id in type_bucket:
                wrapped = WeclappEntity.from_row(
                    type_bucket[ref_id],
                    referenced_entities=ref_map,
                    attribute_definitions=self._attribute_definitions,
                )
                cache[name] = wrapped
                return wrapped
        # weclapp ids are globally unique within a tenant; the bucket name
        # often differs from the field-name convention (customerId -> party).
        for bucket in ref_map.values():
            if ref_id in bucket:
                wrapped = WeclappEntity.from_row(
                    bucket[ref_id],
                    referenced_entities=ref_map,
                    attribute_definitions=self._attribute_definitions,
                )
                cache[name] = wrapped
                return wrapped
        return None

    def __setattr__(self, name, value):
        if name.startswith('_'):
            object.__setattr__(self, name, value)
            return
        index = getattr(self, '_custom_attr_index', None) or {}
        if name in index:
            self._set_custom_attribute_value(name, value)
            return
        if name not in self and name in self._defined_custom_attr_names:
            raise AttributeError(
                f"customAttribute '{name}' is defined but is not present on this "
                "entity. The flattened interface only updates existing "
                "customAttributes; add an explicit v2 customAttributes item "
                "to the payload instead."
            )
        raise AttributeError(
            f"WeclappEntity attribute '{name}' is read-only. "
            "Only flattened customAttribute fields are writable."
        )

    def __setitem__(self, key, value):
        """Apply the customAttribute write contract to normal dict assignment."""
        index = getattr(self, '_custom_attr_index', None) or {}
        if key in index:
            self._set_custom_attribute_value(key, value)
            return
        if (
            isinstance(key, str)
            and key not in self
            and key in getattr(self, '_defined_custom_attr_names', set())
        ):
            raise AttributeError(
                f"customAttribute '{key}' is defined but is not present on this "
                "entity. The flattened interface only updates existing "
                "customAttributes; add an explicit v2 customAttributes item "
                "to the payload instead."
            )
        dict.__setitem__(self, key, value)

    def _set_custom_attribute_value(self, name: str, value: Any) -> None:
        if name in self._read_only_custom_attrs:
            raise AttributeError(
                f"customAttribute '{name}' is read-only according to its "
                "customAttributeDefinition and cannot be changed."
            )
        dict.__setitem__(self, name, value)

    def to_payload(self) -> Dict[str, Any]:
        """Return a plain API payload, primarily for updating this entity.

        Normal entity fields are preserved, including response metadata such as
        ``id`` and ``version``.  A payload produced from a read entity is
        therefore not automatically a valid create payload; construct creates
        explicitly and omit read-only metadata.

        - Flattened customAttribute fields are folded back into the
          ``customAttributes`` array under the originally populated typed-value
          field, preserving any current edits — at every level of nesting.
        - Keys merged in from ``additionalProperties`` are dropped.
        - Cached resolved reference objects are not included.
        - Nested ``WeclappEntity`` values (in dict or list fields) are
          recursively unwrapped via their own ``to_payload``.
        """
        payload: Dict[str, Any] = {}
        flattened = set(self._custom_attr_index.keys())
        synthetic = self._additional_property_keys | flattened
        for key, value in self.items():
            if key in synthetic or key == 'customAttributes':
                continue
            payload[key] = self._unwrap(value)

        custom_attributes_src = self.get('customAttributes')
        if isinstance(custom_attributes_src, list):
            rebuilt = [
                self._sanitize_custom_attribute(item, position)
                for position, item in enumerate(custom_attributes_src)
            ]

            # Direct edits of the raw customAttributes list are unsupported,
            # but detect them for read-only definitions before a request leaves
            # the process. This also catches in-place list/dict mutations.
            for position, original in self._read_only_custom_attr_positions.items():
                original_sanitized = self._sanitize_custom_attribute(
                    original, position
                )
                if (
                    position >= len(rebuilt)
                    or rebuilt[position].get('attributeDefinitionId')
                    != original_sanitized.get('attributeDefinitionId')
                    or rebuilt[position] != original_sanitized
                ):
                    raise ValueError(
                        "customAttribute at position "
                        f"{position} is read-only according to its "
                        "customAttributeDefinition and cannot be removed, "
                        "replaced, moved, or changed."
                    )

            for name, (position, value_field, attr_def_id) in self._custom_attr_index.items():
                if not (0 <= position < len(rebuilt)):
                    raise ValueError(
                        f"customAttribute '{name}' was removed from its original "
                        "position. Edit the flattened field instead of changing "
                        "the raw customAttributes list."
                    )
                current_attr_def_id = rebuilt[position].get(
                    'attributeDefinitionId'
                )
                if (
                    attr_def_id is not None
                    and current_attr_def_id != attr_def_id
                ):
                    raise ValueError(
                        f"customAttribute '{name}' was moved or replaced in the "
                        "raw customAttributes list. Edit the flattened field "
                        "instead."
                    )
                if name in self._read_only_custom_attrs:
                    definition = self._attribute_definitions.get(attr_def_id)
                    original = self._read_only_custom_attr_positions.get(position, {})
                    original_value, _ = self._extract_custom_attribute_value(
                        original, definition
                    )
                    if self._unwrap(self.get(name)) != self._unwrap(original_value):
                        raise ValueError(
                            f"customAttribute '{name}' is read-only according to "
                            "its customAttributeDefinition and cannot be changed."
                        )
                    continue
                rebuilt[position][value_field] = self._unwrap(self.get(name))
                rebuilt[position] = self._sanitize_custom_attribute(
                    rebuilt[position], position
                )

            # Once attributeType is known, emit exactly its active typed slot.
            # This prevents stale legacy slots from creating an ambiguous wire
            # payload. Without a usable definition, preserve every allowed v2
            # field because the client cannot safely infer the active one.
            for position, item in enumerate(rebuilt):
                attr_def_id = item.get('attributeDefinitionId')
                definition = self._attribute_definitions.get(attr_def_id)
                attribute_type = str(
                    definition.get('attributeType') if definition else ''
                ).upper()
                value_field = self._CUSTOM_ATTRIBUTE_TYPE_FIELDS.get(attribute_type)
                if value_field:
                    normalized = {}
                    if 'attributeDefinitionId' in item:
                        normalized['attributeDefinitionId'] = item['attributeDefinitionId']
                    normalized[value_field] = item.get(value_field)
                    rebuilt[position] = normalized

            payload['customAttributes'] = rebuilt

        elif self._read_only_custom_attr_positions:
            raise ValueError(
                "customAttributes contains read-only definitions and cannot be "
                "removed or replaced with a non-list value."
            )

        return payload

    @classmethod
    def _sanitize_custom_attribute(
        cls, item: Any, position: int
    ) -> Dict[str, Any]:
        """Return one schema-exact v2 ``customAttribute`` payload item."""
        if not isinstance(item, dict):
            raise ValueError(
                f"customAttributes[{position}] must be an object, got "
                f"{type(item).__name__}."
            )

        sanitized: Dict[str, Any] = {}
        for field in cls._CUSTOM_ATTRIBUTE_FIELDS:
            if field not in item:
                continue
            value = cls._unwrap(item[field])
            nested_fields = cls._CUSTOM_ATTRIBUTE_NESTED_FIELDS.get(field)
            if nested_fields and value is not None:
                if not isinstance(value, list):
                    raise ValueError(
                        f"customAttributes[{position}].{field} must be a list or null."
                    )
                nested_values = []
                for nested_position, nested_item in enumerate(value):
                    if not isinstance(nested_item, dict):
                        raise ValueError(
                            f"customAttributes[{position}].{field}"
                            f"[{nested_position}] must be an object."
                        )
                    nested_values.append(
                        {
                            nested_field: cls._unwrap(nested_item[nested_field])
                            for nested_field in nested_fields
                            if nested_field in nested_item
                        }
                    )
                value = nested_values
            sanitized[field] = value
        return sanitized

    @classmethod
    def _unwrap(cls, value: Any) -> Any:
        """Recursively turn nested WeclappEntity values back into plain dicts."""
        if isinstance(value, WeclappEntity):
            return value.to_payload()
        if isinstance(value, list):
            return [cls._unwrap(item) for item in value]
        if isinstance(value, tuple):
            return [cls._unwrap(item) for item in value]
        if isinstance(value, dict):
            return {key: cls._unwrap(item) for key, item in value.items()}
        return value


class Weclapp:
    """
    Client for interacting with the Weclapp API.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        pool_connections: int = 100,
        pool_maxsize: int = 100,
        slow_threshold_ms: int = SLOW_REQUEST_THRESHOLD_MS,
        *,
        timeout: Union[int, float] = DEFAULT_REQUEST_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        problem_retries: int = DEFAULT_PROBLEM_RETRIES,
        wait_timeout_ms: Optional[int] = DEFAULT_WAIT_TIMEOUT_MS,
        request_timeout_ms: Optional[int] = DEFAULT_API_REQUEST_TIMEOUT_MS,
    ) -> None:
        """
        Initialize the Weclapp client.

        :param base_url: Base URL for the API, e.g. 'https://myorg.weclapp.com/webapp/api/v2/'.
        :param api_key: Authentication token / API key for the Weclapp instance.
        :param pool_connections: Total number of connection pools to maintain (default=100).
        :param pool_maxsize: Maximum number of connections per pool (default=100).
        :param slow_threshold_ms: Duration after which successful requests log as slow.
        :param timeout: Default client-side request timeout in seconds.
        :param max_retries: Automatic retry count for safe HTTP methods.
        :param backoff_factor: Exponential retry backoff factor.
        :param problem_retries: Additional retries for safe, transient weclapp problem types.
        :param wait_timeout_ms: Optional X-Weclapp-Wait-Timeout-Ms header value.
        :param request_timeout_ms: Optional X-Weclapp-Request-Timeout-Ms header value.
        """
        if not isinstance(base_url, str):
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        parsed_base = urlsplit(base_url)
        if parsed_base.scheme.lower() not in {"http", "https"} or not parsed_base.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed_base.query or parsed_base.fragment:
            raise ValueError("base_url must not contain a query string or fragment")
        if (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be greater than zero")
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if (
            not isinstance(problem_retries, int)
            or isinstance(problem_retries, bool)
            or problem_retries < 0
        ):
            raise ValueError("problem_retries must be a non-negative integer")
        if (
            not isinstance(backoff_factor, (int, float))
            or isinstance(backoff_factor, bool)
            or not math.isfinite(backoff_factor)
            or backoff_factor < 0
        ):
            raise ValueError("backoff_factor must be non-negative")
        for header_name, header_value in (
            ("wait_timeout_ms", wait_timeout_ms),
            ("request_timeout_ms", request_timeout_ms),
        ):
            if header_value is not None and (
                not isinstance(header_value, int)
                or isinstance(header_value, bool)
                or header_value <= 0
            ):
                raise ValueError(f"{header_name} must be a positive integer or None")

        self.base_url = base_url.rstrip('/') + '/'
        normalized_base = urlsplit(self.base_url)
        self._base_origin = (
            normalized_base.scheme.lower(),
            normalized_base.netloc.lower(),
        )
        self.slow_threshold_ms = slow_threshold_ms
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.problem_retries = problem_retries
        self._read_controller = _AdaptiveReadController()
        # Lazy cache: {attributeDefinitionId: definition_dict}. Populated on
        # first wrapped read so customAttribute flattening can resolve
        # internalName via attributeDefinition.attributeKey (weclapp does not
        # ship internalName on entity-level customAttributes).
        self._attribute_definitions_by_id: Optional[Dict[str, Dict[str, Any]]] = None
        self.session = _WeclappSession()
        default_headers = {
            "Content-Type": "application/json",
            "AuthenticationToken": api_key,
        }
        if wait_timeout_ms is not None:
            default_headers["X-Weclapp-Wait-Timeout-Ms"] = str(wait_timeout_ms)
        if request_timeout_ms is not None:
            default_headers["X-Weclapp-Request-Timeout-Ms"] = str(request_timeout_ms)
        self.session.headers.update(default_headers)

        # urllib3 retries happen below the requests API and some legacy
        # versions can replay an unsafe method for an "other" transport error.
        # Keep the adapter strictly retry-free.  _send_request owns the complete
        # retry policy, where the HTTP method is always visible and enforceable.
        adapter = HTTPAdapter(
            max_retries=0,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            pool_block=True,
        )

        # Mount the adapter
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def close(self) -> None:
        """Close pooled HTTP connections owned by this client."""
        self._read_controller.close()
        self.session.close()

    def __enter__(self) -> 'Weclapp':
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _build_url(self, endpoint: str) -> str:
        """Build a same-origin API URL from a relative endpoint path."""
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint must be a non-empty relative path")
        parsed_endpoint = urlsplit(endpoint)
        if parsed_endpoint.scheme or parsed_endpoint.netloc:
            raise ValueError("endpoint must be relative to base_url")
        if parsed_endpoint.fragment:
            raise ValueError("endpoint must not contain a URL fragment")
        if ".." in parsed_endpoint.path.split('/'):
            raise ValueError("endpoint must not traverse outside base_url")
        relative_endpoint = endpoint.lstrip('/')
        url = urljoin(self.base_url, relative_endpoint)
        parsed_url = urlsplit(url)
        final_origin = (parsed_url.scheme.lower(), parsed_url.netloc.lower())
        if final_origin != self._base_origin:
            raise ValueError("endpoint resolved outside base_url origin")
        return url

    @staticmethod
    def _normalize_payload(value: Any) -> Any:
        """Convert entity wrappers nested in a JSON payload back to API dictionaries."""
        return WeclappEntity._unwrap(value)

    def request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Union[int, float]] = None,
    ) -> Any:
        """Send a same-origin request through the client's shared safety contract."""
        if not isinstance(method, str) or not method.strip():
            raise ValueError("method must be a non-empty string")
        method = method.strip().upper()
        url = self._build_url(endpoint)
        request_kwargs: Dict[str, Any] = {}
        if params is not None:
            request_kwargs["params"] = params
        if json is not None:
            request_kwargs["json"] = self._normalize_payload(json)
        if data is not None:
            request_kwargs["data"] = data
        if headers is not None:
            request_kwargs["headers"] = headers
        if timeout is not None:
            if (
                not isinstance(timeout, (int, float))
                or isinstance(timeout, bool)
                or not math.isfinite(timeout)
                or timeout <= 0
            ):
                raise ValueError("timeout must be greater than zero")
            request_kwargs["timeout"] = timeout
        return self._send_request(method, url, **request_kwargs)

    def _check_response(self, response):
        """Check if the response is valid and raise an exception if not.

        :param response: Response object from requests.
        :raises WeclappAPIError: if the request fails or returns non-2xx status.
        """
        if 300 <= response.status_code < 400:
            response_text = response.text
            location = response.headers.get("Location")
            message = f"HTTP {response.status_code} redirect responses are not followed"
            if location:
                message = f"{message}; Location: {location}"
            raise WeclappAPIError(message, response=response, response_text=response_text)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_message = str(e)
            response_text = response.text
            try:
                error_data = response.json()
                if isinstance(error_data, dict) and 'error' in error_data:
                    error_message = f"{error_message} - {error_data['error']}"
            except (ValueError, KeyError):
                pass
            if response_text:
                preview = response_text[:MAX_ERROR_MESSAGE_BODY_CHARS]
                if len(response_text) > MAX_ERROR_MESSAGE_BODY_CHARS:
                    preview = f"{preview}…"
                error_message = f"{error_message}\nResponse body: {preview}"
            raise WeclappAPIError(
                error_message,
                response=response,
                response_text=response_text,
            ) from e

    @staticmethod
    def _response_problem_type(response) -> str:
        try:
            payload = response.json()
        except (ValueError, TypeError):
            return ""
        if not isinstance(payload, dict):
            return ""
        return _problem_type_suffix(payload.get("type"))

    def _should_retry_problem(self, method: str, response, attempt: int) -> bool:
        if method not in SAFE_RETRY_METHODS or attempt >= self.problem_retries:
            return False
        problem_type = self._response_problem_type(response)
        return (
            response.status_code == 400 and problem_type == "request_timeout"
        ) or (
            response.status_code == 409 and problem_type == "persistence"
        )

    def _problem_retry_delay(self, attempt: int) -> float:
        base_delay = self.backoff_factor * (2 ** attempt)
        jitter = random.uniform(0, self.backoff_factor) if self.backoff_factor else 0
        return base_delay + jitter

    @staticmethod
    def _retry_after_seconds(response) -> Optional[float]:
        """Return a valid Retry-After delay in seconds, if supplied."""
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            return max(0.0, retry_at.timestamp() - time.time())

    def _status_retry_delay(self, response, attempt: int) -> float:
        retry_after = self._retry_after_seconds(response)
        if retry_after is not None:
            return retry_after
        return self._problem_retry_delay(attempt)

    def _should_retry_status(self, method: str, response, attempt: int) -> bool:
        return (
            method in SAFE_RETRY_METHODS
            and response.status_code in TRANSIENT_STATUS_CODES
            and attempt < self.max_retries
        )

    @staticmethod
    def _extract_filename(response) -> Optional[str]:
        content_disposition = response.headers.get("Content-Disposition")
        if not content_disposition:
            return None
        message = Message()
        message["Content-Disposition"] = content_disposition
        return message.get_filename()

    @classmethod
    def _parse_success_response(cls, response) -> Any:
        if response.status_code == 204 or not response.content:
            return {}

        content_type = response.headers.get("Content-Type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type == "application/json" or media_type.endswith("+json"):
            return response.json()

        textual_application_types = {
            "application/javascript",
            "application/xml",
            "application/xhtml+xml",
            "application/x-www-form-urlencoded",
        }
        if media_type.startswith("text/") or media_type in textual_application_types:
            return {"content": response.text, "content_type": content_type}

        if not media_type:
            try:
                return response.json()
            except ValueError:
                pass

        result = {"content": response.content, "content_type": content_type}
        filename = cls._extract_filename(response)
        if filename:
            result["filename"] = filename
        return result

    @staticmethod
    def _log_queue_metadata(method: str, path: str, response) -> None:
        wait_ms = response.headers.get("X-Weclapp-Wait-Ms")
        wait_reason = response.headers.get("X-Weclapp-Wait-Reason")
        correlation_id = (
            response.headers.get("X-Correlation-ID")
            or response.headers.get("X-Correlation-Id")
            or response.headers.get("X-Request-ID")
            or response.headers.get("X-Request-Id")
        )
        if wait_ms or wait_reason or correlation_id:
            logger.info(
                "[API_QUEUE] Weclapp %s %s wait_ms=%s reason=%s correlation_id=%s",
                method,
                path,
                wait_ms or "-",
                wait_reason or "-",
                correlation_id or "-",
            )

    def _send_request(self, method: str, url: str, **kwargs) -> Any:
        """
        Send an HTTP request and return parsed content.

        - If status code is 204 or body is empty, returns {}.
        - JSON media types return decoded JSON.
        - Text media types return text under ``content``.
        - Every other non-empty media type returns bytes under ``content``.

        :param method: HTTP method (GET, POST, etc.).
        :param url: Full URL for the request.
        :param kwargs: Additional request parameters (headers, json=data, params, etc.).
        :return: Dict or binary dict structure (for files).
        :raises WeclappAPIError: if the request fails or returns non-2xx status.
        """
        method = method.upper()
        kwargs.setdefault("timeout", self.timeout)
        # requests follows 301/302/307/308 by default. A 307/308 can replay a
        # write body even though the retry policy is disabled, so redirects are
        # always surfaced explicitly to the caller instead.
        kwargs.setdefault("allow_redirects", False)
        path = urlparse(url).path
        start = time.monotonic()
        status_code = None
        error = None
        response = None
        try:
            problem_attempt = 0
            retry_attempt = 0
            while True:
                response = None
                read_saturated = False
                read_permit = method in SAFE_RETRY_METHODS
                read_acquired = False
                try:
                    if read_permit:
                        read_saturated = self._read_controller.acquire()
                        read_acquired = True
                    response = self.session.request(method, url, **kwargs)
                except (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                    ) as exc:
                    retry_transport = (
                        method in SAFE_RETRY_METHODS
                        and not isinstance(exc, requests.exceptions.SSLError)
                        and retry_attempt < self.max_retries
                    )
                    if not retry_transport:
                        raise
                    delay = self._problem_retry_delay(retry_attempt)
                    logger.warning(
                        "[API_RETRY] Weclapp %s %s -> %s; retry %d/%d in %.2fs",
                        method,
                        path,
                        type(exc).__name__,
                        retry_attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    retry_attempt += 1
                    if delay:
                        time.sleep(delay)
                    continue
                finally:
                    if read_acquired:
                        self._read_controller.release()
                status_code = response.status_code
                retry_delay = None
                if self._should_retry_status(method, response, retry_attempt):
                    retry_delay = self._status_retry_delay(response, retry_attempt)
                elif response.status_code == 429:
                    retry_delay = self._problem_retry_delay(retry_attempt)
                self._read_controller.observe(
                    response,
                    retry_delay=retry_delay,
                    saturated=read_saturated,
                )
                if self._should_retry_status(method, response, retry_attempt):
                    self._log_queue_metadata(method, path, response)
                    delay = retry_delay
                    logger.warning(
                        "[API_RETRY] Weclapp %s %s -> %s; retry %d/%d in %.2fs",
                        method,
                        path,
                        response.status_code,
                        retry_attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    retry_attempt += 1
                    if delay:
                        time.sleep(delay)
                    continue
                if not self._should_retry_problem(method, response, problem_attempt):
                    break
                self._log_queue_metadata(method, path, response)
                problem_type = self._response_problem_type(response)
                delay = self._problem_retry_delay(problem_attempt)
                logger.warning(
                    "[API_RETRY] Weclapp %s %s -> %s/%s; retry %d/%d in %.2fs",
                    method,
                    path,
                    response.status_code,
                    problem_type,
                    problem_attempt + 1,
                    self.problem_retries,
                    delay,
                )
                problem_attempt += 1
                if delay:
                    time.sleep(delay)

            self._check_response(response)
            return self._parse_success_response(response)

        except WeclappAPIError as exc:
            error = exc
            raise
        except requests.exceptions.RequestException as e:
            error = e
            # Use response.text if available for error details
            response_text = None
            response_obj = None
            if hasattr(e, 'response') and e.response is not None:
                response_obj = e.response
                response_text = e.response.text
            elif 'response' in locals() and response is not None:
                response_obj = response
                response_text = response.text
            error_message = f"HTTP {method} request failed for {path}: {e}"
            if response_text:
                preview = response_text[:MAX_ERROR_MESSAGE_BODY_CHARS]
                if len(response_text) > MAX_ERROR_MESSAGE_BODY_CHARS:
                    preview = f"{preview}…"
                error_message = f"{error_message}\nResponse body: {preview}"
            raise WeclappAPIError(
                error_message, response=response_obj, response_text=response_text
            ) from e
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            if response is not None:
                self._log_queue_metadata(method, path, response)
            if error is not None:
                logger.warning(
                    f"[API] Weclapp {method} {path} -> ERROR ({duration_ms:.0f}ms) "
                    f"{type(error).__name__}"
                )
            elif status_code is not None:
                if duration_ms >= self.slow_threshold_ms:
                    logger.warning(
                        f"[API_SLOW] Weclapp {method} {path} -> {status_code} "
                        f"({duration_ms:.0f}ms)"
                    )
                else:
                    logger.info(
                        f"[API] Weclapp {method} {path} -> {status_code} ({duration_ms:.0f}ms)"
                    )

    def _wrap_rows(
        self,
        rows: List[Dict[str, Any]],
        additional_properties_global: Optional[Dict[str, List[Any]]],
        referenced_entities: Optional[Dict[str, Dict[str, Any]]],
    ) -> List['WeclappEntity']:
        """Wrap raw result rows as WeclappEntity, slicing additionalProperties per row."""
        if not rows:
            return []
        ap_global = additional_properties_global or {}
        ref_map = referenced_entities or {}
        attr_defs = self._ensure_attribute_definitions([rows, ref_map])
        wrapped: List[WeclappEntity] = []
        for index, row in enumerate(rows):
            per_row: Dict[str, Any] = {}
            for name, values in ap_global.items():
                per_row[name] = (
                    values[index]
                    if isinstance(values, list) and index < len(values)
                    else None
                )
            wrapped.append(WeclappEntity.from_row(row, per_row, ref_map, attr_defs))
        return wrapped

    def _ensure_attribute_definitions(
        self, rows: Any
    ) -> Dict[str, Dict[str, Any]]:
        """Lazily fetch and cache all customAttributeDefinitions on first need.

        Triggered when at least one row (or any nested dict inside it) carries a
        non-empty ``customAttributes`` list whose items lack ``internalName`` —
        the only case where the cache is needed to derive flattened field
        names. Cached for the lifetime of the client.
        """
        if self._attribute_definitions_by_id is not None:
            return self._attribute_definitions_by_id
        if not self._rows_need_attribute_definitions(rows):
            return {}

        cache: Dict[str, Dict[str, Any]] = {}
        try:
            page = 1
            while True:
                params = {
                    'page': page,
                    'pageSize': DEFAULT_PAGE_SIZE,
                    'sort': 'id',
                    'properties': 'id,attributeKey,attributeType,readOnly',
                }
                data = self.request("GET", 'customAttributeDefinition', params=params)
                results = data.get('result', []) if isinstance(data, dict) else []
                for defn in results:
                    if isinstance(defn, dict) and 'id' in defn:
                        cache[defn['id']] = defn
                if len(results) < DEFAULT_PAGE_SIZE:
                    break
                page += 1
        except WeclappAPIError as exc:
            logger.warning(
                "Failed to fetch customAttributeDefinitions; "
                "customAttribute flattening will skip unnamed entries "
                "(status=%s, type=%s)",
                exc.status_code,
                exc.error_type,
            )
            # Cache permanent client-side failures, but let later reads recover
            # from transport, rate-limit, timeout, or server failures.
            if (
                exc.status_code is not None
                and 400 <= exc.status_code < 500
                and not exc.is_retryable
            ):
                self._attribute_definitions_by_id = {}
            return {}
        self._attribute_definitions_by_id = cache
        return cache

    @classmethod
    def _rows_need_attribute_definitions(cls, rows: Any) -> bool:
        """True if any customAttribute in the response lacks internalName."""
        if isinstance(rows, dict):
            cas = rows.get('customAttributes')
            if isinstance(cas, list):
                for item in cas:
                    if isinstance(item, dict) and not item.get('internalName'):
                        return True
            for v in rows.values():
                if isinstance(v, (dict, list)) and cls._rows_need_attribute_definitions(v):
                    return True
        elif isinstance(rows, list):
            for item in rows:
                if cls._rows_need_attribute_definitions(item):
                    return True
        return False

    @staticmethod
    def _not_found_error(endpoint: str, id_value: str, url: str) -> 'WeclappAPIError':
        message = f"Entity '{endpoint}' with id '{id_value}' not found"
        body = json.dumps({
            "type": "/errors/not_found",
            "error": "Not Found",
            "detail": message,
        })
        synthetic = requests.Response()
        synthetic.status_code = 404
        synthetic.url = url
        synthetic._content = body.encode("utf-8")
        synthetic.headers["Content-Type"] = "application/json"
        return WeclappAPIError(message, response=synthetic, response_text=body)

    @overload
    def get(
        self,
        endpoint: str,
        id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        *,
        return_weclapp_response: "Literal[True]",
    ) -> WeclappResponse: ...

    @overload
    def get(
        self,
        endpoint: str,
        id: Optional[str],
        params: Optional[Dict[str, Any]],
        return_weclapp_response: "Literal[True]",
    ) -> WeclappResponse: ...

    @overload
    def get(
        self,
        endpoint: str,
        id: str,
        params: Optional[Dict[str, Any]] = None,
        return_weclapp_response: "Literal[False]" = False,
    ) -> 'WeclappEntity': ...

    @overload
    def get(
        self,
        endpoint: str,
        id: None = None,
        params: Optional[Dict[str, Any]] = None,
        return_weclapp_response: "Literal[False]" = False,
    ) -> List['WeclappEntity']: ...

    def get(
        self,
        endpoint: str,
        id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        return_weclapp_response: bool = False
    ) -> Union[List['WeclappEntity'], 'WeclappEntity', WeclappResponse]:
        """Perform a GET request and return ``WeclappEntity`` objects.

        Reads always go through the list endpoint. When ``id`` is provided,
        the request is ``GET {endpoint}?id-eq={id}&pageSize=1``. This ensures
        ``additionalProperties`` and ``referencedEntities`` are always
        available to the entity wrapper, so flattened customAttributes and
        lazy ``*Id`` resolution work uniformly.

        :param endpoint: API endpoint.
        :param id: Optional identifier to fetch a single record.
        :param params: Query parameters. Use this to add ``additionalProperties``
            and ``includeReferencedEntities`` parameters directly.
        :param return_weclapp_response: If True, returns a ``WeclappResponse``
            wrapping the entity (list or single) plus the raw response shape.
        :return: A single ``WeclappEntity`` if ``id`` is provided, or a list
            of ``WeclappEntity`` otherwise. When ``return_weclapp_response``
            is True, returns a ``WeclappResponse``.
        :raises WeclappAPIError: on request failure or when ``id`` lookup
            yields no result (404 contract preserved).
        """
        params = params.copy() if params is not None else {}
        url = self._build_url(endpoint)

        if id is not None:
            params['id-eq'] = id
            params['page'] = 1
            params['pageSize'] = 1
            logger.debug("GET single %s", endpoint)
            response_data = self.request("GET", endpoint, params=params)
            response = WeclappResponse.from_api_response(response_data)
            rows = response.result or []
            if not rows:
                raise self._not_found_error(endpoint, id, url)
            wrapped = self._wrap_rows(
                rows, response.additional_properties, response.referenced_entities
            )
            if return_weclapp_response:
                return WeclappResponse(
                    result=wrapped[0],
                    additional_properties=response.additional_properties,
                    referenced_entities=response.referenced_entities,
                    raw_response=response.raw_response,
                )
            return wrapped[0]

        logger.debug("GET %s", endpoint)
        response_data = self.request("GET", endpoint, params=params)
        response = WeclappResponse.from_api_response(response_data)
        wrapped = self._wrap_rows(
            response.result or [],
            response.additional_properties,
            response.referenced_entities,
        )
        if return_weclapp_response:
            return WeclappResponse(
                result=wrapped,
                additional_properties=response.additional_properties,
                referenced_entities=response.referenced_entities,
                raw_response=response.raw_response,
            )
        return wrapped

    @staticmethod
    def _validate_limit(limit: Optional[int]) -> None:
        if limit is not None and (
            not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
        ):
            raise ValueError("limit must be a non-negative integer or None")

    @staticmethod
    def _pagination_page_size(
        params: Dict[str, Any], limit: Optional[int]
    ) -> int:
        page_size = params.get('pageSize', DEFAULT_PAGE_SIZE)
        if (
            not isinstance(page_size, int)
            or isinstance(page_size, bool)
            or page_size <= 0
        ):
            raise ValueError("pageSize must be a positive integer")
        if limit is not None and limit > 0:
            return min(page_size, limit)
        return page_size

    @staticmethod
    def _count_params(params: Dict[str, Any]) -> Dict[str, Any]:
        count_params = params.copy()
        for key in (
            'page',
            'pageSize',
            'sort',
            'orderBy',
            'properties',
            'additionalProperties',
            'includeReferencedEntities',
            'serializeNulls',
        ):
            count_params.pop(key, None)
        return count_params

    @staticmethod
    def _record_page_result_ids(
        rows: List[Dict[str, Any]],
        seen_result_ids: set,
        entity: str,
        page_number: int,
    ) -> None:
        """Reject duplicate projected IDs before merging a pagination page.

        A duplicate usually means that the dataset moved between page
        requests.  Rows without a usable ``id`` are intentionally ignored:
        callers that omit ``id`` from ``properties`` get no false consistency
        guarantee.
        """
        page_result_ids = set()
        for row in rows:
            if not isinstance(row, dict) or row.get('id') is None:
                continue
            result_id = row['id']
            try:
                duplicate = (
                    result_id in seen_result_ids or result_id in page_result_ids
                )
            except TypeError:
                # weclapp IDs are strings.  An unexpected unhashable value is
                # not treated as evidence of a duplicate.
                continue
            if duplicate:
                raise WeclappAPIError(
                    f"Pagination for '{entity}' returned duplicate entity id "
                    f"'{result_id}' on page {page_number}. The dataset may have "
                    "changed between page requests; retry against stable data "
                    "and use an explicit stable sort such as 'sort=id'."
                )
            page_result_ids.add(result_id)
        seen_result_ids.update(page_result_ids)

    @classmethod
    def _merge_page_response(
        cls,
        page_data: Dict[str, Any],
        results: List[Dict[str, Any]],
        all_additional_properties: Dict[str, List[Any]],
        all_referenced_entities: Dict[str, List[Dict[str, Any]]],
        *,
        seen_result_ids: Optional[set] = None,
        entity: str = "entity",
        page_number: int = 0,
    ) -> int:
        if not isinstance(page_data, dict):
            raise TypeError("weclapp list response must be a dictionary")
        current_page = page_data.get('result', []) or []
        if not isinstance(current_page, list):
            raise TypeError("weclapp list response 'result' must be a list")

        if seen_result_ids is not None:
            cls._record_page_result_ids(
                current_page,
                seen_result_ids,
                entity,
                page_number,
            )
        previous_count = len(results)
        page_count = len(current_page)
        results.extend(current_page)

        page_properties = page_data.get('additionalProperties') or {}
        if not isinstance(page_properties, dict):
            page_properties = {}
        for name in set(all_additional_properties) - set(page_properties):
            all_additional_properties[name].extend([None] * page_count)
        for name, values in page_properties.items():
            if name not in all_additional_properties:
                all_additional_properties[name] = [None] * previous_count
            normalized_values = list(values) if isinstance(values, list) else []
            normalized_values = normalized_values[:page_count]
            if len(normalized_values) < page_count:
                normalized_values.extend([None] * (page_count - len(normalized_values)))
            all_additional_properties[name].extend(normalized_values)

        page_references = page_data.get('referencedEntities') or {}
        if isinstance(page_references, dict):
            for entity_type, entities in page_references.items():
                if not isinstance(entities, list):
                    continue
                all_referenced_entities.setdefault(entity_type, []).extend(entities)
        return page_count

    def _finalize_collection_response(
        self,
        results: List[Dict[str, Any]],
        all_additional_properties: Dict[str, List[Any]],
        all_referenced_entities: Dict[str, List[Dict[str, Any]]],
        limit: Optional[int],
        return_weclapp_response: bool,
    ) -> Union[List['WeclappEntity'], WeclappResponse]:
        if limit is not None:
            results = results[:limit]
        result_count = len(results)
        if all_additional_properties:
            all_additional_properties = {
                name: values[:result_count]
                for name, values in all_additional_properties.items()
            }

        raw_response: Dict[str, Any] = {'result': results}
        if all_additional_properties:
            raw_response['additionalProperties'] = all_additional_properties
        if all_referenced_entities:
            raw_response['referencedEntities'] = all_referenced_entities

        response = WeclappResponse.from_api_response(raw_response)
        wrapped = self._wrap_rows(
            response.result,
            response.additional_properties,
            response.referenced_entities,
        )
        if return_weclapp_response:
            return WeclappResponse(
                result=wrapped,
                additional_properties=response.additional_properties,
                referenced_entities=response.referenced_entities,
                raw_response=response.raw_response,
            )
        return wrapped

    @staticmethod
    def _empty_collection_response(
        return_weclapp_response: bool,
    ) -> Union[List['WeclappEntity'], WeclappResponse]:
        if return_weclapp_response:
            return WeclappResponse(
                result=[],
                additional_properties=None,
                referenced_entities=None,
                raw_response={'result': []},
            )
        return []

    @overload
    def get_all(
        self,
        entity: str,
        params: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        threaded: bool = True,
        max_workers: Optional[int] = None,
        *,
        return_weclapp_response: "Literal[True]",
    ) -> WeclappResponse: ...

    @overload
    def get_all(
        self,
        entity: str,
        params: Optional[Dict[str, Any]],
        limit: Optional[int],
        threaded: bool,
        max_workers: Optional[int],
        return_weclapp_response: "Literal[True]",
    ) -> WeclappResponse: ...

    @overload
    def get_all(
        self,
        entity: str,
        params: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        threaded: bool = True,
        max_workers: Optional[int] = None,
        return_weclapp_response: "Literal[False]" = False,
    ) -> List['WeclappEntity']: ...

    def get_all(
        self,
        entity: str,
        params: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        threaded: bool = True,
        max_workers: Optional[int] = None,
        return_weclapp_response: bool = False
    ) -> Union[List['WeclappEntity'], WeclappResponse]:
        """
        Retrieve all records for the given entity with automatic pagination.

        :param entity: Entity name, e.g. 'salesOrder'.
        :param params: Query parameters. Use this to add 'additionalProperties' and 'includeReferencedEntities' parameters directly.
        :param limit: Limit total records returned.
        :param threaded: Fetch pages adaptively in parallel if True (default).
        :param max_workers: Optional adaptive concurrency ceiling (default is 10 internally).
        :param return_weclapp_response: If True, returns a WeclappResponse object instead of just the result.
        :return: List of records, or a WeclappResponse object if return_weclapp_response is True.
        :raises WeclappAPIError: on request failure.
        """
        self._validate_limit(limit)
        if threaded and max_workers is not None and (
            not isinstance(max_workers, int)
            or isinstance(max_workers, bool)
            or max_workers <= 0
        ):
            raise ValueError("max_workers must be a positive integer")
        if limit == 0:
            return self._empty_collection_response(return_weclapp_response)

        params = params.copy() if params is not None else {}
        page_size = self._pagination_page_size(params, limit)
        params['pageSize'] = page_size
        results: List[Dict[str, Any]] = []
        all_additional_properties: Dict[str, List[Any]] = {}
        all_referenced_entities: Dict[str, List[Dict[str, Any]]] = {}
        seen_result_ids = set()

        if not threaded:
            page_number = 1
            while True:
                page_params = params.copy()
                page_params['page'] = page_number
                logger.info("Fetching page %d for %s", page_number, entity)
                page_data = self.request("GET", entity, params=page_params)
                page_count = self._merge_page_response(
                    page_data,
                    results,
                    all_additional_properties,
                    all_referenced_entities,
                    seen_result_ids=seen_result_ids,
                    entity=entity,
                    page_number=page_number,
                )
                if (
                    page_count < page_size
                    or (limit is not None and len(results) >= limit)
                ):
                    break
                page_number += 1
        else:
            count_data = self.request(
                "GET",
                f"{entity}/count",
                params=self._count_params(params),
            )
            if not isinstance(count_data, dict):
                raise TypeError("weclapp count response must be a dictionary")
            total_count = count_data.get('result', 0)
            if not isinstance(total_count, int) or isinstance(total_count, bool):
                raise TypeError("weclapp count response 'result' must be an integer")
            if total_count <= 0:
                logger.info("No records found for entity '%s'", entity)
                return self._empty_collection_response(return_weclapp_response)

            total_for_pages = min(total_count, limit) if limit is not None else total_count
            total_pages = math.ceil(total_for_pages / page_size)
            worker_ceiling = max_workers or DEFAULT_MAX_WORKERS
            logger.info(
                "Total %d records for %s; fetching %d pages with adaptive concurrency up to %d",
                total_count,
                entity,
                total_pages,
                worker_ceiling,
            )

            def fetch_page(page_number: int) -> Dict[str, Any]:
                page_params = params.copy()
                page_params['page'] = page_number
                logger.info(
                    "[Threaded] Fetching page %d/%d for %s",
                    page_number,
                    total_pages,
                    entity,
                )
                return self.request("GET", entity, params=page_params)

            pages: Dict[int, Dict[str, Any]] = {}
            with ThreadPoolExecutor(max_workers=worker_ceiling) as executor:
                future_to_page = {}
                next_page = 1

                def submit_available() -> None:
                    nonlocal next_page
                    target = min(worker_ceiling, self._read_controller.target)
                    while next_page <= total_pages and len(future_to_page) < target:
                        future = executor.submit(fetch_page, next_page)
                        future_to_page[future] = next_page
                        next_page += 1

                submit_available()
                try:
                    while future_to_page:
                        done, _ = wait(
                            future_to_page,
                            return_when=FIRST_COMPLETED,
                        )
                        for future in done:
                            page_number = future_to_page.pop(future)
                            pages[page_number] = future.result()
                            logger.info(
                                "[Threaded] Completed page %d/%d for %s",
                                page_number,
                                total_pages,
                                entity,
                            )
                        submit_available()
                except Exception:
                    for pending in future_to_page:
                        pending.cancel()
                    raise

            for page_number in sorted(pages):
                self._merge_page_response(
                    pages[page_number],
                    results,
                    all_additional_properties,
                    all_referenced_entities,
                    seen_result_ids=seen_result_ids,
                    entity=entity,
                    page_number=page_number,
                )
            if len(results) < total_for_pages:
                raise WeclappAPIError(
                    f"Threaded pagination returned {len(results)} of "
                    f"{total_for_pages} expected records for '{entity}'"
                )

        return self._finalize_collection_response(
            results,
            all_additional_properties,
            all_referenced_entities,
            limit,
            return_weclapp_response,
        )

    def iter_all(
        self,
        entity: str,
        params: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> Iterator['WeclappEntity']:
        """Yield entities page by page without retaining the full result set."""
        self._validate_limit(limit)
        if limit == 0:
            return
        page_params = params.copy() if params is not None else {}
        page_size = self._pagination_page_size(page_params, limit)
        page_params['pageSize'] = page_size
        yielded = 0
        page_number = 1
        seen_result_ids = set()
        while True:
            page_params['page'] = page_number
            data = self.request("GET", entity, params=page_params)
            response = WeclappResponse.from_api_response(data)
            rows = response.result or []
            if not rows:
                break
            if not isinstance(rows, list):
                raise TypeError("weclapp list response 'result' must be a list")
            self._record_page_result_ids(
                rows,
                seen_result_ids,
                entity,
                page_number,
            )
            wrapped = self._wrap_rows(
                rows,
                response.additional_properties,
                response.referenced_entities,
            )
            for item in wrapped:
                yield item
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            if len(rows) < page_size:
                break
            page_number += 1

    def post(
        self,
        endpoint: str,
        data: Union[Dict[str, Any], WeclappEntity],
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Perform a POST request to the given endpoint.

        :param endpoint: API endpoint.
        :param data: Data to post.
        :param params: Optional query parameters (e.g., dryRun).
        :return: JSON response.
        :raises WeclappAPIError: on request failure.
        """
        logger.debug("POST %s", endpoint)
        return self.request("POST", endpoint, json=data, params=params)

    def put(
        self,
        endpoint: str,
        id: str,
        data: Union[Dict[str, Any], WeclappEntity],
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
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
        path = f"{endpoint}/id/{id}"
        logger.debug("PUT %s", path)
        return self.request("PUT", path, json=data, params=params)

    def delete(
        self,
        endpoint: str,
        id: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
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
        path = f"{endpoint}/id/{id}"
        logger.debug("DELETE %s", path)
        return self.request("DELETE", path, params=params)

    def call_method(
        self,
        entity: str,
        action: str,
        entity_id: Optional[str] = None,
        method: str = "GET",
        data: Optional[Union[Dict[str, Any], WeclappEntity]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
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

        method = method.upper()
        if method not in ("GET", "POST"):
            raise ValueError("Only GET and POST methods are supported by call_method().")

        return self.request(method, path, json=data, params=params)

    def upload(
        self,
        endpoint: str,
        data: bytes,
        id: Optional[str] = None,
        action: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        content_type: Optional[str] = None,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload binary data (documents, images) to a weclapp endpoint.

        The URL is constructed based on the provided parameters:
        - If both id and action are provided: {endpoint}/id/{id}/{action}
        - If only action is provided: {endpoint}/{action}
        - Otherwise: {endpoint}

        Content type is determined in order of priority:
        1. Explicit content_type parameter (highest priority)
        2. Inferred from filename extension
        3. Falls back to 'application/octet-stream'

        A warning is logged if content_type and filename extension suggest different types.

        :param endpoint: API endpoint (e.g., 'document', 'article').
        :param data: Binary data to upload.
        :param id: Optional entity ID for entity-specific uploads.
        :param action: Optional action name (e.g., 'upload', 'uploadArticleImage').
        :param params: Query parameters (e.g., entityName, entityId, name for document upload).
        :param content_type: Explicit MIME type. If not provided, inferred from filename.
        :param filename: Used for content type inference and logging. Not sent to API unless in params.
        :return: API response as dict.
        :raises WeclappAPIError: on request failure.
        """
        params = params.copy() if params is not None else {}

        # Determine content type
        inferred_type = infer_content_type(filename)
        effective_content_type = content_type or inferred_type or 'application/octet-stream'

        # Warn if explicit content_type differs from inferred type
        if content_type and inferred_type and content_type != inferred_type:
            logger.warning(
                f"Content type mismatch: explicit '{content_type}' differs from "
                f"inferred '{inferred_type}' for filename '{filename}'"
            )

        # Build URL based on parameters
        if id is not None and action is not None:
            path = f"{endpoint}/id/{id}/{action}"
        elif action is not None:
            path = f"{endpoint}/{action}"
        else:
            path = endpoint

        logger.debug("UPLOAD %s Content-Type=%s", path, effective_content_type)

        # Send request with binary data
        headers = {"Content-Type": effective_content_type}
        return self.request("POST", path, data=data, headers=headers, params=params)

    def download(
        self,
        endpoint: str,
        id: Optional[str] = None,
        action: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Download binary data from a weclapp endpoint.

        The URL is constructed based on the provided parameters:
        - If both id and action are provided: {endpoint}/id/{id}/{action}
        - If only id is provided: {endpoint}/id/{id}/download
        - If only action is provided: {endpoint}/{action}
        - Otherwise: {endpoint}

        :param endpoint: API endpoint (e.g., 'document', 'salesInvoice').
        :param id: Optional entity ID.
        :param action: Optional action name (e.g., 'downloadLatestSalesInvoicePdf').
        :param params: Query parameters.
        :return: Dict with 'content' (bytes) and 'content_type' keys for binary data,
                 or regular dict for JSON responses.
        :raises WeclappAPIError: on request failure.
        """
        params = params.copy() if params is not None else {}

        # Build URL based on parameters
        if id is not None and action is not None:
            path = f"{endpoint}/id/{id}/{action}"
        elif id is not None:
            path = f"{endpoint}/id/{id}/download"
        elif action is not None:
            path = f"{endpoint}/{action}"
        else:
            path = endpoint

        logger.debug("DOWNLOAD %s", path)

        return self.request("GET", path, params=params)
