# Feature requests

- Threaded writing
- Generators

## Dynamic entity model (0.5.0)

Plan: `~/.claude/plans/gentle-hugging-torvalds.md`

- [x] Phase 1 — `WeclappEntity` primitive with customAttribute flatten/round-trip
- [x] Phase 2 — Route every `get`/`get_all` through `id-eq`; wrap rows; synthesize 404
- [x] Phase 3 — Lazy `*Id` → object auto-resolve via referencedEntities
- [x] Phase 4 — Docs (README, CHANGELOG, CLAUDE.md scope), bump to `0.5.0`
- [x] Phase 5 — Nested entity wrapping: recursive dict/list wrap, nested `*Id` resolve, nested customAttribute round-trip (0.6.0)