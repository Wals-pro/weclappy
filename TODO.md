# Roadmap and ideas

Active planning belongs in [GitHub issues](https://github.com/Wals-pro/weclappy/issues)
so the community can discuss scope, trade-offs, and ownership.

Good candidates for future work are small, generic improvements to reliability,
typing, observability, pagination, and documentation. Proposals should preserve
the request-like API and the single `requests` runtime dependency.

The project intentionally does not plan entity-specific workflow helpers,
generated ERP models, automatic parallel writes, or a large framework layer.
Those can be useful in applications, but keeping them outside `weclappy` makes
the client easier to understand and reuse.
