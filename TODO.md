# Feature requests

- Bulk-/threaded writes: geplant für 1.1 als explizite, nicht-automatische API (Entscheidung Markus 08.10.2026)
- Async-Client (httpx): v2, bricht `session`-Konsumenten

## Road to v1.0.0 — umgesetzt am 08.10.2026 (Branch `claude/weclapp-client-library-v1-158489`)

Plan: `docs/review-and-roadmap-v1.0.0.md`. Offen: Review-PR, Freigabe Markus, PyPI-Release `v1.0.0`, Konsumenten-Pins.

- [x] Phase 0 — entfällt (Entscheidung Markus 08.10.2026: kein Hotfix, direkt 1.0.0); PR #7 nach Merge als überholt schließen
- [x] Phase 1 — 0.7.0 Adaptive Reads: Controller-Wachstum reparieren (P0-B), Abbau pro Epoche, `max_concurrency` als Deckel, 429-Budget getrennt + Backoff-Deckel 60 s, Writes warten auf Cooldown, Timeout-Header < Client-Timeout, `threaded="auto"`, `sort=id`-Default, Pfad-Encoding, Definitions-Cache-Lock, Fake-Clock-Tests, Migrationsnotiz, Konsumenten-RC-Test
- [x] Phase 2 — 0.8.0 Observability: `on_response`/`RequestMetrics`, `client.stats`, `session=`/`before_request`, Fehler-Unterklassen mit `outcome_unknown`, Entity-Fixes (`_ref_cache`, `copy`), Private-API-Nutzung in Kern-Konsumenten auf null
- [x] Phase 3 — 0.9.0 Batching: Sandbox-Messung Paketgröße/URL-Limit, `get_by_ids`, `strategy="ids"`, `max_records`, `iter_keyset`
- [x] Phase 4 — 1.0.0 Freeze: `src/weclappy/`-Paket, `py.typed`, `__version__`, keyword-only/Naming-Konsolidierung, mypy/ruff/Coverage-Gate, Python ≥ 3.10, Policies (SemVer, Deprecation, Security), `RELEASING.md`, OpenAPI-Snapshots raus, `1.0.0rc1` eine Woche im Einsatz

## Dynamic entity model (0.5.0 / 0.6.0) — abgeschlossen

- [x] Phase 1–5 (WeclappEntity, id-eq-Routing, Referenz-Auflösung, Docs, verschachtelte Entities)
