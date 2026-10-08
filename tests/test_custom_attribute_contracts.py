"""Offline contracts for schema-safe customAttribute round-tripping."""

import pytest

from weclappy import WeclappEntity

TYPE_CASES = [
    ("BOOLEAN", "booleanValue", False, True),
    ("DATE", "dateValue", 0, 1_700_000_000_000),
    ("DECIMAL", "numberValue", "0", "12.50"),
    ("INTEGER", "numberValue", "0", "12"),
    ("ENTITY", "entityId", "", "entity-2"),
    (
        "REFERENCE",
        "entityReferences",
        [],
        [{"entityId": "article-2", "entityName": "article"}],
    ),
    ("LIST", "selectedValueId", "", "choice-2"),
    (
        "MULTISELECT_LIST",
        "selectedValues",
        [],
        [{"id": "choice-2"}, {"id": "choice-3"}],
    ),
    ("LARGE_TEXT", "stringValue", "", "Longer text"),
    ("STRING", "stringValue", "", "Text"),
    ("URL", "stringValue", "", "https://example.test"),
]


def make_entity(attribute_type, value_field, value, *, read_only=False):
    return WeclappEntity.from_row(
        {
            "id": "entity-1",
            "customAttributes": [
                {
                    "attributeDefinitionId": "definition-1",
                    "internalName": "legacy_name",
                    "legacyMetadata": "must-not-be-sent",
                    value_field: value,
                }
            ],
        },
        attribute_definitions={
            "definition-1": {
                "id": "definition-1",
                "attributeKey": "contract_field",
                "attributeType": attribute_type,
                "readOnly": read_only,
            }
        },
    )


@pytest.mark.parametrize(("attribute_type", "value_field", "initial", "replacement"), TYPE_CASES)
def test_all_v2_types_preserve_boundary_values_and_round_trip_existing_fields(
    attribute_type, value_field, initial, replacement
):
    entity = make_entity(attribute_type, value_field, initial)

    assert entity.contract_field == initial
    untouched = entity.to_payload()["customAttributes"][0]
    assert untouched == {
        "attributeDefinitionId": "definition-1",
        value_field: initial,
    }

    entity.contract_field = replacement
    edited = entity.to_payload()["customAttributes"][0]
    assert edited == {
        "attributeDefinitionId": "definition-1",
        value_field: replacement,
    }


@pytest.mark.parametrize(
    ("attribute_type", "value_field", "initial"),
    [
        (attribute_type, value_field, replacement)
        for attribute_type, value_field, _, replacement in TYPE_CASES
    ],
)
def test_all_v2_types_can_be_explicitly_cleared_with_none(attribute_type, value_field, initial):
    entity = make_entity(attribute_type, value_field, initial)

    entity.contract_field = None

    custom_attribute = entity.to_payload()["customAttributes"][0]
    assert value_field in custom_attribute
    assert custom_attribute[value_field] is None


def test_payload_preserves_every_allowed_field_and_removes_unknown_metadata():
    item = {
        "attributeDefinitionId": "definition-1",
        "stringValue": "",
        "numberValue": "0",
        "booleanValue": False,
        "dateValue": 0,
        "entityId": "",
        "entityReferences": [
            {
                "entityId": "article-1",
                "entityName": "article",
                "legacyLabel": "Article one",
            }
        ],
        "selectedValueId": "",
        "selectedValues": [{"id": "choice-1", "legacyLabel": "Choice one"}],
        "internalName": "legacy_name",
        "version": "legacy-version",
    }
    entity = WeclappEntity.from_row({"id": "entity-1", "customAttributes": [item]})

    custom_attribute = entity.to_payload()["customAttributes"][0]

    assert set(custom_attribute) == set(WeclappEntity._CUSTOM_ATTRIBUTE_FIELDS)
    assert custom_attribute["booleanValue"] is False
    assert custom_attribute["dateValue"] == 0
    assert custom_attribute["stringValue"] == ""
    assert custom_attribute["entityReferences"] == [
        {"entityId": "article-1", "entityName": "article"}
    ]
    assert custom_attribute["selectedValues"] == [{"id": "choice-1"}]


def test_definition_type_is_authoritative_when_legacy_slots_disagree():
    entity = WeclappEntity.from_row(
        {
            "customAttributes": [
                {
                    "attributeDefinitionId": "definition-1",
                    "stringValue": "stale legacy value",
                    "booleanValue": None,
                }
            ]
        },
        attribute_definitions={
            "definition-1": {
                "attributeKey": "enabled",
                "attributeType": "BOOLEAN",
            }
        },
    )

    assert entity.enabled is None
    entity.enabled = False
    custom_attribute = entity.to_payload()["customAttributes"][0]
    assert custom_attribute == {
        "attributeDefinitionId": "definition-1",
        "booleanValue": False,
    }


def test_read_only_definition_rejects_attribute_and_item_assignment_locally():
    entity = make_entity("STRING", "stringValue", "original", read_only=True)

    with pytest.raises(AttributeError, match=r"read-only.*customAttributeDefinition"):
        entity.contract_field = "changed"
    with pytest.raises(AttributeError, match=r"read-only.*customAttributeDefinition"):
        entity["contract_field"] = "changed"

    assert entity.to_payload()["customAttributes"][0]["stringValue"] == "original"


def test_read_only_definition_detects_raw_and_in_place_mutation_before_write():
    raw_entity = make_entity("STRING", "stringValue", "original", read_only=True)
    raw_entity["customAttributes"][0]["stringValue"] = "changed"
    with pytest.raises(ValueError, match=r"read-only.*customAttributeDefinition"):
        raw_entity.to_payload()

    list_entity = make_entity(
        "REFERENCE",
        "entityReferences",
        [{"entityId": "article-1", "entityName": "article"}],
        read_only=True,
    )
    list_entity.contract_field.append({"entityId": "article-2", "entityName": "article"})
    with pytest.raises(ValueError, match=r"read-only.*customAttributeDefinition"):
        list_entity.to_payload()


@pytest.mark.parametrize(
    "replacement",
    [
        [],
        [
            {
                "attributeDefinitionId": "other-definition",
                "stringValue": "original",
            }
        ],
        None,
    ],
)
def test_read_only_definition_cannot_be_removed_or_replaced(replacement):
    entity = make_entity("STRING", "stringValue", "original", read_only=True)

    entity["customAttributes"] = replacement

    with pytest.raises(ValueError, match=r"read-only.*(removed|replaced)"):
        entity.to_payload()


def test_read_only_definition_cannot_be_moved_to_another_slot():
    entity = WeclappEntity.from_row(
        {
            "customAttributes": [
                {
                    "attributeDefinitionId": "read-only-definition",
                    "stringValue": "locked",
                },
                {
                    "attributeDefinitionId": "writable-definition",
                    "stringValue": "editable",
                },
            ]
        },
        attribute_definitions={
            "read-only-definition": {
                "attributeKey": "locked",
                "attributeType": "STRING",
                "readOnly": True,
            },
            "writable-definition": {
                "attributeKey": "editable",
                "attributeType": "STRING",
                "readOnly": False,
            },
        },
    )

    entity["customAttributes"].reverse()

    with pytest.raises(ValueError, match=r"read-only.*moved"):
        entity.to_payload()


def test_writable_definitions_cannot_be_reordered_in_the_raw_list():
    entity = WeclappEntity.from_row(
        {
            "customAttributes": [
                {
                    "attributeDefinitionId": "definition-a",
                    "stringValue": "A",
                },
                {
                    "attributeDefinitionId": "definition-b",
                    "stringValue": "B",
                },
            ]
        },
        attribute_definitions={
            "definition-a": {
                "attributeKey": "field_a",
                "attributeType": "STRING",
                "readOnly": False,
            },
            "definition-b": {
                "attributeKey": "field_b",
                "attributeType": "STRING",
                "readOnly": False,
            },
        },
    )
    entity.field_a = "A-edited"
    entity["customAttributes"].reverse()

    with pytest.raises(ValueError, match=r"field_a.*moved or replaced"):
        entity.to_payload()


def test_missing_defined_attribute_has_an_explicit_existing_only_boundary():
    entity = WeclappEntity.from_row(
        {"id": "entity-1", "customAttributes": []},
        attribute_definitions={
            "definition-1": {
                "attributeKey": "not_on_entity",
                "attributeType": "STRING",
                "readOnly": False,
            }
        },
    )

    with pytest.raises(AttributeError, match="defined but is not present"):
        entity.not_on_entity = "new"
    with pytest.raises(AttributeError, match="defined but is not present"):
        entity["not_on_entity"] = "new"

    assert entity.to_payload()["customAttributes"] == []


def test_unresolved_legacy_attribute_is_still_sanitized_for_v2_payloads():
    entity = WeclappEntity.from_row(
        {
            "customAttributes": [
                {
                    "attributeDefinitionId": "unknown-definition",
                    "stringValue": "kept",
                    "internalName": None,
                    "legacyMetadata": "removed",
                }
            ]
        }
    )

    assert entity.to_payload()["customAttributes"] == [
        {
            "attributeDefinitionId": "unknown-definition",
            "stringValue": "kept",
        }
    ]


def test_malformed_custom_attribute_items_fail_before_transport():
    entity = WeclappEntity.from_row({"customAttributes": ["not-an-object"]})

    with pytest.raises(ValueError, match=r"customAttributes\[0\] must be an object"):
        entity.to_payload()


def test_additional_properties_namespace_is_a_read_only_plain_copy():
    entity = WeclappEntity.from_row(
        {"id": "entity-1"},
        additional_properties_for_row={
            "computed": {"score": 7, "details": [{"label": "stable"}]},
        },
    )

    additional = entity.additional_properties

    assert type(additional) is dict
    assert type(additional["computed"]) is dict
    assert type(additional["computed"]["details"][0]) is dict
    assert additional == {"computed": {"score": 7, "details": [{"label": "stable"}]}}
    additional["computed"]["score"] = 99
    assert entity.computed.score == 7
    with pytest.raises(AttributeError, match=r"read-only"):
        entity.additional_properties = {}


def test_additional_properties_namespace_excludes_values_not_merged_on_collision():
    entity = WeclappEntity.from_row(
        {"id": "entity-1", "status": "OPEN"},
        additional_properties_for_row={"status": "COMPUTED", "score": 7},
    )

    assert entity.status == "OPEN"
    assert entity.additional_properties == {"score": 7}
