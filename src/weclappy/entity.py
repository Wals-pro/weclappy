"""Response container and attribute-access entity wrapper for weclapp API rows."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Self, cast, override

__all__ = ["JsonDict", "WeclappEntity", "WeclappResponse"]

logger = logging.getLogger("weclappy.entity")

JsonDict = dict[str, Any]
"""A decoded JSON object as returned by (or sent to) the weclapp API."""


class WeclappEntity(dict[str, Any]):
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
      object referenced by ``entity['customerId']``). Resolved objects are
      cached per ``(field, id)``, so reassigning ``entity['customerId']``
      resolves the new id on the next access.

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

    Caveats:

    - Fields whose names collide with ``dict`` methods (``items``, ``keys``,
      ``values``, ``get``, ``copy``, ``update``, ``pop`` ...) are reachable only
      via item access, e.g. ``entity["items"]``; ``entity.items`` is the dict
      method.
    - ``entity.copy()``, ``dict(entity)`` and ``json.dumps(entity)`` include
      the synthetic flattened customAttribute keys and merged
      additionalProperties keys. :meth:`to_payload` is the only supported path
      into a write request.
    """

    _CUSTOM_ATTRIBUTE_VALUE_FIELDS: ClassVar[tuple[str, ...]] = (
        "stringValue",
        "numberValue",
        "booleanValue",
        "dateValue",
        "entityId",
        "entityReferences",
        "selectedValueId",
        "selectedValues",
    )

    # ``customAttribute`` is a closed v2 schema. Legacy responses can contain
    # helper metadata such as ``internalName``; forwarding that metadata makes
    # an otherwise valid PUT fail with ``platform.unknown_property``.
    _CUSTOM_ATTRIBUTE_FIELDS: ClassVar[tuple[str, ...]] = (
        "attributeDefinitionId",
        *_CUSTOM_ATTRIBUTE_VALUE_FIELDS,
    )

    _CUSTOM_ATTRIBUTE_NESTED_FIELDS: ClassVar[dict[str, tuple[str, ...]]] = {
        "entityReferences": ("entityId", "entityName"),
        "selectedValues": ("id",),
    }

    _CUSTOM_ATTRIBUTE_TYPE_FIELDS: ClassVar[dict[str, str]] = {
        "BOOLEAN": "booleanValue",
        "DATE": "dateValue",
        "DECIMAL": "numberValue",
        "INTEGER": "numberValue",
        "ENTITY": "entityId",
        "REFERENCE": "entityReferences",
        "LIST": "selectedValueId",
        "MULTISELECT_LIST": "selectedValues",
        "LARGE_TEXT": "stringValue",
        "STRING": "stringValue",
        "URL": "stringValue",
    }

    _MAX_WRAP_DEPTH: ClassVar[int] = 64

    # Per-instance state, set via ``object.__setattr__`` because
    # ``__setattr__`` is reserved for the customAttribute write contract.
    _custom_attr_index: dict[str, tuple[int, str, Any]]
    _referenced_entities: dict[str, dict[str, JsonDict]]
    _ref_cache: dict[tuple[str, Any], "WeclappEntity"]
    _original_keys: set[str]
    _additional_property_keys: set[str]
    _attribute_definitions: dict[str, JsonDict]
    _defined_custom_attr_names: set[str]
    _read_only_custom_attrs: set[str]
    _read_only_custom_attr_positions: dict[int, JsonDict]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_custom_attr_index", {})
        object.__setattr__(self, "_referenced_entities", {})
        object.__setattr__(self, "_ref_cache", {})
        object.__setattr__(self, "_original_keys", set(self.keys()))
        object.__setattr__(self, "_additional_property_keys", set())
        object.__setattr__(self, "_attribute_definitions", {})
        object.__setattr__(self, "_defined_custom_attr_names", set())
        object.__setattr__(self, "_read_only_custom_attrs", set())
        object.__setattr__(self, "_read_only_custom_attr_positions", {})

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_row(
        cls,
        row: JsonDict,
        additional_properties_for_row: JsonDict | None = None,
        referenced_entities: dict[str, dict[str, JsonDict]] | None = None,
        attribute_definitions: dict[str, JsonDict] | None = None,
    ) -> "WeclappEntity":
        """Build a WeclappEntity from a single result row.

        Nested dict and list-of-dict values are recursively wrapped as
        ``WeclappEntity`` so attribute access, customAttribute flattening, and
        ``*Id`` resolution work uniformly at every level. Passing an existing
        ``WeclappEntity`` returns it unchanged (idempotent). The input row is
        not mutated.

        :param row: Raw entity dict from the API ``result`` list.
        :param additional_properties_for_row: Per-row slice of the response's
            ``additionalProperties`` (i.e. ``{prop_name: value_for_this_row}``).
        :param referenced_entities: Shared referenced-entities map produced by
            ``WeclappResponse.from_api_response`` (``{type: {id: entity_dict}}``).
        :param attribute_definitions: Map of ``attributeDefinitionId`` to the
            full definition dict (must contain ``attributeKey``). weclapp does
            not include ``internalName`` on entity-level customAttributes, so
            this map is used to derive flattened field names.
        :raises ValueError: If the row is nested deeper than ``_MAX_WRAP_DEPTH``.
        """
        return cls._from_row_at_depth(
            row,
            additional_properties_for_row,
            referenced_entities,
            attribute_definitions,
            0,
        )

    @classmethod
    def _from_row_at_depth(
        cls,
        row: JsonDict,
        additional_properties_for_row: JsonDict | None,
        referenced_entities: dict[str, dict[str, JsonDict]] | None,
        attribute_definitions: dict[str, JsonDict] | None,
        depth: int,
    ) -> "WeclappEntity":
        """Implementation of :meth:`from_row` carrying the recursion depth."""
        if isinstance(row, WeclappEntity):
            return row
        if depth > cls._MAX_WRAP_DEPTH:
            raise ValueError(
                f"WeclappEntity wrap depth exceeded {cls._MAX_WRAP_DEPTH}; "
                "input row is too deeply nested or cyclic."
            )

        entity = cls(row)
        object.__setattr__(entity, "_original_keys", set(entity.keys()))

        if referenced_entities:
            object.__setattr__(entity, "_referenced_entities", referenced_entities)
        if attribute_definitions:
            object.__setattr__(entity, "_attribute_definitions", attribute_definitions)
            object.__setattr__(
                entity,
                "_defined_custom_attr_names",
                {
                    name
                    for definition in attribute_definitions.values()
                    if isinstance(definition, dict)
                    for name in (definition.get("attributeKey") or definition.get("internalName"),)
                    if isinstance(name, str) and name
                },
            )

        custom_attributes = entity.get("customAttributes")
        if isinstance(custom_attributes, list):
            cls._flatten_custom_attributes(entity, custom_attributes, attribute_definitions)

        if additional_properties_for_row:
            cls._merge_additional_properties(entity, additional_properties_for_row)

        # Recursively wrap nested dict / list-of-dict values. The raw
        # customAttributes list is metadata (definitions + values), not entities,
        # so it stays untouched and is fully owned by the flatten/round-trip pass.
        for key in list(entity.keys()):
            if key == "customAttributes":
                continue
            current = entity[key]
            wrapped = cls._wrap_nested_value(
                current, referenced_entities, attribute_definitions, depth + 1
            )
            if wrapped is not current:
                dict.__setitem__(entity, key, wrapped)

        return entity

    @classmethod
    def _wrap_nested_value(
        cls,
        value: Any,
        referenced_entities: dict[str, dict[str, JsonDict]] | None,
        attribute_definitions: dict[str, JsonDict] | None,
        depth: int,
    ) -> Any:
        """Wrap dicts (and dicts inside lists) as ``WeclappEntity``; pass scalars through."""
        if isinstance(value, WeclappEntity):
            return value
        if isinstance(value, dict):
            if depth > cls._MAX_WRAP_DEPTH:
                raise ValueError(f"WeclappEntity wrap depth exceeded {cls._MAX_WRAP_DEPTH}")
            return cls._from_row_at_depth(
                value, None, referenced_entities, attribute_definitions, depth
            )
        if isinstance(value, list):
            if depth > cls._MAX_WRAP_DEPTH:
                raise ValueError(f"WeclappEntity wrap depth exceeded {cls._MAX_WRAP_DEPTH}")
            return [
                cls._wrap_nested_value(item, referenced_entities, attribute_definitions, depth + 1)
                for item in value
            ]
        return value

    @classmethod
    def _flatten_custom_attributes(
        cls,
        entity: "WeclappEntity",
        custom_attributes: list[Any],
        attribute_definitions: dict[str, JsonDict] | None = None,
    ) -> None:
        index = entity._custom_attr_index
        for position, item in enumerate(custom_attributes):
            if not isinstance(item, dict):
                continue
            attr_def_id = item.get("attributeDefinitionId")
            definition = (
                attribute_definitions.get(attr_def_id)
                if attr_def_id and attribute_definitions
                else None
            )
            is_read_only = bool(isinstance(definition, dict) and definition.get("readOnly") is True)
            if is_read_only:
                entity._read_only_custom_attr_positions[position] = cls.unwrap(item)
            # v2 definition metadata is authoritative; ``internalName`` only
            # exists on legacy response shapes and is a fallback when no
            # definition was available.
            name = (
                definition.get("attributeKey") or definition.get("internalName")
                if definition
                else None
            )
            if not name:
                name = item.get("internalName")
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
            dict.__setitem__(entity, name, cls.unwrap(value))
            index[name] = (position, value_field, attr_def_id)
            if is_read_only:
                entity._read_only_custom_attrs.add(name)

    @classmethod
    def _extract_custom_attribute_value(
        cls,
        item: Mapping[str, Any],
        definition: Mapping[str, Any] | None = None,
    ) -> tuple[Any, str]:
        # The definition is authoritative. Legacy payloads occasionally carry
        # several typed slots, so scanning for the first non-null value before
        # consulting ``attributeType`` can expose the wrong field.
        if definition:
            attribute_type = str(definition.get("attributeType") or "").upper()
            value_field = cls._CUSTOM_ATTRIBUTE_TYPE_FIELDS.get(attribute_type)
            if value_field:
                return item.get(value_field), value_field

        for field in cls._CUSTOM_ATTRIBUTE_VALUE_FIELDS:
            if field in item and item[field] is not None:
                return item[field], field

        # Legacy responses may expose just one typed field with a null value.
        present_fields = [field for field in cls._CUSTOM_ATTRIBUTE_VALUE_FIELDS if field in item]
        if len(present_fields) == 1:
            return item.get(present_fields[0]), present_fields[0]
        return None, "stringValue"

    @classmethod
    def _merge_additional_properties(
        cls, entity: "WeclappEntity", additional_props: Mapping[str, Any]
    ) -> None:
        ap_keys = entity._additional_property_keys
        for name, value in additional_props.items():
            if name in entity:
                logger.warning(
                    "additionalProperty '%s' collides with existing entity field; built-in wins.",
                    name,
                )
                continue
            dict.__setitem__(entity, name, value)
            ap_keys.add(name)

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    @property
    def additional_properties(self) -> JsonDict:
        """Return the actually merged additionalProperties as a plain copy.

        The convenience namespace is read-only and excludes response values
        that collided with built-in entity fields and therefore were not
        merged. Nested containers are copied so callers cannot mutate the
        entity through the returned mapping.
        """
        return {
            name: self.unwrap(value)
            for name, value in self.items()
            if name in self._additional_property_keys
        }

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self:
            return self[name]
        id_key = name + "Id"
        if id_key in self:
            resolved = self._resolve_reference(name, self[id_key])
            if resolved is not None:
                return resolved
        raise AttributeError(name)

    def _resolve_reference(self, name: str, ref_id: Any) -> "WeclappEntity | None":
        """Resolve a stripped ``*Id`` accessor against the shared ref map.

        Tries name-based buckets first (``customer`` / ``customers``); falls
        back to a flat id lookup across all buckets because weclapp uses
        unified types under different field names (e.g. ``customerId`` and
        ``invoiceRecipientId`` both resolve to the ``party`` bucket).

        Results are cached per ``(name, ref_id)`` so the same object is
        returned on repeated access while a reassigned ``*Id`` field resolves
        its new target.
        """
        if ref_id is None:
            return None
        cache_key = (name, ref_id)
        cache = self._ref_cache
        try:
            cached = cache.get(cache_key)
        except TypeError:
            # Unhashable id values cannot index the referenced-entities map.
            return None
        if cached is not None:
            return cached
        ref_map = self._referenced_entities or {}
        for type_key in (name, name + "s"):
            type_bucket = ref_map.get(type_key)
            if type_bucket and ref_id in type_bucket:
                wrapped = WeclappEntity.from_row(
                    type_bucket[ref_id],
                    referenced_entities=ref_map,
                    attribute_definitions=self._attribute_definitions,
                )
                cache[cache_key] = wrapped
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
                cache[cache_key] = wrapped
                return wrapped
        return None

    # ------------------------------------------------------------------
    # Write access
    # ------------------------------------------------------------------

    @override
    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        index = getattr(self, "_custom_attr_index", None) or {}
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

    @override
    def __setitem__(self, key: str, value: Any) -> None:
        """Apply the customAttribute write contract to normal dict assignment."""
        index = getattr(self, "_custom_attr_index", None) or {}
        if key in index:
            self._set_custom_attribute_value(key, value)
            return
        if (
            isinstance(key, str)
            and key not in self
            and key in getattr(self, "_defined_custom_attr_names", set())
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

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_payload(self) -> JsonDict:
        """Return a plain API payload, primarily for updating this entity.

        Normal entity fields are preserved, including response metadata such as
        ``id`` and ``version``. A payload produced from a read entity is
        therefore not automatically a valid create payload; construct creates
        explicitly and omit read-only metadata.

        - Flattened customAttribute fields are folded back into the
          ``customAttributes`` array under the originally populated typed-value
          field, preserving any current edits — at every level of nesting.
        - Keys merged in from ``additionalProperties`` are dropped.
        - Cached resolved reference objects are not included.
        - Nested ``WeclappEntity`` values (in dict or list fields) are
          recursively unwrapped via their own ``to_payload``.

        :raises ValueError: If read-only customAttributes were changed,
            removed, replaced, or moved, if a flattened attribute's raw slot was
            moved or removed, or if a raw ``customAttributes`` item is malformed.
        """
        payload: JsonDict = {}
        flattened = set(self._custom_attr_index.keys())
        synthetic = self._additional_property_keys | flattened
        for key, value in self.items():
            if key in synthetic or key == "customAttributes":
                continue
            payload[key] = self.unwrap(value)

        custom_attributes_src = self.get("customAttributes")
        if isinstance(custom_attributes_src, list):
            rebuilt = [
                self._sanitize_custom_attribute(item, position)
                for position, item in enumerate(custom_attributes_src)
            ]

            # Direct edits of the raw customAttributes list are unsupported,
            # but detect them for read-only definitions before a request leaves
            # the process. This also catches in-place list/dict mutations.
            for position, original in self._read_only_custom_attr_positions.items():
                original_sanitized = self._sanitize_custom_attribute(original, position)
                if (
                    position >= len(rebuilt)
                    or rebuilt[position].get("attributeDefinitionId")
                    != original_sanitized.get("attributeDefinitionId")
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
                current_attr_def_id = rebuilt[position].get("attributeDefinitionId")
                if attr_def_id is not None and current_attr_def_id != attr_def_id:
                    raise ValueError(
                        f"customAttribute '{name}' was moved or replaced in the "
                        "raw customAttributes list. Edit the flattened field "
                        "instead."
                    )
                if name in self._read_only_custom_attrs:
                    definition = self._attribute_definitions.get(attr_def_id)
                    original = self._read_only_custom_attr_positions.get(position, {})
                    original_value, _ = self._extract_custom_attribute_value(original, definition)
                    if self.unwrap(self.get(name)) != self.unwrap(original_value):
                        raise ValueError(
                            f"customAttribute '{name}' is read-only according to "
                            "its customAttributeDefinition and cannot be changed."
                        )
                    continue
                rebuilt[position][value_field] = self.unwrap(self.get(name))
                rebuilt[position] = self._sanitize_custom_attribute(rebuilt[position], position)

            # Once attributeType is known, emit exactly its active typed slot.
            # This prevents stale legacy slots from creating an ambiguous wire
            # payload. Without a usable definition, preserve every allowed v2
            # field because the client cannot safely infer the active one.
            for position, item in enumerate(rebuilt):
                item_def_id: Any = item.get("attributeDefinitionId")
                item_definition = self._attribute_definitions.get(item_def_id)
                attribute_type = str(
                    item_definition.get("attributeType") if item_definition else ""
                ).upper()
                active_field = self._CUSTOM_ATTRIBUTE_TYPE_FIELDS.get(attribute_type)
                if active_field:
                    normalized: JsonDict = {}
                    if "attributeDefinitionId" in item:
                        normalized["attributeDefinitionId"] = item["attributeDefinitionId"]
                    normalized[active_field] = item.get(active_field)
                    rebuilt[position] = normalized

            payload["customAttributes"] = rebuilt

        elif self._read_only_custom_attr_positions:
            raise ValueError(
                "customAttributes contains read-only definitions and cannot be "
                "removed or replaced with a non-list value."
            )

        return payload

    @classmethod
    def _sanitize_custom_attribute(cls, item: Any, position: int) -> JsonDict:
        """Return one schema-exact v2 ``customAttribute`` payload item."""
        # ValueError (not TypeError) is the established public contract here.
        if not isinstance(item, dict):
            raise ValueError(
                f"customAttributes[{position}] must be an object, got {type(item).__name__}."
            )

        sanitized: JsonDict = {}
        for field in cls._CUSTOM_ATTRIBUTE_FIELDS:
            if field not in item:
                continue
            value = cls.unwrap(item[field])
            nested_fields = cls._CUSTOM_ATTRIBUTE_NESTED_FIELDS.get(field)
            if nested_fields and value is not None:
                if not isinstance(value, list):
                    raise ValueError(
                        f"customAttributes[{position}].{field} must be a list or null."
                    )
                nested_values: list[JsonDict] = []
                for nested_position, nested_item in enumerate(value):
                    if not isinstance(nested_item, dict):
                        raise ValueError(
                            f"customAttributes[{position}].{field}"
                            f"[{nested_position}] must be an object."
                        )
                    nested_values.append(
                        {
                            nested_field: cls.unwrap(nested_item[nested_field])
                            for nested_field in nested_fields
                            if nested_field in nested_item
                        }
                    )
                value = nested_values
            sanitized[field] = value
        return sanitized

    @classmethod
    def unwrap(cls, value: Any) -> Any:
        """Recursively convert entity wrappers back into plain JSON containers.

        ``WeclappEntity`` values become their :meth:`to_payload` (flattened
        customAttributes folded back, merged additionalProperties dropped);
        lists and tuples become lists; dicts are copied; scalars pass through.
        """
        match value:
            case WeclappEntity():
                return value.to_payload()
            case list() | tuple():
                return [cls.unwrap(item) for item in value]
            case dict():
                return {key: cls.unwrap(item) for key, item in value.items()}
            case _:
                return value

    @classmethod
    def _unwrap(cls, value: Any) -> Any:
        """Backward-compatible alias of :meth:`unwrap`."""
        return cls.unwrap(value)


@dataclass
class WeclappResponse:
    """Structured response from the weclapp API.

    This class handles the response structure when using ``additionalProperties``
    and ``referencedEntities`` parameters in API requests.

    Attributes:
        result: The wrapped rows (a list for collection reads, a single
            :class:`WeclappEntity` for ``get(entity, entity_id)``). Instances
            built directly via :meth:`from_api_response` carry the raw dict
            rows of ``response_data`` until the client wraps them.
        additional_properties: Optional ``{property: [value_per_row, ...]}``
            mapping if requested.
        referenced_entities: Optional ID-indexed view of referenced entities
            (``{type: {id: entity_dict}}``) if requested.
        raw_response: The complete raw response from the API.
    """

    result: list[WeclappEntity] | WeclappEntity
    additional_properties: dict[str, list[Any]] | None = None
    referenced_entities: dict[str, dict[str, JsonDict]] | None = None
    raw_response: JsonDict | None = None

    @property
    def raw_referenced_entities(self) -> JsonDict | None:
        """Return weclapp's native ``referencedEntities`` mapping.

        ``referenced_entities`` remains the backwards-compatible ID-indexed
        view used by lazy ``*Id`` resolution. Colon projections are allowed
        to omit the referenced entity's ``id``; those entries cannot be
        indexed, but remain available through this raw view.
        """
        if not isinstance(self.raw_response, dict):
            return None
        value = self.raw_response.get("referencedEntities")
        return value if isinstance(value, dict) else None

    @classmethod
    def from_api_response(cls, response_data: JsonDict) -> Self:
        """Create a response instance from a raw API response dictionary.

        Args:
            response_data: The raw API response dictionary.

        Returns:
            An instance with parsed data. ``referencedEntities`` lists are
            re-indexed by ``id``; entries without an ``id`` are only available
            through :attr:`raw_referenced_entities`.
        """
        # Raw rows are dicts; WeclappEntity is a dict subclass, so the declared
        # type holds for every read operation (the client wraps before returning).
        result = cast("list[WeclappEntity] | WeclappEntity", response_data.get("result", []))
        additional_properties = response_data.get("additionalProperties")

        raw_referenced_entities = response_data.get("referencedEntities")
        referenced_entities: dict[str, dict[str, JsonDict]] | None = None

        if isinstance(raw_referenced_entities, dict) and raw_referenced_entities:
            referenced_entities = {}
            for entity_type, entities_list in raw_referenced_entities.items():
                bucket: dict[str, JsonDict] = {}
                referenced_entities[entity_type] = bucket
                if not isinstance(entities_list, list):
                    continue
                for entity in entities_list:
                    if isinstance(entity, dict) and entity.get("id") is not None:
                        bucket[entity["id"]] = entity

        return cls(
            result=result,
            additional_properties=additional_properties,
            referenced_entities=referenced_entities,
            raw_response=response_data,
        )
