# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## [0.6.0] - 2026-04-25

### Added
- `WeclappEntity` recursively wraps nested dict and list-of-dict values, so attribute access, customAttribute flattening, and `*Id` resolution work at every level. Examples:
  - `order.orderItems[0].article.articleNumber` resolves nested `*Id` against the same `referencedEntities` map.
  - `order.orderItems[0].myCustomField` reads a flattened nested customAttribute.
  - Editing a nested customAttribute and calling `order.to_payload()` rebuilds the nested `customAttributes` array under the original typed-value field, alongside the parent payload.
  - Nested wrappers preserve identity (`order.orderItems[0] is order.orderItems[0]`).
- `from_row` is idempotent: passing an already-wrapped value returns it unchanged.
- Defensive `_MAX_WRAP_DEPTH = 64` guard on pathologically deep / cyclic input.

### Fixed (battle-tested against live tenant)
- `*Id` auto-resolution now falls back to a flat-id lookup across all `referencedEntities` buckets when the bucket name does not match the field-name convention. weclapp uses unified types under different field names (e.g. `customerId`, `invoiceRecipientId`, and `recipientPartyId` all resolve to the `party` bucket), so the previous name-only match returned `None` for the most common case.
- `customAttribute` flattening now lazily fetches and caches `customAttributeDefinition` on first wrapped read, and uses the definition's `attributeKey` as the flattened field name. Real weclapp responses do not include `internalName` on entity-level `customAttributes` — only `attributeDefinitionId` plus the typed-value field — so 0.6.0's flatten silently no-op'd against real data without this lookup.

### Notes
- Field names that collide with `dict` methods (`items`, `keys`, `values`, `get`, `pop`, `update`, ...) are only reachable via bracket access at every nesting level (e.g. `entity["items"][0]`), since attribute access resolves to the bound method. This is inherent to subclassing `dict`.
- The raw `customAttributes` list itself is intentionally not wrapped — its dicts are metadata records owned by the flatten / round-trip pass.
- The lazy `customAttributeDefinition` fetch issues at most one extra HTTP call per `Weclapp` client lifetime, and only when at least one read returns a `customAttributes` entry without `internalName`. If the fetch fails, flattening degrades gracefully (a warning is logged, raw `customAttributes` remain accessible via bracket access).

## [0.5.0] - 2026-04-25

### Added
- New `WeclappEntity` class — a `dict` subclass returned by `get` and `get_all` that adds attribute-style access (`shipment.id`, `shipment.customer.name`).
  - `customAttributes` are flattened to top-level fields keyed by their `internalName`. The original list remains under `entity['customAttributes']`.
  - Per-row `additionalProperties` values are merged into each entity at the top level.
  - `*Id` fields lazily resolve to the matching object from `referencedEntities` (e.g. `entity.customer` looks up the object referenced by `entity.customerId`). Raw `*Id` fields are preserved.
  - Flattened customAttribute fields are writable; `entity.to_payload()` rebuilds the original `customAttributes` array under the originally populated typed-value field, ready for `put`/`post`.
  - On collisions (customAttribute `internalName` or `additionalProperty` name matching a built-in field), the built-in wins and a warning is logged.
- `WeclappEntity` is exported from the package root.

### Changed (BREAKING)
- `client.get(endpoint, id=X)` now routes via `GET {endpoint}?id-eq=X&pageSize=1` instead of `GET {endpoint}/id/{X}`. This guarantees `additionalProperties` and `referencedEntities` are always available to the entity wrapper.
- Reads (`get`, `get_all`) now return `WeclappEntity` (or a list of them) instead of plain dicts. Existing dict access (`entity['id']`, `entity.get(...)`) keeps working because `WeclappEntity` subclasses `dict`. Code that constructs new dicts via `dict(entity)` or relies on the exact return type may need adjustment.
- `WeclappResponse.result` likewise now contains `WeclappEntity` objects (or a single one when fetching by id). The unprocessed payload is still available via `WeclappResponse.raw_response`.
- `id-eq` validates id format on the weclapp side; lookups with non-numeric / out-of-range ids that previously returned 404 may now return 400. The 404 contract is otherwise preserved: an empty result for a valid id raises `WeclappAPIError` with `is_not_found == True` and a synthetic 404 response.

### Notes
- `*Id` auto-resolution applies to top-level fields only. Nested resolution inside list fields (e.g. `positions[].articleId`) is out of scope for 0.5.0.

## [0.4.1] - 2026-03-06

### Added
- Added `@overload` typing for `get()` and `get_all()` so static type checkers can narrow return types based on `return_weclapp_response`.

### Changed
- Documented official support for Python 3.9+ in the main README and test documentation.

## [0.4.0] - 2026-03-06

### Added
- HTTP request timing logging: every API call logs method, endpoint path, status code, and duration in milliseconds
- Slow request detection: calls taking >= 2000ms log at WARNING level with `[API_SLOW]` prefix; all others log at INFO with `[API]` prefix
- Configurable slow threshold via `slow_threshold_ms` parameter in `Weclapp.__init__()` (default: 2000ms)
- Timing instrumentation covers both `_send_request()` and the direct count endpoint call in threaded `get_all`
- Query parameters are stripped from logged paths for security (tokens, filters never appear in logs)
- Default request timeout of 120 seconds for all HTTP requests (aligned with weclapp recommendation of at least one minute). Callers can override by passing `timeout` in request kwargs.
- Extend existing Retry logic to also handle 429 responses.
- Added optional params parameter to `post()` for query parameters like `dryRun=true`, consistent with `put()` and `delete()`.
- Documentation on how to build
- Remove generated changelog

### Fixed
- Fixed `examples/get_with_both_parameters.py` to handle referenced entity responses returned as dictionaries keyed by id.
- Updated `examples/crud_operations.py` to use the current `party` endpoint instead of the deprecated `contact` endpoint, with cleanup of temporary test data.

## [0.3.1] - 2026-01-31

### Fixed
- Fixed missing project description on PyPI due to case-sensitive README.md filename (renamed from readme.md)

## [0.3.0] - 2025-01-31

### Added
- New `upload()` method for uploading documents and images to weclapp entities
  - Automatic content type inference from filename extension
  - Optional explicit content type override with mismatch warning
  - Follows polymorphic pattern with `id` and `action` parameters
- New `download()` method as a convenience wrapper for binary downloads
  - Defaults to `download` action when only `id` is provided
  - Supports custom actions like `downloadLatestSalesInvoicePdf`
- `MIME_TYPES` dictionary with 37 common file type mappings
- `infer_content_type()` helper function for content type inference
- Extended binary response handling for images, audio, video, and archives
- New example script `examples/upload_document.py`
- Comprehensive unit tests for upload/download functionality
- Library design patterns documented in README

### Changed
- Updated README with Document & Image Uploads section
- Updated README with Binary Downloads section
- Updated README with Library Design Patterns section
- Exported `MIME_TYPES` and `infer_content_type` from package

## [0.2.1] - 2024-07-14 (approximate)

### Fixed
- Issue in get_all threaded fetching

## [0.2.0] - 2024-07-14

### Added
- Support for weclapp API's `additionalProperties` parameter in `get_all` method
- Support for weclapp API's `includeReferencedEntities` parameter in `get_all` method
- New `WeclappResponse` class to handle structured API responses
- New example scripts demonstrating the new features
- Enhanced documentation in README.md
- New integration and unit tests for additionalProperties and includeReferencedEntities

### Changed
- Updated `get` and `get_all` methods with new optional parameters
- Improved error handling for API responses
- Enhanced example scripts
- Project version updated to 0.2.0

### Fixed
- Corrected parameter name for referenced entities
- Fixed handling of additionalProperties and referencedEntities across multiple pages

## [0.1.4] - 2024-05-07 (approximate)

### Added
- Support for calling custom API methods with `call_method`
- Ability to download PDFs and binary files
- Better error handling with detailed error messages

### Fixed
- Issue with pagination when using filters
- Connection pool management for better performance
- Bugfix in PUT method

## [0.1.3] - 2024-04-01 (approximate)

### Added
- Threaded pagination for improved performance when fetching large datasets
- Support for custom page sizes
- Configurable connection pool settings

### Changed
- Improved logging with more detailed debug information
- Better handling of API rate limits

## [0.1.2] - 2024-03-27 (approximate)

### Added
- Support for all CRUD operations (Create, Read, Update, Delete)
- Query parameter support for filtering results
- Basic pagination support

### Fixed
- Authentication token handling
- URL path construction

## [0.1.1] - 2024-02-07 (approximate)

### Added
- Initial implementation of the weclapp API client
- Basic GET functionality
- Simple error handling
- Example scripts and fixes

### Changed
- Project structure and organization

## [0.1.0] - 2024-02-05 (approximate)

### Added
- Initial project setup
- Basic project structure
- Documentation framework 