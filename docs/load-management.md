# weclapp load management and how weclappy implements it

This document explains the load-management contract of the weclapp REST API,
how `ConcurrencyController` and `RetryPolicy` implement it, and which numbers
were measured on the weclapp sandbox. The code in `src/weclappy/concurrency.py`
and `src/weclappy/retry.py` is the authoritative specification; this text
describes it.

## 1. The contract

weclapp documents its load management in the prose of the API v2 OpenAPI
document. The parts weclappy relies on:

- **No fixed rate limit.** weclapp does not count requests per minute. It
  limits the number of concurrently active requests per tenant. The number is
  not published and may differ between tenants and over time.
- **Queue, then 429.** Requests above the limit are queued, currently for up to
  about 30 seconds. A request still queued after that is rejected with HTTP
  429.
- **Load is request time.** weclapp accounts load as the effective processing
  time of requests ("request seconds"). Fewer, larger requests are cheaper
  than many small ones.
- **Feedback headers.** A response to a queued request carries
  `X-Weclapp-Wait-Ms` (milliseconds already spent in the queue; a report, not
  an instruction) and `X-Weclapp-Wait-Reason` (`concurrency`, `load`, or
  both, comma-separated). Both appear on 2xx and on 429 responses and are
  absent when the request did not wait.
- **Client-controlled timeouts.** `X-Weclapp-Wait-Timeout-Ms` bounds the queue
  wait, `X-Weclapp-Request-Timeout-Ms` bounds the processing time. Both can
  only lower the server defaults and are best effort. Exceeding the request
  timeout produces a 400 problem response of type `request_timeout`.
- **Client behaviour weclapp asks for.** Throttle proactively as soon as wait
  times rise instead of waiting for 429; back off exponentially after 429;
  retry only safe methods automatically; keep the client timeout generous (at
  least 60 s) and the server-side timeouts below it.

`Retry-After` is not documented by weclapp. weclappy honours it when present,
because intermediaries may send it, but caps it.

## 2. Mapping responses to signals

`ConcurrencyController.signal_from_response(status, headers)` turns every
response of a read into one `Signal`:

| Response | Signal | Rule |
| --- | --- | --- |
| HTTP 429 | `RATE_LIMITED` | always, regardless of headers |
| reason contains `load`, or `X-Weclapp-Wait-Ms` ≥ 2000 | `LOAD` | the explicit reason wins over thresholds |
| reason contains `concurrency`, or `X-Weclapp-Wait-Ms` ≥ 250 | `CONCURRENCY` | |
| 5xx without wait hints | `ERROR` | transport failures are `ERROR` too |
| anything else (2xx, 4xx) | `OK` | counts toward growth |

The thresholds are `ConcurrencySettings.concurrency_wait_threshold_ms` (250)
and `load_wait_threshold_ms` (2000). They are tuning values chosen by
weclappy, not numbers published by weclapp.

## 3. The controller: AIMD per epoch

`ConcurrencyController` keeps a *target*: the number of reads allowed in
flight. Reads acquire a `Permit` before they are sent and release it when the
response (or the failure) arrives. The target changes once per *epoch*; an
epoch is `target` completed observations, so its length follows the window
size.

| Rule | Value |
| --- | --- |
| Initial target | `min(initial_concurrency, max_concurrency)` = 2 |
| Ceiling | `max_concurrency` = 10 (`Weclapp(max_concurrency=...)`) |
| `CONCURRENCY` | target − 1, floor 1 |
| `LOAD` | target halved, rounded up, floor 1 |
| Decreases per epoch | at most one (`CONCURRENCY`/`LOAD`) |
| `RATE_LIMITED` | target = 1 and a shared cooldown of `max(min_rate_limit_cooldown, retry delay)` = at least 2 s; no permit is granted during the cooldown |
| `ERROR` | no change, but the epoch cannot grow |
| Growth | +1 at the end of an epoch that was saturated, had no decrease and no error |

**Why per epoch.** Responses arrive in bursts. If four in-flight responses all
carry `load`, a per-response rule would halve the target four times (10 → 5 →
3 → 2 → 1) within one round trip, although they all describe the same moment.
With at most one decrease per epoch the controller reacts once, then observes
the effect of that reaction.

**Why "saturated".** An epoch is saturated when the number of active permits
reached the target at some point during it. Growth is only useful when the
caller actually uses every slot; a sequential caller that never holds more
than one permit does not raise the target. This rule works at every target,
including 1, so a client recovers after a 429 instead of staying serial
forever (the 0.7.0 branch could not grow from 1).

**Cooldown.** After a 429 the controller starts a cooldown shared by every
thread of the client (or of every client sharing the controller). Reads wait
for it in `acquire()`; writes call `wait_for_cooldown()` before they are sent.
The cooldown is the capped `Retry-After` when present, otherwise the next
rate-limit backoff, and never less than `min_rate_limit_cooldown` (2 s).
Non-finite values are ignored.

**Timeout.** `acquire()` and `wait_for_cooldown()` wait at most the client's
read timeout and then raise `WeclappConcurrencyTimeoutError`, so a stuck
controller never hangs a caller indefinitely.

**Scope.** The default is one controller per client. weclapp's limit is per
tenant, so processes that run several clients against one tenant should share
one controller explicitly:

```python
from weclappy import ConcurrencyController, ConcurrencySettings, Weclapp

shared = ConcurrencyController(ConcurrencySettings(max_concurrency=8))
reader = Weclapp.for_tenant("acme", "key-for-reports", concurrency=shared)
writer = Weclapp.for_tenant("acme", "key-for-sync", concurrency=shared)
```

weclappy keeps no process-global state; sharing is always the caller's
decision.

**Parallel pages.** `get_all` and `get_by_ids` submit jobs through a moving
window of `min(max_workers, controller.target)` jobs. When the target drops,
no new job is submitted until the in-flight count is below the new target;
when it grows, the window widens. The thread pool size (`max_workers`, at most
`max_concurrency`) is only an upper bound.

## 4. The retry policy

`RetryPolicy` is immutable and classifies every failed attempt into a
`RetryDecision`. Reads are `GET`, `HEAD`, `OPTIONS`, and `POST` to paths ending
in `/query`, `/count` or `batch/query`. Everything else is a write.

| Failure | Read | Write |
| --- | --- | --- |
| DNS failure, connection refused, connect timeout (`NOT_SENT`) | transient budget | transient budget |
| Read timeout, connection dropped after sending, broken chunked body (`UNKNOWN`) | transient budget | not retried, `WeclappTransportError(outcome_unknown=True)` |
| TLS error (`NOT_RETRYABLE`) | not retried | not retried |
| 500, 502, 503, 504 | transient budget | not retried |
| 429 | rate-limit budget | not retried |
| 400 `request_timeout`, 409 `persistence` | problem budget | not retried |
| 3xx | not followed, `WeclappRedirectError` | same |

| Budget | Default | Delay before retry *n* | With jitter |
| --- | --- | --- | --- |
| transient (`max_retries`) | 3 | `0.3 · 2ⁿ` s | 0.3–0.6, 0.6–0.9, 1.2–1.5 s |
| rate limit (`rate_limit_retries`) | 5 | `2 · 2ⁿ` s | 2–4, 4–6, 8–10, 16–18, 32–34 s |
| problem (`problem_retries`) | 1 | `0.3 · 2ⁿ` s | 0.3–0.6 s |

Every delay, including `Retry-After`, is capped at `max_backoff` (60 s). With
the defaults, a read that keeps receiving 429 gives up after roughly one minute
of backoff plus up to six 30-second queue waits.

`classify_transport_error()` decides `NOT_SENT` only for failures that happen
before a connection carries request bytes: `ConnectTimeout`, and
`ConnectionError` wrapping urllib3's `NameResolutionError`,
`NewConnectionError` or `ConnectTimeoutError`. Everything else is `UNKNOWN`,
because the server may have processed the request.

**Why writes are not retried.** A 5xx, a 429 after queueing, or a timeout does
not prove that the write failed. weclapp may have committed it before the
response was lost. Repeating `POST salesInvoice` can create a second invoice;
repeating a stock booking books twice. weclappy therefore raises and leaves
the decision to the caller, who can read the entity back (by a business key)
and decide. A practical read-back schedule is 0, 2, 5, 10, 20 and 30 seconds.

## 5. Timeouts

| Layer | Default | Notes |
| --- | --- | --- |
| Client (`requests`) | 120 s | float or `(connect, read)` |
| `X-Weclapp-Wait-Timeout-Ms` | 30 000 | matches weclapp's current queue limit |
| `X-Weclapp-Request-Timeout-Ms` | 110 000 | below the client timeout, so weclapp answers with a definitive 400 `request_timeout` before the client gives up |
| per-request `timeout=` | – | lowers the request-timeout header to 90 % of the read timeout when that is smaller |

Without the 10-second gap, client and server would give up at the same moment
and a write would end in an ambiguous read timeout instead of a definitive
error. Lowering the header for short per-request timeouts prevents retried
reads from leaving several long-running executions behind on the server.

## 6. Pagination and batching

- `get_all` adds `sort=id` unless `sort` or `orderBy` is given. Offset pages
  without a stable order can move rows across page boundaries.
- `threaded="auto"` reads page 1 first; only a full page triggers a
  `/count` request and the concurrent fetch of the remaining pages.
- Both paths reject duplicate ids across pages; the concurrent path also
  rejects a shortfall against the count. Both raise `WeclappPaginationError`.
- `strategy="ids"` and `get_by_ids` implement the pattern weclapp recommends
  for large projections: read ids first (`properties=id`), then the rows in
  `id-in` chunks with the full projection. The id list is a snapshot; ids that
  disappear in between are absent from the result.
- `iter_keyset` uses `sort=id&id-gt=<last id>` and is immune to inserts and
  deletes during the read.

## 7. Sandbox measurements

Measured on the weclapp sandbox tenant in October 2026 with weclapp API v2.
They are observations, not guarantees.

| Topic | Observation | Consequence in weclappy |
| --- | --- | --- |
| URL length | The edge (Akamai) in front of weclapp rejects request URLs of about 8.9 KB with HTTP 400 before they reach weclapp. | `get_by_ids(max_url_length=8000)` |
| `id-in` chunk size | 640 numeric ids fit below the URL limit. | `get_by_ids(chunk_size=500)` leaves headroom for longer ids and other parameters. |
| `id-in` and `pageSize` | `id-in` is paginated like any list request: without an explicit `pageSize` only the default page size of matches is returned. | Each chunk sends `pageSize=len(chunk)`. |
| `pageSize` above 1000 | No 1000-row cap was observed on the sandbox; larger page sizes were accepted. weclapp's documentation names 1000 as the maximum. | weclappy defaults to 1000 and does not rely on larger pages. |
| `POST batch/query` | Accepts at most 500 requests per call. The response is a flat list of triples `[index, meta, {status, body}, ...]` that is not in request order. | `batch_query` rejects more than 500 locally and sorts by index. |
| `POST batch/query` paths | `/id/{id}` paths are rejected inside a batch; collection paths with query strings and `{entity}/count` work. | Documented on `batch_query`. |
| `GET {entity}/id/{id}` | Ignores `properties` and `includeReferencedEntities`. | `get(entity, entity_id)` reads `{entity}?id-eq={id}&page=1&pageSize=1` instead. |

## 8. Unverified or tenant-dependent

Do not treat the following as facts; they are either undocumented, untested,
or expected to differ between tenants:

- The tenant's concurrency limit (not published; varies by tenant and over
  time).
- The server-side maximum for `X-Weclapp-Wait-Timeout-Ms` and
  `X-Weclapp-Request-Timeout-Ms`, and whether the 30-second queue limit stays
  at 30 seconds.
- Whether weclapp ever sends `Retry-After`.
- The correlation header name (weclappy reads `X-Correlation-ID` and
  `X-Request-ID` variants if present).
- The URL limit and the absence of a 1000-row cap on production tenants
  (measured on the sandbox only; edge configuration may differ).
- How `POST batch/query` is accounted in load management (one request or one
  per sub-request), and the meaning of the `meta` value in its response.
- Body semantics of `POST {entity}/query` and `POST {entity}/count` beyond the
  fields weclappy sends (`filter`, `properties`, `orderBy`, `page`,
  `pageSize`, `offset`, `serializeNulls`, `includeReferencedEntities`,
  `additionalProperties`).
- The AIMD parameters themselves (start 2, ceiling 10, thresholds 250 ms and
  2000 ms, cooldown 2 s). They are weclappy's tuning choices and can be changed
  through `ConcurrencySettings`.
