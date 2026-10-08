# weclappy documentation

| Document | Content |
| --- | --- |
| [../README.md](../README.md) | Reference for the public API, configuration and migration from 0.x |
| [load-management.md](load-management.md) | weclapp's load-management contract, the adaptive controller, the retry policy and sandbox measurements |
| [review-and-roadmap-v1.0.0.md](review-and-roadmap-v1.0.0.md) | Review of 0.6.0/0.7.0 and the design decisions behind 1.0.0 (German, internal) |
| `weclapp-openapi.yaml`, `weclapp-openapi.json` | weclapp API v2 OpenAPI snapshots (see below) |

The OpenAPI snapshots are not part of the published package.

## weclapp OpenAPI snapshots

This directory contains the weclapp API v2 OpenAPI document in two equivalent
formats:

- `weclapp-openapi.yaml` is convenient for reading and repository searches.
- `weclapp-openapi.json` is convenient for tools that prefer JSON.

The files are snapshots of documentation published by weclapp. They are
included for offline endpoint lookup and are not generated or maintained as a
separate API contract by the `weclappy` project. The current official weclapp
documentation takes precedence if it differs from these snapshots.

The snapshot identifies itself as OpenAPI 3.0.1 and API version 2. Its embedded
documentation links to the official
[v2 changelog](https://www.weclapp.com/api/changelogV2.html).

When updating the snapshot:

1. obtain both formats from the same official API documentation release;
2. replace both files together without hand-editing generated schemas;
3. verify that `info.version` is `2` and the files parse successfully;
4. summarize the source and relevant API changes in the commit or pull request;
5. check that no tenant-specific server, credential, or private schema was
   included.

The current pair was last committed on 2026-01-31. The source export does not
embed a reliable generation date, so use the repository history when tracing a
particular snapshot.
