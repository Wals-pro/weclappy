# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## [1.0.0] - 2026-10-08

First stable release. The public API is now frozen under Semantic Versioning;
see the [versioning and support policy](README.md#versioning-and-support-policy).

> **Note:** the `[0.7.0] - 2026-07-17` entry that existed on the development
> branch was never released to PyPI. Its changes are included below; 1.0.0 is
> the direct successor of 0.6.0.

### Migration

1.0.0 contains breaking changes for every 0.x user. Read
[Migration from 0.x](README.md#migration-from-0x) before upgrading, and pin
`weclappy>=1.0,<2`.

### Deprecated
- The `id=` keyword on `get`, `put`, `delete`, `upload` and `download` still
  works but emits a `DeprecationWarning`; use `entity_id=`. Removed in 2.0.

### Security
- **Writes are never retried after an ambiguous outcome.** 0.6.0 mounted a
  urllib3 `Retry` that repeated `POST`, `PUT` and `DELETE` on 500, 502, 503, 504
  and 429, so a write that weclapp had already committed could be executed
  twice (duplicate invoices, double stock bookings). Writes are now retried
  only when the connection was provably never established.
- Redirects are never followed, so a `307`/`308` cannot replay a write body
  and the `AuthenticationToken` cannot follow a redirect to another host.
- Endpoints must be relative and same-origin; absolute URLs, other hosts,
  `..` segments and fragments raise `ValueError`.
- `entity_id` and `action` path segments are percent-encoded; values with `/`,
  `?` or `#` are rejected, so untrusted ids cannot reach other endpoints.
- Logs and `RequestMetrics` never contain the API key, query strings or
  bodies.
- MIT license, private vulnerability reporting, and PyPI Trusted Publishing
  with tag, version and changelog gates.

### Added
- Adaptive load control: `ConcurrencyController` (AIMD per epoch driven by
  `X-Weclapp-Wait-Ms` and `X-Weclapp-Wait-Reason`), `ConcurrencySettings`,
  `ConcurrencySnapshot` and `Signal`. `Weclapp(max_concurrency=10)` sets the
  ceiling; `Weclapp(concurrency=...)` shares one controller between clients
  of the same tenant. Writes wait for an active 429 cooldown.
- `RetryPolicy` with separate budgets: transient (5xx and transport, 3 × 0.3 s
  base), rate limit (429, 5 × 2 s base) and weclapp problem types
  (`request_timeout`, `persistence`, 1). Every delay is capped by
  `max_backoff` (60 s). New constructor arguments `rate_limit_retries`,
  `rate_limit_backoff`, `max_backoff`, `retry_policy`.
- `get_all(threaded="auto")`, `max_records`, `strategy="ids"`; `get_by_ids()`
  with 500-id / 8000-byte chunks measured on the weclapp sandbox;
  `iter_keyset()` (`sort=id` + `id-gt`); `count()`.
- Unofficial endpoints, clearly labelled: `query()`, `query_count()`,
  `batch_query()` returning `BatchResult`, `openapi(include_hidden=...)`.
- Observability: `on_response` hook with `RequestMetrics` per physical
  attempt, `client.stats` (`StatsSnapshot`), `reset_stats()`.
- Extension points: `session=`, `before_request=` hook with
  `OutgoingRequest`, `user_agent=`, and the public `request()` escape hatch
  with per-request `headers` and `timeout` (float or `(connect, read)`).
- `Weclapp.for_tenant(tenant, api_key, *, api_version=2)`.
- Error hierarchy: `WeclappError` base, `WeclappTransportError`
  (`request_sent`, `outcome_unknown`), `WeclappRateLimitError`,
  `WeclappNotFoundError`, `WeclappValidationError`,
  `WeclappOptimisticLockError`, `WeclappRequestTimeoutError`,
  `WeclappAuthenticationError`, `WeclappRedirectError`,
  `WeclappPaginationError`, `WeclappConcurrencyTimeoutError`, and
  `WeclappAPIError.from_response()`.
- `WeclappEntity.unwrap()` as public API, `refresh_attribute_definitions()`,
  `WeclappResponse.raw_referenced_entities`, `entity.additional_properties`.
- `__version__`, `py.typed`, `User-Agent: weclappy/<version>`, and default
  headers `X-Weclapp-Wait-Timeout-Ms: 30000` and
  `X-Weclapp-Request-Timeout-Ms: 110000`.
- `close()` and context-manager support; `iter_all()` generator.
- Guarded examples for load management, unofficial endpoints and a read-only
  live contract probe; `docs/load-management.md`.

### Changed (BREAKING)
- Python ≥ 3.12 is required (was ≥ 3.9).
- The single module `weclappy.py` became the package `src/weclappy/`. Import
  public names from `weclappy`.
- Every constructor argument after `api_key` is keyword-only. In `get_all`
  everything after `params` is keyword-only; `return_weclapp_response` in
  `get`, `method`/`data`/`params` in `call_method` and
  `content_type`/`filename` in `upload` are keyword-only.
- Parameter renames: `id` → `entity_id` and `endpoint` → `entity`; positions
  are unchanged.
- `get_all()` defaults to `threaded="auto"` (0.6.0: sequential): page 1 is
  read sequentially and only a full first page triggers `/count` and
  concurrent fetching of the remaining pages.
- `get_all()`, `iter_all()` and `strategy="ids"` add `sort=id` when neither
  `sort` nor `orderBy` is given; `{"sort": None}` opts out.
- `get_all(max_workers=)` must not exceed `max_concurrency`; it raises
  `ValueError` instead of silently capping.
- Writes (`POST`, `PUT`, `DELETE`, uploads, `call_method(method="POST")`) are
  not retried on 5xx, 429, read timeouts or dropped connections; an unknown
  outcome raises `WeclappTransportError` with `outcome_unknown=True`.
- Redirects are not followed; a 3xx raises `WeclappRedirectError`.
- Absolute endpoint URLs are rejected.
- `base_url` must be the API root ending in `/webapp/api/v<N>`; a bare tenant
  host raises `ValueError` instead of producing redirects on every request.
- `_send_request()` and `_check_response()` were removed; use `request()`,
  `before_request`/`on_response` or `session=`.
- `WeclappAPIError.wait_ms` is a `float` (0.7.0 branch: `str`).
- Duplicate ids between pages and count shortfalls raise
  `WeclappPaginationError` (a `WeclappAPIError` subclass).
- Custom-attribute flattening uses `customAttributeDefinition.attributeKey`;
  definitions are loaded once per client under a lock; transient failures
  propagate instead of silently disabling flattening.

### Fixed
- **Write retries in 0.6.0** on 5xx and 429 (see Security).
- **Controller stuck at 1** (0.7.0 branch): after a single 429 or `load`
  signal the target could never grow again, making long-lived clients serial
  forever. Growth is now measured per saturated epoch and works at every
  target.
- **Uncapped `Retry-After`** (0.7.0 branch): `Retry-After: 3600` blocked all
  reads for an hour, and `inf` crashed every later `acquire()` with
  `OverflowError`. Every delay is now capped at `max_backoff` and non-finite
  values are ignored.
- Decreases are applied at most once per epoch, so a burst of `load`
  responses no longer collapses the target in one round trip.
- `X-Weclapp-Request-Timeout-Ms` stays below the client timeout and is
  lowered for shorter per-request timeouts.
- Read permits are released by a context manager on every exit path, and
  waiting for a permit is bounded by the client timeout
  (`WeclappConcurrencyTimeoutError`) instead of blocking indefinitely.
- `POST …/query`, `POST …/count` and `POST batch/query` are treated as reads.
- Resolved references are cached per `(field, id)`, so reassigning a `*Id`
  field resolves the new target.
- Concurrent cold starts load `customAttributeDefinition` once.

### Removed
- Python 3.9, 3.10 and 3.11 support.
- The repository-root `__init__.py` and the module `weclappy.py`.
- Package-root constants `DEFAULT_MAX_WORKERS`, `DEFAULT_MAX_RETRIES`,
  `DEFAULT_BACKOFF_FACTOR`, `SAFE_RETRY_METHODS`, `TRANSIENT_STATUS_CODES`.
- Private `_send_request()` and `_check_response()`; positional
  `threaded`/`max_workers`/`return_weclapp_response` in `get_all`.

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
