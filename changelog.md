# Changelog

All notable changes to the weclappy project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2023-11-15

### Fixed
- Corrected the parameter name for referenced entities from `referencedEntities` to `includeReferencedEntities` to match the weclapp API

### Added
- Support for weclapp API's `additionalProperties` parameter in `get_all` method
- Support for weclapp API's `includeReferencedEntities` parameter in `get_all` method
- New `WeclappResponse` class to handle structured API responses
- New example scripts demonstrating the new features:
  - `get_with_additional_properties.py` for sales orders
  - `get_all_sales_invoices.py` for sales invoices with referenced entities
  - `get_articles_with_properties.py` for articles with both additionalProperties and referencedEntities
- Enhanced documentation in README.md

### Note
- Both `additional_properties` and `referenced_entities` parameters accept either:
  - A list of strings (e.g., `["customer", "positions"]`)
  - A comma-separated string (e.g., `"customer,positions"`)
- The `additional_properties` parameter (passed as `additionalProperties` to the API) specifies which property names to include in the response
- The `referenced_entities` parameter (passed as `includeReferencedEntities` to the API) specifies which property paths (e.g., `"customerId,orderItems.articleId"`) to include as referenced entities
- Both parameters are only available when fetching lists of entities, not when fetching by ID

### Changed
- Updated `get` and `get_all` methods with new optional parameters while maintaining backward compatibility
- Improved error handling for API responses
- Enhanced example scripts to demonstrate both basic and advanced usage

## [0.1.4] - 2023-10-20

### Added
- Support for calling custom API methods with `call_method`
- Ability to download PDFs and binary files
- Better error handling with detailed error messages

### Fixed
- Issue with pagination when using filters
- Connection pool management for better performance

## [0.1.3] - 2023-09-15

### Added
- Threaded pagination for improved performance when fetching large datasets
- Support for custom page sizes
- Configurable connection pool settings

### Changed
- Improved logging with more detailed debug information
- Better handling of API rate limits

## [0.1.2] - 2023-08-10

### Added
- Support for all CRUD operations (Create, Read, Update, Delete)
- Query parameter support for filtering results
- Basic pagination support

### Fixed
- Authentication token handling
- URL path construction

## [0.1.1] - 2023-07-05

### Added
- Initial implementation of the weclapp API client
- Basic GET functionality
- Simple error handling

### Changed
- Project structure and organization

## [0.1.0] - 2023-06-20

### Added
- Initial project setup
- Basic project structure
- Documentation framework
