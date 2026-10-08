# weclappy: Review und Roadmap zu v1.0.0

Stand: 2026-10-08. Grundlage: `origin/main` 9dc2d8c (= PyPI 0.6.0), Branch `agent/adaptive-threaded-pagination` 620e222 (= Release-Kandidat 0.7.0), PR #7 (`fix/no-blind-write-retries`, Arne), Notion-Task „weclappy: optimale API-Nutzung" (Projekte-DB), Wissensbasis `walspro.core/ai/knowledge/weclapp/*` (Load Management, Community-Day-Vortrag Lanig, Praxis-Learnings), Konsumenten-Scan über `~/Projects`.

Zeilenangaben ohne Zusatz beziehen sich auf `weclappy.py` im 0.7.0-Branch (620e222); `main:` kennzeichnet 9dc2d8c.

> **Status 08.10.2026, Abend:** Alle Phasen sind im Branch `claude/weclapp-client-library-v1-158489` in einem Zug umgesetzt (Entscheidung Markus: kein 0.6.1-Hotfix, inoffizielle Endpunkte rein, Python ≥ 3.12, Bulk-Writes → 1.1, Async → v2). Ergebnis: Paket `src/weclappy/`, 878 Offline-Tests auf 3.12/3.13/3.14, Coverage 97 %, mypy strict, Live-Contract gegen die Acme-Sandbox grün. Die Befunde unten beschreiben den Stand *vor* der Umsetzung; Abweichungen von Abschnitt 5 und 6 sind im CHANGELOG und in `docs/load-management.md` dokumentiert.

## 1. Kurzfazit

Der 0.7.0-Branch ist die richtige Basis: Writes werden dort auf keinem Pfad wiederholt, Redirects werden nicht gefolgt, Seiten kommen in Reihenfolge, Seitenfehler werden geworfen, Packaging und CI sind auf Release-Niveau (Trusted Publishing, 3.9 bis 3.14, LICENSE, `requires-python`). 235 Offline-Tests grün auf 3.9, 3.12, 3.14 und gegen `requests==2.26.0`, Zeilenabdeckung 88 Prozent.

Er ist aber **nicht releasefähig**: Der adaptive Controller hat einen Logikfehler, der jeden Client nach dem ersten 429 oder `load`-Signal dauerhaft auf Parallelität 1 festnagelt. Dazu kommen die aus Notion bekannten Punkte (fester Deckel 10, Abbau pro Antwort, gemeinsames 429/5xx-Budget, Retry-After ohne Deckel, Writes ignorieren den Cooldown).

PyPI 0.6.0 wiederholt weiterhin POST/PUT/DELETE bei 5xx und 429 (`main:624-629`). Drei Konsumenten sind ungepinnt oder lose gepinnt. Deshalb zuerst ein 0.6.1-Hotfix, dann 0.7.0 mit repariertem Controller, dann zwei Minor-Releases bis zum API-Freeze.

Die Bibliothek ist mit 2382 Zeilen nicht mehr „in einem Durchgang lesbar". Rund 45 Prozent entfallen auf `WeclappEntity` (570 Zeilen) sowie Retry- und Controller-Mechanik. Für 1.0 gehört ein Modul-Split dazu, nicht nur ein Freeze.

## 2. Befunde nach Schwere

### P0 — Blocker

| Nr | Fundstelle | Befund | Auswirkung |
|---|---|---|---|
| P0-A | `main:624-629` | urllib3-`Retry` mit `allowed_methods` inkl. POST/PUT/DELETE, `status_forcelist` 5xx und 429. | Ein 500 oder 429 nach serverseitig erfolgreichem Write löst den Vorgang erneut aus (Doppelbuchung, doppelte Rechnung). Betrifft jeden Konsumenten auf 0.6.0 ohne eigene Adapter-Korrektur. |
| P0-B | `151-154` mit `186-201` | Controller kann nach Abfall auf Ziel 1 nie wieder wachsen: Permit nur bei `active == 0`, Sättigung verlangt `active >= max(1, target-1)`, bei Ziel 1 also `0 >= 1`. | Ein einziger 429 oder ein `load`-Header macht einen langlebigen Client (MCP-Server, n8n-Worker) dauerhaft seriell. Im Probe-Lauf blieb das Ziel nach 50 sequenziellen und 80 parallelen Erfolgen bei 1. |
| P0-C | `1315-1327`, `188-191`, `149` | `Retry-After` ohne Obergrenze, `inf` wird akzeptiert. | `Retry-After: 3600` blockiert alle Reads des Clients eine Stunde. `inf` oder `1e300` lässt `acquire()` bei jedem folgenden Read mit `OverflowError` sterben (Probe bestätigt), der Client ist unbrauchbar. |

### P1 — vor 1.0 zwingend

| Nr | Fundstelle | Befund | Auswirkung |
|---|---|---|---|
| P1-A | `193-196` | Abbau pro Antwort statt pro Fenster: jede `load`-Antwort halbiert, jede `concurrency`-Antwort subtrahiert 1. | Vier gleichzeitige `load`-Antworten bringen das Ziel in einem Roundtrip von 10 auf 1. Mit P0-B dauerhaft. |
| P1-B | `1150`, `2067`, `2094`, `1434-1439` | Deckel fest `DEFAULT_MAX_WORKERS=10`, kein Konstruktor-Parameter. `get_all(max_workers=20)` wirkt still als 10. Jedes `get()` läuft durch das client-weite Gate, `acquire()` ohne Timeout. Controller pro Client, nicht pro Mandant. | README verspricht `max_workers` als Ceiling, Code liefert 10. Zwei Clients auf denselben Mandanten koordinieren nicht. Ein Caller mit 30 eigenen Threads auf `get()` bekommt 2 bis 10 und blockiert unangekündigt. |
| P1-C | `1449`, `1472`, `1309-1312` | Ein Budget für 429, 5xx und Transportfehler (3 × 0,3/0,6/1,2 s + Jitter), kein Deckel. 429-Cooldown ist nur der Backoff-Wert. | Nach 30 s serverseitiger Queue geht der nächste Request nach 0,3 s raus. Vertrag verlangt für 429 ≥ 2 s Basis, 5 Versuche, Deckel 60 s. `max_retries=20` ergibt letzte Pause 0,3·2¹⁹ s. |
| P1-D | `1434` | Writes holen kein Permit und warten nicht auf den Cooldown. | Während Reads nach 429 pausieren, laufen Writes aus anderen Threads in die volle Queue, bekommen 429 und werden (korrekt) nicht wiederholt. Der Caller sieht vermeidbare Write-Fehler. Verzögern ist erlaubt, Wiederholen nicht. |
| P1-E | `1522-1541` | Transportfehler bei Writes werden zu `WeclappAPIError(status_code=None)` ohne Unterscheidung „nie gesendet" (ConnectError) vs „Ausgang unbekannt" (ReadTimeout, ChunkedEncodingError, RemoteDisconnected). | Der Vertrag „Writes nie wiederholen, Caller liest nach" hat kein Signal, mit dem der Caller entscheiden kann. Vor dem Freeze: `outcome_unknown`-Flag. |
| P1-F | `87-89`, `1161-1164`, `1242-1250` | `X-Weclapp-Request-Timeout-Ms=120000` gleich Client-Timeout 120 s. Per-Request-`timeout=` senkt den Header nicht. | Client bricht im selben Moment ab wie der Server; Writes bekommen ein mehrdeutiges `ReadTimeout` statt des definitiven 400 `request_timeout`. GET mit `timeout=10` und Retries hinterlässt bis zu vier 120-s-Ausführungen auf dem Server (Lastverstärkung). |
| P1-G | `2227`, `2250`, `2274`, `2332`, `2372`; `1202` | `id` und `action` werden unkodiert in den Pfad gesetzt; `_build_url` blockt nur `..`. | `put("salesOrder", "42/createSalesInvoice", …)` oder `"42?dryRun=false"` trifft einen anderen Endpunkt. Nicht vertrauenswürdige IDs (Webhook-Payloads) erreichen fremde Pfade. |
| P1-H | `1994`, `2028-2049`, `2132` | Default `threaded=True` (0.6.0: False). Threaded zählt vorab und wirft bei Unterdeckung; sequenziell prüft nicht und verliert verschobene Zeilen still. Jeder threaded-Aufruf kostet einen `/count`, auch bei `limit=5`. | Zwei Pfade, zwei Garantien. Konsumenten mit über 100 Default-Aufrufen (n8n-cicd) wechseln still das Verhalten. weclapp-mcp umgeht mit threaded seinen Circuit-Breaker und das 60-s-`context.call`-Timeout. |
| P1-I | `2020-2022` | Kein stabiles `sort`, wenn der Caller keines setzt; Seiten parallel per Offset. | Duplikate oder Lücken hängen an der Server-Default-Ordnung. Duplikat-Check greift nur mit `id` in der Projektion. Praxis-Learning L-Serie verlangt `sort=id` und Duplikat-Erkennung. |
| P1-J | `1596-1637` | Definitions-Cache ohne Lock, nie aktualisiert, bei transientem Fehler stilles `{}`. | Kalter Client mit N Threads lädt Definitionen N-mal. Nach Start angelegte Zusatzfelder werden nie geflattet. Nach einem 503 wirft `entity.myAttr` einmal `AttributeError`, beim nächsten Mal nicht: Entity-Form ist nicht deterministisch. |

### P2 — sollte in 1.0

| Nr | Fundstelle | Befund |
|---|---|---|
| P2-A | `1438-1439` | `KeyboardInterrupt` zwischen `acquire()` und `read_acquired=True` leakt ein Permit; bei Ziel 1 Deadlock aller weiteren Reads. |
| P2-B | `821-823` | `_ref_cache` ist nach Attributname, nicht nach ID geschlüsselt: nach `e["customerId"]="10"` liefert `e.customer` weiter Kunde 9 (Probe bestätigt). |
| P2-C | `799`, `495` | dict-Methoden verdecken Felder (`items`, `values`, `keys`, `get`, `copy`, `pop`, `update`). `copy()` und `json.dumps` enthalten synthetische Keys (geflattete Attribute, additionalProperties); `client.put(e.copy())` sendet unbekannte Top-Level-Properties. `copy.copy()` teilt `_ref_cache`. |
| P2-D | `193-195` | 250 ms und `SLOW_REQUEST_THRESHOLD_MS` (Logging-Konstante) steuern die Drosselung; `slow_threshold_ms` im Konstruktor wirkt nicht darauf. |
| P2-E | `145`, `1866`, `2057`, `1844` | `RuntimeError`, `TypeError`, `OverflowError` entkommen `except WeclappAPIError`; Duplikat-ID-Fehler ist ein `WeclappAPIError` ohne Status. Fehlerhierarchie fehlt. |
| P2-F | `1279`, `237` | Bis 4000 Zeichen Response-Body in Exception-Text; `err.response.request.headers` trägt den Token. Error-Reporter, die Attribute serialisieren, erfassen ihn. |
| P2-G | `2117-2120` | Bei Seitenfehler wartet `__exit__` des Executors auf laufende Seiten; Fehler erscheint erst nach Timeout × Versuche. |
| P2-H | `1107`, `1243`, `1073-1075` | `timeout` lehnt `(connect, read)`-Tupel ab, anders als requests. `pool_*` und `slow_threshold_ms` positional. `POST …/query` würde als Write behandelt (nicht gegated, nicht wiederholt). |
| P2-I | `1472`/`1481`, `1292` | `_should_retry_status` läuft zweimal pro Antwort, Fehler-JSON wird bis dreimal geparst. |
| P2-J | `109-121` | `_WeclappSession.rebuild_auth` kann bei `allow_redirects=False` nie laufen; als Defense-in-Depth behalten und so dokumentieren. |

### P3 — Qualität und Hygiene

- Kein `__version__`, totes Root-`__init__.py` (nicht im Wheel, dupliziert `__all__`), kein `py.typed` (Single-File-Modul kann keines tragen), `tests/conftest.py` fehlt im sdist, kein dev-Extra, `urllib3` direkt importiert ohne Deklaration.
- mypy: 11 Fehler (`1483`, `1523`, `1750`, `1771` u. a.), `--strict` 48. ruff auf Tests: 6 × F841, 1 × F821 (`test_weclappy_unit.py:1841`).
- Test `test_rate_limit_retry_respects_retry_after_header` wartet real 7 s (85 Prozent der Suite), weil `time.sleep` gepatcht ist, `Condition.wait` im Controller aber nicht. Controller-Wachstum (`201`), Blocking (`155`) und Close (`145`) sind ungetestet. Kein End-to-End-Test `get_all` gegen Controller unter 429/`load`, kein Test paralleler `get_all` auf einem Client.
- CHANGELOG `[0.7.0] - 2026-07-17` ist datiert, aber unveröffentlicht; Breaking Changes (threaded-Default, keine Redirects, absolute URLs abgelehnt, keine Write-Retries) nicht als BREAKING markiert. README `249-251` beschreibt `max_workers` falsch.
- `docs/weclapp-openapi.{json,yaml}` 3,8 MB im Repo (nicht im Wheel); `.cursor/rules/project.mdc` enthält absoluten lokalen Pfad; `PYPI.md` ist ein Release-Guide mit irreführendem Namen; SECURITY.md spricht von „unter 1.0".
- CI: kein ruff/mypy/Coverage-Gate, keine `concurrency`-Gruppe, Actions nach Tag statt SHA gepinnt, `requests`-Floor 2.26.0 nicht in CI, Python 3.9 seit 10/2025 EOL, 3.10 EOL 10/2026.

### Was im 0.7.0-Branch bereits richtig ist

Adapter `max_retries=0` (`1171`), `allow_redirects=False` auf jedem Request (`1422`), Origin-Check für `base_url` und `endpoint` (`1193-1211`), Writes auf keinem Pfad wiederholt, Seiten in Reihenfolge gemerged (`2124`), Seitenfehler werfen (`2117`), Duplikat-ID-Erkennung (`1817-1852`), Retry-Budget für Reads mit Problem-Typen (`1299-1341`), `id-eq`-Routing injektionssicher, Trusted Publishing mit Tag/Version/CHANGELOG-Gate, Wheel-Smoke-Test, Write-Tests opt-in.

## 3. Konsumenten-Lage

| Repo | Rolle | Pin | Kritische Nutzung | Risiko bei 0.7.0 / 1.0 |
|---|---|---|---|---|
| `weclapp-mcp` | Kernprodukt | `==0.6.0` | tauscht `client.session` komplett aus (`auth.py:754-778`), liest `get_adapter().max_retries` und `_pool_*`; `_send_request("GET", url, params, timeout=)` (`tools/_raw_api.py:23`, `protected_client.py:46`); eigener Tenant-Circuit-Breaker; `get_all` bewusst ohne threaded (`aggregate.py:65`) | Session-Tausch und `_send_request`-Signatur müssen bleiben oder einen dokumentierten Hook bekommen (`session=`, `request()`-Hook). Threaded-Default umgeht Breaker und `context.call`-Timeout. Python ≥ 3.13. |
| `walspro.tradehub` | Kernprodukt | pyproject `>=0.6.0,<0.7`, **deployed** `functions/requirements.txt:22` `==0.4.1` | 21 `get_all` ohne threaded; eigener `RetryingWeclappClient` (5xx/429) über weclappy-Retry gestapelt; Cursor-Scan `sort=lastModifiedDate` + `limit` (`adapter.py:~2541`) | Deployment-Pin ist inkonsistent zur Codebasis (eigenes Thema, jetzt prüfen). Doppelte Retry-Schichten. Python 3.12. |
| `walspro.weclapp.n8n-cicd` | Agentur-Infrastruktur | `>=0.1.0` | 94 Dateien, 101 `get_all` Default / 31 True / 21 False; `WeclappEntity._unwrap` (`tenant/neauvia/contact_updates.py:107`); `session.post/get` direkt; absolute `base_url`-URLs als `endpoint`; `max_workers` ohne `threaded` (`lib/assign_all_users_to_all_tasks.py:97`) | Nimmt jedes Release sofort. Absolute URLs als endpoint werden in 0.7.0 abgelehnt (`1198`). Pin auf `~=0.6.1` bis 0.7.0 verifiziert. |
| `walspro.multicarrier` (4Fulfillment) | Kernprodukt | `~=0.3.1` | `session.request` + `_check_response` + `_send_request` im eigenen Pool (`service/weclapp.py:190-212`); `sort=-lastModifiedDate` dann `documents[0]` | Geschützt durch Pin; Migration braucht `request()`-Hook statt Private-API. |
| `walspro.weclapp.mirakl`, BBN Article Importer | Kunde | `==0.2.0`, `~=0.2.0` | eigener Adapter + Retry (safe only) via `session.headers`/`mount` | Geschützt; `session` muss öffentlich bleiben. |
| hermes-campusdirekt, hema, smartStock | Mini-Kunden | `~=0.2.2`, `~=0.2.0` | `get_all(threaded=True, max_workers=20)` | Geschützt; `max_workers=20` wirkt in 0.7.0 als 10. |
| `walspro.weclapp.usfc` | Kunde | **ungepinnt** (Docker) | get/post/put | Nimmt jedes Release beim Rebuild. |
| `walspro.weclapp.scripts`, `walspro.sales`, SimpliServices | ad hoc | keiner / `>=0.1.0` | `session.get/mount`, absolute URLs, `get_all(threaded=True)` | Wie n8n-cicd. |

Keine Vendor-Kopie von `weclappy.py` außerhalb des Repos; ca. 70 handgeschriebene `class Weclapp`-Forks in Script-Repos importieren das Paket nicht.

**Für 1.0 stabil zu halten oder durch Hook zu ersetzen:** öffentliches, austauschbares `session`; `base_url` mit Trailing Slash; Logger-Name `weclappy`; `put` mit `ignoreMissingProperties=true` als Default; synthetischer 404 bei `get(id=)`; `_send_request(method, url, params=, timeout=)` → ersetzen durch öffentliches `request()` plus `before_request`/`on_response`; `_check_response` → öffentliche Fehlerklassifikation; `WeclappEntity._unwrap` → öffentliches `to_payload()`/`unwrap()`.

## 4. Soll laut weclapp-API-Vertrag

Quelle: `walspro.core/ai/knowledge/weclapp/weclapp-api-core.md` (Load Management, Retry boundaries, Client-Side Batching), OpenAPI-v2-Prosa, Community-Day-Vortrag Lanig, Praxis-Learnings.

- Kein festes Rate-Limit; mandantenweites Limit gleichzeitiger Requests (Zahl unveröffentlicht), Queue „derzeit" bis 30 s, danach 429. Last als „effektive Request-Zeit" (Request-Sekunden).
- `X-Weclapp-Wait-Ms` = bereits vergangene Queue-Zeit (keine Anweisung), `X-Weclapp-Wait-Reason` ∈ {`concurrency`, `load`, `concurrency, load`}; beide auf 2xx und 429, fehlen ohne Wartezeit. Reaktion (unsere Praxis): `concurrency` → Parallelität senken, `load` → Volumen senken.
- `X-Weclapp-Wait-Timeout-Ms` und `X-Weclapp-Request-Timeout-Ms` nur reduzierend, Best Effort; Überschreitung → 400 `/request_timeout`. Client-Timeout ≥ 60 s, Server-Timeouts unter dem Client-Timeout.
- 429 mit exponentiellem Backoff (Beispiel 2 s, 4 s …). `Retry-After` ist nicht dokumentiert: respektieren, falls vorhanden, mit Deckel.
- Nur GET/HEAD/OPTIONS automatisch wiederholen; bei 429, 500, 502, 503, 504, Transportfehler, 400 `/request_timeout`, 409 `/persistence`. Writes nie blind wiederholen; nach Timeout/429 zuerst nachlesen (Read-after-write-Backoff [0, 2, 5, 10, 20, 30] s). Optimistic Lock als 409 oder 400 mit Suffix `optimistic_lock`.
- Batching nach Lanig: `/count` → `properties=id&pageSize=1000` → `id-in`-Pakete mit `properties=` und bei Bedarf `includeReferencedEntities`. Paketgröße und URL-Limit undokumentiert → auf Acme-Sandbox messen. ID-Liste ist ein Snapshot; IDs sind Strings; `pageSize` max 1000; Abbruch bei kurzer Seite, nie per Count; `sort=id` plus Duplikat-Check; Keyset `sort=id&id-gt=`.
- Inoffiziell (kein Vertrag): `POST /{entity}/query`, `POST /{entity}/count`, `POST /batch/query`, `meta/openapi.yaml?includeHidden=true`. Nur bewusst, mit Fallback, nie auf kritischem Pfad.
- Nicht als Fakt hinterlegen: Mandanten-Limit, Server-Maximum für Wait-Timeout, Retry-After-Existenz, Paketgrößen, Body-Semantik der POST-Query-Endpunkte, AIMD-Parameter (unsere Tuning-Werte), Correlation-ID-Headername.

## 5. Entscheidungen (nur Markus)

| Frage | Empfehlung | Begründung |
|---|---|---|
| 0.6.1-Hotfix vorab oder direkt 0.7.0? | **0.6.1 sofort**, nur Write-Retry-Entfernung. | n8n-cicd, usfc, Scripts nehmen jedes Release; 0.7.0 braucht erst P0-B/P0-C. Minimaler Diff, kein Verhaltenswechsel außer dem gewollten. |
| Default `threaded=True` behalten? | **Weder noch: `threaded="auto"`** als Default. Seite 1 sequenziell; kurz → fertig (kein `/count`, kein Pool); voll → `/count`, Rest adaptiv parallel. `True`/`False` bleiben explizit. | Kleine Abfragen zahlen keinen Zusatzrequest, große profitieren; ein Pfad, eine Konsistenzgarantie (Shortfall + Duplikat-Check in beiden Modi). Für weclapp-mcp bleibt `threaded=False` setzbar. |
| Load-Management pro Client oder prozessweit pro Mandant? | **Injizierbares Controller-Objekt**, Default eine Instanz pro Client; Konsumenten teilen es bewusst (`Weclapp(..., concurrency=shared)`). Kein globaler Prozess-Zustand in der Bibliothek. | Vertrag ist pro Mandant, aber globale Registries in einer Bibliothek sind schwer testbar und überraschen. weclapp-mcp (mehrere Clients je Mandant) kann teilen, ohne dass Einzelskripte es müssen. |
| Inoffizielle Endpunkte in der öffentlichen Bibliothek? | **Nicht in 1.0.** Frühestens 1.x als opt-in `experimental`-Namespace nach Sandbox-Verifikation. | Kein Vertrag, keine Änderungsankündigung; eine 1.0 soll nur Verträge kapseln. |
| Bulk-Writes (Issue #2)? | **Nein** für 1.0; Issue mit Begründung schließen oder als „won't fix" markieren. | Widerspricht „keine automatischen parallelen Writes". Caller können `ThreadPoolExecutor` selbst nutzen; die Bibliothek garantiert dann nur, nichts zu wiederholen. |
| Python-Mindestversion für 1.0? | **≥ 3.10** (3.9 EOL 10/2025; 3.10 EOL 10/2026, aber tradehub/multicarrier auf 3.12, mcp auf 3.13). Alternativ ≥ 3.11 wenn kein Konsument 3.10 braucht. | Support-Policy in README fixieren: letzte vier CPython-Versionen. |

## 6. Roadmap

Foundation-first, jede Phase ein PR mit Review, eigener Changelog-Eintrag, Konsumenten-Test vor Release. Kein PyPI-Release ohne Freigabe Markus. Live-Messungen nur Acme-Sandbox.

### Phase 0 — 0.6.1 Hotfix (sofort, 1 Tag)

- Scope: `main:624-629` `allowed_methods` auf HEAD/GET/OPTIONS; `Retry` behält 5xx/429 für Reads. Sonst nichts.
- Tests: Mock-Server-Suite aus PR #7 (`tests/test_retry_policy.py`, zählt Hits pro Methode) übernehmen, Erwartung „Write bei 429 genau einmal". Arne als Co-Author.
- Doku: CHANGELOG `[0.6.1]` mit Sicherheitshinweis; README-Abschnitt Retry-Verhalten.
- PR #7 schließen als „superseded by #<neu>" mit Dank.
- Konsumenten: n8n-cicd `requirements.txt` auf `weclappy~=0.6.1`; usfc pinnen; tradehub `functions/requirements.txt` auf `==0.6.1` heben und Deploy prüfen (heute 0.4.1).
- Exit: PyPI 0.6.1 live, Tag `v0.6.1`, Konsumenten-Pins gemerged.

### Phase 1 — 0.7.0 Adaptive Reads (1 bis 2 Wochen)

- Basis: Branch `agent/adaptive-threaded-pagination` auf `main` rebasen, PR gegen main.
- Controller (`124-208`):
  - P0-B: Sättigung messen als „Fenster war voll" über ein Epochen-Zähler-Modell: Wachstum +1 pro Fenster (Epoche = `target` abgeschlossene Antworten ohne negatives Signal), Abbau max. einmal pro Epoche (P1-A).
  - P1-B: `Weclapp(max_concurrency: int = 10)` als harter Deckel; `get_all(max_workers=)` ≤ `max_concurrency`, darüber `ValueError`. Controller-Objekt injizierbar (`concurrency=`). `acquire(timeout=)` mit Client-Timeout, danach `WeclappAPIError`-Unterklasse statt Hängen.
  - P1-D: Writes holen kein Permit, warten aber auf `cooldown_until`. Nie wiederholen.
  - P2-D: Schwellen 250 ms / 2000 ms als Controller-Parameter, getrennt von `slow_threshold_ms`.
  - P2-A: `acquire()` in `try/finally` so, dass ein Permit nie leakt.
- Retry (`1299-1341`, `1402-1561`):
  - P1-C: getrenntes 429-Budget (5 Versuche, Basis 2 s, Jitter, Deckel 60 s) vs. 5xx/Transport (3 × 0,3/0,6/1,2 s). Backoff-Deckel 60 s auch für `Retry-After` (P0-C), nicht-finite Werte ignorieren.
  - Vier Retry-Prädikate zu einem `_classify(method, response|exc) -> RetryDecision` zusammenfassen (P2-I).
- Timeouts (P1-F): `request_timeout_ms` Default auf 110 000 bei Client-Timeout 120 s; Per-Request-`timeout=` setzt den Header auf `min(header, timeout·1000 − Reserve)`. `timeout` akzeptiert `(connect, read)`.
- `get_all` (P1-H, P1-I): `threaded="auto"` Default (siehe Entscheidung); sequenzieller Pfad auf `iter_all` aufgebaut, beide Pfade mit Shortfall- und Duplikat-Check; ohne `sort` automatisch `sort=id` setzen und das dokumentieren (Opt-out `sort=None` explizit); Warnung bei `pageSize > 1000`.
- P1-G: `id`, `entity_id`, `action` mit `urllib.parse.quote(..., safe="")` kodieren; `ValueError` bei `/` oder `?` im Wert.
- P1-J: Definitions-Cache mit `threading.Lock`, einmaliger Fetch, `refresh_attribute_definitions()`; Fehler loggen und als `AttributeError` mit Hinweis werfen, nicht `{}`.
- Tests: Fake-Clock (`time.monotonic` + `Condition.wait` gepatcht) für Controller und Cooldown (7-s-Test eliminieren); Wachstum, Abbau pro Epoche, Blocking, Close; End-to-End `get_all` gegen Fake-Server mit 429/`load`/`concurrency`-Sequenzen; parallele `get_all` auf einem Client; Pfad-Encoding; Shortfall sequenziell; Retry-After-Deckel und `inf`.
- Doku: CHANGELOG `[0.7.0]` mit frischem Datum und Abschnitt „Changed (BREAKING)": Default `auto`, keine Redirects, absolute URLs abgelehnt, keine Write-Retries, Deckel. Migrationsnotiz 0.6 → 0.7. README `249-251` korrigieren. AIMD-Tabelle für Blog-Entwurf „Jeder Request zählt" aus dem Code ableiten.
- Konsumenten: weclapp-mcp (`==0.7.0`, Session-Tausch und `_send_request` prüfen, `threaded=False` an den Breaker-Stellen), tradehub (`<0.8`, Cursor-Scan unter `auto` testen), n8n-cicd (absolute URLs als `endpoint` finden und auf relative Pfade umstellen, dann `~=0.7.0`).
- Exit: alle P0 und P1-A bis P1-J geschlossen, Suite < 3 s, Coverage ≥ 88 Prozent, drei Kern-Konsumenten gegen RC grün, Freigabe Markus, PyPI 0.7.0.

### Phase 2 — 0.8.0 Observability und Erweiterungspunkte (1 Woche)

- `RequestMetrics` (Dataclass: method, path ohne Query, status, duration_ms, wait_ms, wait_reason, correlation_id, attempt, concurrency_target, outcome) und `Weclapp(on_response=callable)`; `client.stats` mit Request-Sekunden, Anzahl, 429-Zähler, max Wait. Nie Token oder Query loggen.
- `Weclapp(session=requests.Session)` und `before_request(prepared)`-Hook, damit weclapp-mcp, Mirakl, BBN ohne `session.mount`-Tricks auskommen; `User-Agent: weclappy/<version>`; Header-Override je Aufruf in `request()`.
- Fehlermodell: `WeclappAPIError` bleibt Basis; Unterklassen `WeclappTransportError` (mit `outcome_unknown: bool`, P1-E), `WeclappRateLimited`, `WeclappNotFound`, `WeclappValidationError`, `WeclappOptimisticLock`, `WeclappPaginationError`; `is_*`-Properties bleiben. `wait_ms` numerisch. Token aus `response.request.headers` beim Anhängen an die Exception maskieren (P2-F).
- `WeclappEntity`: `_ref_cache` nach ID schlüsseln (P2-B); `copy()`/`__reduce__`/`json`-Verhalten dokumentieren, `to_payload()` als einziger Weg in einen Write (P2-C); Read-only-Positionsverfolgung (`~80 Zeilen`) entfernen, Server lehnt ohnehin ab.
- Exit: weclapp-mcp nutzt `session=`/`on_response` statt `_send_request`; Private-API-Nutzung in Kern-Konsumenten auf null.

### Phase 3 — 0.9.0 Batching und Pagination-Budget (1 bis 2 Wochen)

- Vorab auf Acme-Sandbox messen und in `docs/` festhalten: maximale `id-in`-Paketgröße, URL-Länge, `pageSize`-Verhalten > 1000, `/count` auf Entitäten ohne Count.
- `get_by_ids(entity, ids, params=None, chunk_size=<gemessen>, max_url_length=<gemessen>)` mit Reihenfolge der Eingabe, fehlende IDs gemeldet.
- `get_all(strategy="pages"|"ids")`: `ids` = count → `properties=id` → `id-in`-Pakete adaptiv parallel; Default bleibt `pages`.
- `max_records` (Abbruch vor dem Abruf nach `/count`), `iter_keyset(entity, params, start_after=None)` mit `sort=id&id-gt=`, Filterverifikation je Zeile.
- Exit: Benchmark auf Sandbox dokumentiert (Request-Sekunden pages vs ids), Tests für Chunking, Reihenfolge, Teilfehler.

### Phase 4 — 1.0.0 API-Freeze (1 Woche)

- Paketlayout `src/weclappy/` mit `__init__.py`, `_client.py`, `_concurrency.py`, `_retry.py`, `_entity.py`, `_errors.py`; Root-`__init__.py` löschen; `py.typed`; `__version__` aus `importlib.metadata`; `conftest.py` ins sdist oder Tests raus.
- Signaturen: `pool_connections`, `pool_maxsize`, `slow_threshold_ms` keyword-only; `endpoint`/`entity` vereinheitlichen (ein Name, Alias mit `DeprecationWarning`); `id` → `entity_id` konsistent; `from_row` ohne `_depth` in der Signatur; Write-Methoden typisiert (`Dict[str, Any]`, `WeclappEntity` bei JSON); `WeclappResponse.result` korrekt typisiert.
- Qualität: mypy clean (`--strict` Ziel), ruff in CI, Coverage-Gate ≥ 90 Prozent, `requests`-Floor in CI oder auf 2.31 heben, Actions nach SHA, `concurrency`-Gruppe, Dependabot, Python ≥ 3.10.
- Doku: README als Referenz je Methode; `RELEASING.md` statt `PYPI.md`; SECURITY.md für 1.x; Versionierungs- und Deprecation-Policy (SemVer, `DeprecationWarning` mindestens ein Minor vor Entfernung); CHANGELOG mit Migrationsnotiz 0.7 → 1.0; OpenAPI-Snapshots aus dem Repo (Fetch-Script) oder LFS; `.cursor`-Pfad entfernen.
- Konsumenten: alle Kern-Repos auf `>=1.0,<2`, gegen RC getestet.
- Exit: `1.0.0rc1` auf PyPI, eine Woche in weclapp-mcp und n8n-cicd im Einsatz, keine P1-Befunde, Freigabe Markus, `1.0.0`.

### Nicht in 1.0

`POST /{entity}/query` und `/count` (frühestens 1.x, opt-in), `POST /batch/query` (nie ohne Vertrag), Bulk-Writes, `api_version`-Parameter (1.1 möglich, additiv), `client.openapi()`, Async-Client (2.0-Thema; httpx würde `session`-Konsumenten brechen).

## 7. Öffentliche API 1.0 (Vorschlag zum Einfrieren)

```python
Weclapp(base_url, api_key, *, timeout=120, max_retries=3, backoff_factor=0.3,
        problem_retries=1, rate_limit_retries=5, rate_limit_base_delay=2.0, max_backoff=60.0,
        wait_timeout_ms=30_000, request_timeout_ms=110_000, max_concurrency=10,
        concurrency=None, session=None, before_request=None, on_response=None,
        pool_connections=100, pool_maxsize=100, slow_threshold_ms=2000)
.request(method, endpoint, *, params=None, json=None, data=None, headers=None, timeout=None)
.get(entity, entity_id=None, params=None, *, return_weclapp_response=False)
.get_all(entity, params=None, *, limit=None, max_records=None, threaded="auto",
         max_workers=None, strategy="pages", return_weclapp_response=False)
.get_by_ids(entity, ids, params=None, *, chunk_size=None)
.iter_all(entity, params=None, *, limit=None)
.iter_keyset(entity, params=None, *, start_after=None)
.post(entity, data, params=None)   .put(entity, entity_id, data, params=None)
.delete(entity, entity_id, params=None)
.call_method(entity, action, entity_id=None, *, method="GET", data=None, params=None)
.upload(...)  .download(...)  .refresh_attribute_definitions()  .stats  .close()
WeclappAPIError (+ Unterklassen), WeclappResponse, WeclappEntity, RequestMetrics,
ConcurrencyController, MIME_TYPES, infer_content_type, __version__
```

Alles mit führendem Unterstrich ist privat und ab 1.0 ohne Semver-Garantie.
