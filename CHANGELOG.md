# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

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