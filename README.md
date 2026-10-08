# weclappy

**The weclapp REST API client for Python that listens to the tenant's queue and
never repeats a write it cannot vouch for.** You name an endpoint, pass query
parameters or a JSON payload, and get typed Python objects back. Underneath,
weclappy implements weclapp's load-management contract end to end.

```python
from weclappy import Weclapp

client = Weclapp.for_tenant("acme", api_key)
orders = client.get_all(
    "salesOrder",
    {"status-eq": "ORDER_CONFIRMED", "includeReferencedEntities": "customerId"},
)
print(orders[0].customer.name)  # customerId resolves to the referenced party
```

## Highlights

- **Writes are never repeated blindly.** A 5xx, 429 or read timeout on
  `POST`/`PUT`/`DELETE` raises instead of retrying; `outcome_unknown` tells you
  when to read the entity back. Only requests that provably never left the
  process are retried. No duplicate invoices, no double stock bookings.
- **Adaptive concurrency, driven by weclapp itself.** An AIMD controller reads
  `X-Weclapp-Wait-Ms` and `X-Weclapp-Wait-Reason`, grows one slot per clean
  window and backs off before the tenant lands in the queue. One controller can
  be shared by every client of a tenant.
- **Retry budgets that match the API.** 5xx and network failures: 3 × 0.3 s.
  429: 5 × 2 s with a 60 s cap that also bounds `Retry-After`. weclapp's own
  transient problem types (`request_timeout`, `persistence`) get one more try.
- **Pagination you can trust.** `get_all` reads page one, counts only when more
  pages exist, fetches the rest concurrently in page order, sorts by `id` by
  default and raises on duplicates or a shortfall. `iter_keyset` streams exports
  that never lose a row. `max_records` refuses runaway reads before they start.
- **Batching the way weclapp recommends.** `get_by_ids` and
  `get_all(strategy="ids")` read ids first and then rows in `id-in` chunks sized
  from sandbox measurements (500 ids, 8 KB URLs). 3,721 articles in 0.6 s with
  5 requests on the weclapp sandbox.
- **Entities that behave.** `WeclappEntity` is a dict with attribute access,
  flattened custom attributes (all eleven value types round-trip), lazy `*Id`
  resolution through `referencedEntities`, nested wrapping and `to_payload()`
  for safe writes.
- **Observability built in.** `on_response` hands you `RequestMetrics` for every
  attempt (duration, queue wait, reason, correlation id, retry decision);
  `client.stats` aggregates request seconds the way weclapp bills load.
- **Typed errors.** `WeclappRateLimitError`, `WeclappNotFoundError`,
  `WeclappOptimisticLockError`, `WeclappValidationError`,
  `WeclappTransportError`, `WeclappPaginationError` and more, all under
  `WeclappAPIError` with the parsed problem document.
- **The hidden endpoints, labelled.** `query()` (`POST /{entity}/query`, no URL
  length limit), `query_count()`, `batch_query()` (up to 500 reads in one call)
  and `openapi(include_hidden=True)`, each marked as unofficial with a fallback.
- **Small and strict.** One module family, two runtime dependencies
  (`requests`, `urllib3`), Python 3.12+, `py.typed`, mypy strict, 97 % test
  coverage including an in-process fake weclapp server that simulates queueing,
  429s and dropped connections.

weclappy is independent and community-maintained; it is not affiliated with
weclapp.

- [Install](#install)
- [Quick start](#quick-start)
- [How weclappy talks to weclapp](#how-weclappy-talks-to-weclapp)
- [Reading data](#reading-data)
- [Entities](#entities)
- [Writing data](#writing-data)
- [Unofficial endpoints](#unofficial-endpoints)
- [Observability](#observability)
- [Extension points](#extension-points)
- [Errors](#errors)
- [Configuration reference](#configuration-reference)
- [Migration from 0.x](#migration-from-0x)
- [Versioning and support policy](#versioning-and-support-policy)
- [Development](#development)
- [License](#license)

## Install

```bash
python -m pip install weclappy
```

Requires Python 3.12 or newer. Runtime dependencies: `requests` (≥ 2.31) and
`urllib3` (≥ 2.0). The package ships type information (`py.typed`).

## Quick start

Keep the API key out of your source code:

```bash
export WECLAPP_API_KEY="your-api-key"
```

```python
import os

from weclappy import Weclapp

with Weclapp.for_tenant("acme", os.environ["WECLAPP_API_KEY"]) as client:
    # Every matching record; pagination, sort=id and load control are automatic.
    orders = client.get_all(
        "salesOrder",
        {"status-eq": "ORDER_CONFIRMED", "properties": "id,orderNumber,customerId"},
    )

    # One record by id. Attribute access works next to normal dict access.
    order = client.get("salesOrder", orders[0].id, {"properties": "id,version,commission"})
    print(order.id, order["version"], order.commission)

    # Round trip: to_payload() gives a plain JSON dict that is safe to send back.
    payload = order.to_payload()
    payload["commission"] = "Checked by weclappy"
    client.put("salesOrder", order.id, payload)
```

`Weclapp.for_tenant("acme", key)` builds
`https://acme.weclapp.com/webapp/api/v2/`. Pass a full host
(`for_tenant("erp.example.com", key)`) for custom domains and
`api_version=` for another API version, or construct the client from the API
root: `Weclapp("https://acme.weclapp.com/webapp/api/v2/", key)`. A `base_url`
that does not end in `/webapp/api/v<N>` raises `ValueError`; a bare tenant host
would answer every request with a redirect.

The client owns a pooled HTTP session. Use it as a context manager or call
`client.close()` when a long-lived client is no longer needed. One client is
thread-safe and is meant to be shared by all threads of a process that talk to
the same tenant.

## How weclappy talks to weclapp

weclapp has no fixed request rate limit. It limits the number of concurrently
active requests per tenant (the number is not published) and queues requests
above that limit, currently for up to about 30 seconds, before rejecting them
with HTTP 429. Load is accounted as request time. Every queued response says
how long it waited and why:

| Header | Meaning |
| --- | --- |
| `X-Weclapp-Wait-Ms` | Time the request already spent in weclapp's queue, in milliseconds. A report, not an instruction. Absent when there was no wait. |
| `X-Weclapp-Wait-Reason` | `concurrency` (too many requests active), `load` (overall load too high), or both. Appears on 2xx and 429 responses. |
| `X-Weclapp-Wait-Timeout-Ms` | Request header: the longest queue wait the client accepts. Can only lower the server default. |
| `X-Weclapp-Request-Timeout-Ms` | Request header: the longest server-side processing time. Exceeding it yields a 400 `request_timeout` problem. Can only lower the server default. |

weclappy uses these signals to throttle proactively, before 429 responses
occur. [docs/load-management.md](https://github.com/Wals-pro/weclappy/blob/main/docs/load-management.md) has the full
explanation, including sandbox measurements.

### Adaptive concurrency (AIMD per epoch)

Reads (`GET`, `HEAD`, `OPTIONS` and the read-only `POST …/query`, `POST
…/count`, `POST batch/query`) hold a permit from a `ConcurrencyController`
while they are in flight. The controller keeps a *target* number of parallel
reads and adjusts it once per *epoch*, one epoch being `target` completed
responses:

| Event | Effect on the target |
| --- | --- |
| Start | 2 (`min(initial_concurrency, max_concurrency)`) |
| Ceiling | 10 (`Weclapp(max_concurrency=...)`) |
| Wait reason `concurrency`, or wait ≥ 250 ms | −1 (at most one decrease per epoch) |
| Wait reason `load`, or wait ≥ 2000 ms | halved, rounded up (at most one decrease per epoch) |
| HTTP 429 | 1, plus a shared cooldown of at least 2 s (or the capped `Retry-After`) during which no request is sent |
| 5xx or transport failure | no change, but no growth in this epoch |
| Full epoch, window saturated, no decrease or error | +1 |

"Saturated" means the number of active reads actually reached the target at
some point during the epoch, so the target only grows when an extra slot would
be used. Growth works at every target, including 1. Because a decrease is
applied at most once per epoch, a burst of in-flight responses carrying the
same hint cannot collapse the target to 1 in a single round trip.

Writes never hold a read slot, but they wait for an active 429 cooldown before
they are sent: a request sent into a queue that just answered 429 will only
receive another 429.

### Retries

Every retry decision lives in one place; the urllib3 adapter is mounted with
`max_retries=0`.

| Condition | Reads | Writes (`POST`, `PUT`, `DELETE`, uploads, `call_method(method="POST")`) |
| --- | --- | --- |
| Connection never established (DNS failure, connection refused, connect timeout) | retried, transient budget | retried, transient budget |
| Outcome unknown (read timeout, connection dropped after sending, broken chunked body) | retried, transient budget | **never**; raises `WeclappTransportError` with `outcome_unknown=True` |
| TLS error | never | never |
| 500, 502, 503, 504 | retried, transient budget; `Retry-After` honoured (capped) | **never** |
| 429 | retried, rate-limit budget; `Retry-After` honoured (capped); starts the shared cooldown | **never** (but waits for the cooldown before sending) |
| 400 `request_timeout`, 409 `persistence` | retried, problem budget | **never** |
| 3xx | never followed; raises `WeclappRedirectError` | never followed |
| Any other 4xx | never | never |

| Budget | Default | Delay before retry *n* (0-based) |
| --- | --- | --- |
| Transient (`max_retries`) | 3 | `0.3 · 2ⁿ` s plus up to 0.3 s jitter |
| Rate limit (`rate_limit_retries`) | 5 | `2 · 2ⁿ` s plus up to 2 s jitter |
| Problem (`problem_retries`) | 1 | `0.3 · 2ⁿ` s plus jitter |

Every delay, including a server-supplied `Retry-After`, is capped at
`max_backoff` (60 s). Non-finite or unparsable `Retry-After` values are
ignored. Each logical request has its own counters, so a 429 does not consume
the transient budget.

### Timeouts

| Setting | Default | Purpose |
| --- | --- | --- |
| Client timeout (`timeout=`) | 120 s | `requests` timeout per attempt; a float or a `(connect, read)` tuple. Also bounds the wait for a read permit. |
| `X-Weclapp-Wait-Timeout-Ms` (`wait_timeout_ms=`) | 30 000 | Longest acceptable server-side queue wait. |
| `X-Weclapp-Request-Timeout-Ms` (`request_timeout_ms=`) | 110 000 | Kept below the client timeout so weclapp answers with a definitive 400 `request_timeout` instead of the client giving up while the request may still be running. |

A per-request `timeout=` shorter than the defaults (for example
`client.request("GET", "article", timeout=20)`) lowers the request-timeout
header to 90 % of the read timeout, so a short client timeout never leaves a
long-running request behind on the server. Pass `None` for either header
setting to omit the header.

### Safety rails

- **Redirects are never followed.** A 3xx raises `WeclappRedirectError` with
  the `Location` in the message. A `307`/`308` therefore cannot replay a write
  body, and the API key cannot follow a redirect to another host.
- **Same-origin guard.** Every endpoint must be a path relative to `base_url`.
  Absolute URLs, other hosts, `..` segments and URL fragments raise
  `ValueError`.
- **Path segments are encoded.** `entity_id` and `action` are percent-encoded;
  values containing `/`, `?` or `#` raise `ValueError`, so an id taken from a
  webhook payload cannot reach another endpoint.

## Reading data

### `get`

```python
order = client.get("salesOrder", "4384", {"properties": "id,orderNumber,customerId"})
page = client.get("article", params={"pageSize": 50, "active-eq": "true"})
```

With an `entity_id`, `get` returns one `WeclappEntity`. It reads
`GET salesOrder?id-eq=4384&page=1&pageSize=1` rather than `salesOrder/id/4384`,
because `/id/{id}` ignores `properties` and `includeReferencedEntities`. An
empty result raises `WeclappNotFoundError`. Without an id, `get` returns one
page as `list[WeclappEntity]` exactly as weclapp sends it (no default sort).

### `get_all`

```python
orders = client.get_all(
    "salesOrder",
    {"status-eq": "ORDER_CONFIRMED", "properties": "id,orderNumber"},
    limit=5000,
    max_records=50_000,
)
```

Everything after `params` is keyword-only. With the default `threaded="auto"`:

1. Unless `params` contains `sort` or `orderBy`, weclappy adds `sort=id` so
   that pages are stable. Pass `{"sort": None}` to opt out (the key is then
   removed and weclapp's own order applies).
2. The page size is `pageSize` from `params` or 1000, reduced to `limit` when
   that is smaller.
3. Page 1 is read sequentially.
4. If page 1 is short, or already holds `limit` rows, the read is complete: no
   count request, no thread pool. Most small reads cost exactly one request.
5. Otherwise weclappy calls `GET {entity}/count` with the filter part of
   `params` (pagination and projection keys are stripped). If the count
   exceeds `max_records`, `WeclappPaginationError` is raised before any further
   page is fetched.
6. Pages 2 to N are fetched concurrently. At most
   `min(max_workers, controller target)` pages are in flight, and the window
   follows the controller as feedback arrives.
7. Pages are merged in page order. A duplicate id across pages, or fewer rows
   than counted, raises `WeclappPaginationError`: the data set changed during
   the read, and the caller should retry it.

`threaded=True` is an alias for `"auto"`. `threaded=False` reads every page
sequentially until a short page, without a count request; duplicate ids still
raise, `max_records` is checked as rows arrive, and there is no shortfall
check. `max_workers` lowers the parallelism ceiling for one call and must not
exceed the client's `max_concurrency` (otherwise `ValueError`).

Offset pagination is not a snapshot. Records created after the count request
are not included, and records that change their sort position during the read
are detected (duplicates, shortfall) but not repaired. For long exports, use
`iter_keyset`.

`strategy="ids"` implements the batching pattern weclapp recommends for large
projections: it reads only the ids with the same filters (`properties=id`),
then fetches the rows with the full projection through `get_by_ids`.

```python
orders = client.get_all(
    "salesOrder",
    {
        "status-eq": "ORDER_CONFIRMED",
        "properties": "id,orderNumber,customerId,orderItems",
        "includeReferencedEntities": "customerId",
    },
    strategy="ids",
)
```

### `get_by_ids`

```python
rows = client.get_by_ids("article", ["4384", "4390", "4401"], {"properties": "id,name"})
```

Reads specific records with `GET {entity}?id-in=[...]` in concurrent chunks.
Duplicate ids are removed, results come back in the order of `ids`, and ids
weclapp no longer knows are silently absent (an id list is a snapshot). Each
chunk holds at most `chunk_size` ids (default 500) and is split further so no
URL exceeds `max_url_length` (default 8000 bytes). Both defaults come from
measurements on the weclapp sandbox: the edge in front of weclapp rejects URLs
of about 8.9 KB with HTTP 400, and 640 numeric ids fit below that, so 500
leaves headroom. Each chunk sends an explicit `pageSize` equal to its length,
because `id-in` is paginated like any other list request.

### `iter_all` and `iter_keyset`

```python
for article in client.iter_all("article", {"properties": "id,articleNumber"}, limit=10_000):
    print(article.articleNumber)

for party in client.iter_keyset("party", {"properties": "id,company", "partyType-eq": "CUSTOMER"}):
    print(party.id, party.company)
```

`iter_all` is a sequential generator over offset pages (default `sort=id`,
duplicate check, only the seen ids are kept in memory).

`iter_keyset` paginates with `sort=id` and `id-gt=<last id>` instead of page
offsets. It never skips or repeats a row while the data set changes, which
makes it the right iterator for long exports and reports. `params` must not
contain `page`, `sort`, `orderBy` or `id-gt`; `id` must be in the projection.
Pass `start_after="<id>"` to resume an interrupted export.

### `count`

```python
open_orders = client.count("salesOrder", {"status-eq": "ORDER_CONFIRMED"})
```

`GET {entity}/count` with the filter part of `params`; returns an `int`.

### `additionalProperties` and `includeReferencedEntities`

```python
articles = client.get(
    "article",
    params={
        "properties": "id,articleNumber,unitId,unit:id,unit:name",
        "additionalProperties": "currentSalesPrice",
        "includeReferencedEntities": "unitId",
        "pageSize": 5,
    },
)
for article in articles:
    print(article.articleNumber, article.currentSalesPrice, article.unit.name)
```

`additionalProperties` are computed, read-only values; weclappy merges each
row's value onto its entity. `includeReferencedEntities` side-loads the
referenced records; `article.unit` resolves `article.unitId` against them.
Referenced fields use colon projection (`unit:id,unit:name`); include the
referenced `id` so the record can be indexed.

### `WeclappResponse`

Every list read accepts `return_weclapp_response=True` and then returns a
`WeclappResponse` with the original sections:

```python
response = client.get_all(
    "salesOrder",
    {"properties": "id,customerId,party:id,party:company", "includeReferencedEntities": "customerId"},
    limit=100,
    return_weclapp_response=True,
)
response.result                    # list[WeclappEntity]
response.additional_properties     # {"name": [value_per_row, ...]} or None
response.referenced_entities       # {"party": {"<id>": {...}}}, id-indexed
response.raw_referenced_entities   # weclapp's native {"party": [{...}, ...]}
response.raw_response              # the merged raw response
```

## Entities

Read methods return `WeclappEntity`, a `dict` subclass. Dict code keeps
working; attribute access adds:

- **Fields as attributes:** `order.orderNumber` is `order["orderNumber"]`.
- **Reference resolution:** `order.customer` resolves `order.customerId`
  against the response's `referencedEntities` (also when the bucket name
  differs, e.g. `customerId` → `party`). Resolved objects are cached per
  `(field, id)`.
- **Nested wrapping:** dicts and lists of dicts are wrapped recursively, so
  `order.orderItems[0].article.articleNumber` works.
- **Merged additional properties:** per-row `additionalProperties` values
  appear as fields; `entity.additional_properties` lists them.
- **Flattened custom attributes:** each `customAttributes` entry appears as a
  field named after its definition's `attributeKey`.

### Custom attributes

v2 responses carry only `attributeDefinitionId` plus a typed value. To name the
flattened field, weclappy loads `customAttributeDefinition` (`id,
attributeKey, attributeType, readOnly`) once per client, lazily, under a lock,
on the first row that needs it. If the definitions are permanently unreadable
(a non-transient 4xx such as missing permission), a warning is logged and
custom attributes stay unflattened; transient errors propagate so the entity
shape never silently varies. Call `client.refresh_attribute_definitions()`
after creating new definitions in a running process.

Existing, writable flattened attributes can be assigned; `to_payload()` folds
them back into the `customAttributes` array under the correct typed field:

```python
article = client.get("article", "4384", {"properties": "id,version,customAttributes"})
article.myAttributeKey = "new value"   # an existing, non-readOnly custom attribute
client.put("article", article.id, article.to_payload())
```

Definitions marked `readOnly` raise locally. The flattened interface never adds
an attribute that is absent from the entity; to add one, send an explicit v2
`customAttributes` item (`{"attributeDefinitionId": ..., "stringValue": ...}`).
All other fields are read-only via attribute syntax (`order.id = ...` raises
`AttributeError`); build an explicit payload dict instead.

### Collisions with dict methods

Fields named like `dict` methods (`items`, `keys`, `values`, `get`, `copy`,
`update`, `pop`, ...) are reachable only by item access: `entity["items"]`. A
built-in field also wins over a custom attribute or additional property of the
same name; the raw data remains under `entity["customAttributes"]`.

### `to_payload` and `unwrap`

`entity.copy()`, `dict(entity)` and `json.dumps(entity)` include the synthetic
flattened and merged keys. `to_payload()` is the only supported path into a
write: it drops merged additional properties, rebuilds `customAttributes`,
omits resolved reference objects and recursively converts nested entities.
`WeclappEntity.unwrap(value)` does the same for any structure that contains
entities. Write methods call it for you, so `client.put("article", a.id, a)` is
equivalent to passing `a.to_payload()`. A payload built from a read entity keeps
`id` and `version`; for creates, build the payload explicitly.

## Writing data

```python
created = client.post("party", {"partyType": "ORGANIZATION", "company": "Acme GmbH"})
client.put("party", created["id"], {"version": created["version"], "company": "Acme AG"})
client.delete("party", created["id"])

client.call_method("salesOrder", "createSalesInvoice", "4384", method="POST", data={})
pdf = client.download("salesInvoice", "4400", action="downloadLatestSalesInvoicePdf")
client.upload(
    "document",
    b"%PDF-1.7 ...",
    action="upload",
    params={"entityName": "salesOrder", "entityId": "4384", "name": "terms.pdf"},
    filename="terms.pdf",
)
```

| Method | Request | Returns |
| --- | --- | --- |
| `post(entity, data, params=None)` | `POST {entity}` | parsed JSON |
| `put(entity, entity_id, data, params=None)` | `PUT {entity}/id/{id}?ignoreMissingProperties=true` | parsed JSON |
| `delete(entity, entity_id, params=None)` | `DELETE {entity}/id/{id}` | `{}` on 204 |
| `call_method(entity, action, entity_id=None, *, method="GET", data=None, params=None)` | `GET`/`POST {entity}[/id/{id}]/{action}` | parsed body |
| `upload(entity, data, entity_id=None, action=None, params=None, *, content_type=None, filename=None)` | `POST` raw bytes | parsed JSON |
| `download(entity, entity_id=None, action=None, params=None)` | `GET`; `action` defaults to `download` when an id is given | `{"content": bytes, "content_type": str, "filename": str}` |
| `request(method, endpoint, *, params, json, data, headers, timeout)` | any same-origin request | parsed body |

Parsed bodies: JSON is decoded; 204 or an empty body becomes `{}`; text media
types become `{"content": str, "content_type": str}`; other media types become
`{"content": bytes, "content_type": str}` plus `filename` when the response
names one. Upload content types come from `content_type`, else from the
`filename` extension (`infer_content_type`), else `application/octet-stream`.

`put` sends `ignoreMissingProperties=true` unless `params` sets it, so a
partial payload updates only the fields it contains. Pass
`{"ignoreMissingProperties": False}` for full-replacement semantics. `dryRun`
and other endpoint options are ordinary `params`.

### Writes are not retried

A write is retried only when the connection was never established. After a
5xx, a 429, a read timeout or a dropped connection, the write may or may not
have been processed, and repeating it could create a second invoice or book
stock twice. weclappy raises instead and leaves the decision to you.

### Recipe: optimistic locking

Include the `version` you read. If someone else changed the record in between,
weclapp rejects the write and weclappy raises `WeclappOptimisticLockError`:

```python
from weclappy import WeclappOptimisticLockError

for _attempt in range(3):
    order = client.get("salesOrder", "4384", {"properties": "id,version,commission"})
    try:
        client.put("salesOrder", order.id, {"version": order.version, "commission": "B-17"})
        break
    except WeclappOptimisticLockError:
        continue  # re-read, re-apply the change, try again
```

### Recipe: read after an unknown outcome

```python
import time

from weclappy import WeclappTransportError


def create_party_once(client, customer_number):
    try:
        return client.post(
            "party",
            {"partyType": "ORGANIZATION", "company": "Acme", "customerNumber": customer_number},
        )
    except WeclappTransportError as exc:
        if not exc.outcome_unknown:
            raise  # provably never sent: safe to repeat later
        for delay in (0, 2, 5, 10, 20, 30):
            time.sleep(delay)
            found = client.get("party", params={"customerNumber-eq": customer_number})
            if found:
                return found[0]  # the write went through
        raise  # still unknown: escalate instead of writing again
```

Use a business key you control (an external reference, a customer number, a
note marker) so a lost response can be reconciled. A 5xx or 429 on a write
raises the typed HTTP error; treat it like an unknown outcome unless the
endpoint is idempotent.

## Unofficial endpoints

> **Unofficial.** The following methods use endpoints that weclapp lists only
> in its hidden OpenAPI document. They carry no compatibility promise and
> weclapp does not announce changes to them. Use them deliberately, keep a
> fallback to the official API, and keep them off critical paths.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `query(entity, *, filter=None, properties=None, include_referenced_entities=None, additional_properties=None, order_by=None, page=None, page_size=None, offset=None, serialize_nulls=None, return_weclapp_response=False)` | `POST {entity}/query` | Filter expression in the body, so long `id in [...]` lists avoid the URL limit. |
| `query_count(entity, *, filter=None)` | `POST {entity}/count` | Count with a body filter expression. |
| `batch_query(requests_)` | `POST batch/query` | Up to 500 relative GET queries in one call; returns `list[BatchResult]` ordered by request index. |
| `openapi(*, include_hidden=False)` | `GET meta/openapi.yaml` | The tenant's OpenAPI document as YAML text; `include_hidden=True` adds the hidden endpoints. |

```python
from weclappy import WeclappAPIError

ids = ["4384", "4390"]
try:
    rows = client.query(
        "article",
        filter=f"id in [{','.join(ids)}]",
        properties=["id", "name"],
        page_size=len(ids),
    )
except WeclappAPIError:
    rows = client.get_by_ids("article", ids, {"properties": "id,name"})  # official fallback

for result in client.batch_query(["article/count", "party?properties=id&pageSize=5"]):
    print(result.index, result.status, result.ok, result.body)
```

All four count as reads: they hold a read permit and are retried like `GET`.
`batch_query` rejects more than 500 requests locally; a failing sub-request
does not fail the batch, so check `BatchResult.ok` per entry. weclapp rejects
`/id/{id}` paths inside a batch.

## Observability

### `on_response` and `RequestMetrics`

```python
from weclappy import RequestMetrics, Weclapp


def record(metrics: RequestMetrics) -> None:
    if metrics.wait_ms:
        print(f"{metrics.method} {metrics.path} waited {metrics.wait_ms:.0f} ms ({metrics.wait_reason})")


client = Weclapp.for_tenant("acme", api_key, on_response=record)
```

The hook runs after every physical attempt, including failed attempts and
attempts that will be retried. `RequestMetrics` fields: `method`, `path` (no
query string), `status_code` (`None` for transport failures), `duration_ms`,
`wait_ms`, `wait_reason`, `correlation_id`, `attempt` (1-based),
`will_retry`, `retry_delay`, `concurrency_target`, `error` (exception class
name), and the derived `processing_ms` (duration minus queue wait). Exceptions
raised by the hook are logged and never propagate.

### `stats`

```python
snapshot = client.stats
print(snapshot.requests, snapshot.retries, snapshot.rate_limited, snapshot.max_wait_ms)
print(snapshot.as_dict())
print(client.concurrency.snapshot())  # target, active, ceiling, cooldown_remaining, ...
client.reset_stats()
```

`StatsSnapshot` aggregates every attempt of the client: `requests`, `retries`,
`rate_limited`, `transport_errors`, `http_errors`, `slow_requests`,
`duration_seconds` (client-side), `request_seconds` (estimated server processing,
weclapp's load measure), `wait_seconds`, `max_wait_ms`,
and `by_status`.

### Logging

weclappy logs through the standard `logging` module under the names
`weclappy` and `weclappy.entity` and never configures handlers itself.

| Record | Level | Content |
| --- | --- | --- |
| `[API]` | INFO (WARNING for transport errors) | method, path, status, duration |
| `[API_SLOW]` | WARNING | requests at or above `slow_threshold_ms` (2000 ms) |
| `[API_RETRY]` | WARNING | reason, retry number, budget, delay |
| `[API_QUEUE]` | INFO | `wait_ms`, wait reason, correlation id |

Log records and metrics never contain the API key, query strings or bodies.
Exception messages do include up to 4000 characters of the error response
body, and an exception's `response.request.headers` still carries the
`AuthenticationToken` header. Do not serialise raw `requests` objects into
error reporters.

## Extension points

```python
import requests

from weclappy import (
    ConcurrencyController,
    ConcurrencySettings,
    OutgoingRequest,
    RetryPolicy,
    Weclapp,
)

# One controller per tenant, shared by every client that talks to it.
shared = ConcurrencyController(ConcurrencySettings(max_concurrency=6))


def tag(request: OutgoingRequest) -> None:
    request.headers["X-Correlation-ID"] = f"sync-job-{request.attempt}"


session = requests.Session()  # adapters must not retry (max_retries=0, the default)
client = Weclapp.for_tenant(
    "acme",
    api_key,
    session=session,
    before_request=tag,
    concurrency=shared,
    retry_policy=RetryPolicy(max_retries=2, rate_limit_retries=8, max_backoff=30.0),
)
```

| Argument | Use |
| --- | --- |
| `session=` | Bring your own `requests.Session` (proxies, certificates, custom adapters). weclappy sets its default headers on it but mounts no adapter, and `close()` leaves it open. |
| `before_request=` | Called with an `OutgoingRequest` (`method`, `url`, `path`, `attempt`, mutable `headers` and `params`) before every attempt. The API key is not part of it. An exception aborts the request. |
| `concurrency=` | A shared `ConcurrencyController`. Overrides `max_concurrency`. `close()` on a client does not close a controller it was given. |
| `retry_policy=` | A complete, immutable `RetryPolicy`; overrides the individual retry arguments. |
| `request()` | The public escape hatch for endpoints without a helper; same load control, retries, hooks and parsing as every other method. |

## Errors

```text
WeclappError
├── WeclappConcurrencyTimeoutError     no read permit before the client timeout
└── WeclappAPIError                    any failed request (response attached when there is one)
    ├── WeclappTransportError          no response: .request_sent, .outcome_unknown
    ├── WeclappRateLimitError          429 (reads: after the rate-limit budget)
    ├── WeclappNotFoundError           404, or empty get(entity, entity_id)
    ├── WeclappValidationError         400 with validation problems
    ├── WeclappOptimisticLockError     stale version (409 or 400 optimistic_lock)
    ├── WeclappRequestTimeoutError     400 request_timeout
    ├── WeclappAuthenticationError     401, 403
    ├── WeclappRedirectError           3xx (never followed)
    └── WeclappPaginationError         duplicate ids, shortfall, max_records exceeded
```

`except WeclappAPIError` still catches everything request-related. Every
`WeclappAPIError` exposes `status_code`, `url`, `response`, `response_text`,
weclapp's problem fields (`error`, `detail`, `title`, `error_type`,
`validation_errors`, `messages`), header helpers (`retry_after`, `wait_ms` as
float, `wait_reason`, `correlation_id`), `get_validation_messages()`,
`get_all_messages()`, and the predicates `is_not_found`,
`is_validation_error`, `is_optimistic_lock`, `is_rate_limited`,
`is_request_timeout`, `is_persistence_error` and `is_retryable`.
`is_retryable` describes the response, not whether repeating a particular
business operation is safe.

```python
from weclappy import WeclappAPIError, WeclappNotFoundError, WeclappValidationError

try:
    order = client.get("salesOrder", "4384")
except WeclappNotFoundError:
    order = None
except WeclappValidationError as exc:
    print(exc.get_validation_messages())
except WeclappAPIError as exc:
    print(exc.status_code, exc.error_type, exc.correlation_id)
    raise
```

## Configuration reference

All arguments after `api_key` are keyword-only.

| Argument | Default | Meaning |
| --- | --- | --- |
| `base_url` | required | Absolute HTTP(S) API root ending in `/webapp/api/v<N>`, e.g. `https://acme.weclapp.com/webapp/api/v2/`. No query or fragment. |
| `api_key` | required | weclapp API token, sent as `AuthenticationToken`. |
| `timeout` | `120.0` | Client timeout in seconds, or `(connect, read)`. |
| `max_retries` | `3` | Transient budget: 5xx and transport failures on reads, unsent writes. |
| `backoff_factor` | `0.3` | Base of the transient backoff (`factor · 2ⁿ` + jitter). |
| `rate_limit_retries` | `5` | Retries after 429 on reads. |
| `rate_limit_backoff` | `2.0` | Base delay after a 429, doubled per attempt. |
| `problem_retries` | `1` | Retries for 400 `request_timeout` / 409 `persistence` on reads. |
| `max_backoff` | `60.0` | Cap for every delay including `Retry-After`. |
| `retry_policy` | `None` | A complete `RetryPolicy`; overrides the five arguments above. |
| `wait_timeout_ms` | `30000` | `X-Weclapp-Wait-Timeout-Ms`; `None` omits it. |
| `request_timeout_ms` | `110000` | `X-Weclapp-Request-Timeout-Ms`; `None` omits it. Lowered automatically for shorter per-request timeouts. |
| `max_concurrency` | `10` | Ceiling of the adaptive controller. |
| `concurrency` | `None` | A shared `ConcurrencyController`; overrides `max_concurrency`. |
| `session` | `None` | A caller-owned `requests.Session`. |
| `before_request` | `None` | Hook called with `OutgoingRequest` before every attempt. |
| `on_response` | `None` | Hook called with `RequestMetrics` after every attempt. |
| `user_agent` | `weclappy/<version>` | `User-Agent` header. |
| `pool_connections` | `100` | Connection pools of the default adapter. |
| `pool_maxsize` | `100` | Connections per pool of the default adapter. |
| `slow_threshold_ms` | `2000` | Requests at or above this duration log as `[API_SLOW]` and count as slow. |

`ConcurrencySettings` (for a custom controller): `max_concurrency=10`,
`initial_concurrency=2`, `concurrency_wait_threshold_ms=250.0`,
`load_wait_threshold_ms=2000.0`, `min_rate_limit_cooldown=2.0`.

## Migration from 0.x

1.0 is a breaking release. Coming from 0.6.x or the unreleased 0.7.0 branch:

- **Python ≥ 3.12.** 3.9 to 3.11 are no longer supported.
- **Package layout.** `weclappy` is now a package (`src/weclappy/`) with
  `py.typed` and `__version__`. Import public names from `weclappy` only;
  module paths such as `weclappy.client` are implementation details.
- **Keyword-only arguments.** Every constructor argument after `api_key`
  (including `pool_connections`, `pool_maxsize`, `slow_threshold_ms`);
  everything after `params` in `get_all` (`limit`, `threaded`, `max_workers`,
  `return_weclapp_response`, ...); `return_weclapp_response` in `get`;
  `method`, `data` and `params` in `call_method`; `content_type` and
  `filename` in `upload`.
- **Parameter renames.** `id` → `entity_id` in `get`, `put`, `delete`,
  `upload` and `download`, and `endpoint` → `entity` as the first parameter of
  every method. Positions are unchanged, so positional calls keep working:
  `client.get("article", id="1")` becomes `client.get("article", "1")` or
  `client.get("article", entity_id="1")`. The `id=` keyword still works in
  1.x but emits a `DeprecationWarning` and is removed in 2.0.
- **Extra requests you may notice.** A large `get_all` issues one
  `GET {entity}/count` before fetching pages concurrently; the first read
  that returns `customAttributes` loads `customAttributeDefinition` once per
  client. Test doubles must answer both.
- **`get_all` defaults to `threaded="auto"`** (0.6.x: sequential). Small reads
  cost one request; large reads count and fetch pages in parallel. Pass
  `threaded=False` to keep strictly sequential reads.
- **Writes are never retried** on 5xx, 429, timeouts or dropped connections.
  0.6.0 retried POST/PUT/DELETE on 5xx and 429, which could duplicate writes.
  Handle `WeclappTransportError.outcome_unknown` with a read-back (see
  [above](#recipe-read-after-an-unknown-outcome)).
- **Redirects are not followed**; a 3xx raises `WeclappRedirectError`.
- **`base_url` must be the API root** (`…/webapp/api/v2`); anything else raises
  `ValueError`. `Weclapp.for_tenant("acme", key)` builds it for you.
- **Absolute URLs are rejected** as endpoints. Pass paths relative to
  `base_url` (`"salesOrder/count"`, not
  `"https://acme.weclapp.com/webapp/api/v2/salesOrder/count"`).
- **`_send_request` and `_check_response` are gone.** Use `request()` for raw
  calls and `before_request`/`on_response` or `session=` for the customisation
  that previously needed private methods. Replace `WeclappEntity._unwrap` with
  `WeclappEntity.unwrap` or `entity.to_payload()`.
- **`WeclappAPIError.wait_ms` is a float** (0.7.0 branch: a string).
- **Default sort.** `get_all`, `iter_all` and `strategy="ids"` add `sort=id`
  when neither `sort` nor `orderBy` is given; pass `{"sort": None}` for
  weclapp's default order. `get()` without an id is unchanged.
- **`max_workers` is capped at `max_concurrency`** (default 10). A larger
  value is clamped with a warning; raise `max_concurrency` on the client to
  allow more concurrent reads.
- **The HTTP adapter never retries** (`max_retries=0`); every retry decision
  is made by the client. Code that read or copied retry settings from
  `session.get_adapter(...)` must use `retry_policy=` instead, and a custom
  session goes in through `session=`.
- **New default headers.** Every request sends
  `X-Weclapp-Wait-Timeout-Ms: 30000`, `X-Weclapp-Request-Timeout-Ms: 110000`
  (0.7.0 branch: 120000, equal to the client timeout) and
  `User-Agent: weclappy/<version>`. Pass `None` to omit a timeout header.
- **Typed errors.** Existing `except WeclappAPIError` blocks keep working; the
  new subclasses allow narrower handling. Duplicate-page errors are now
  `WeclappPaginationError`.
- **Module constants** `DEFAULT_MAX_WORKERS`, `DEFAULT_MAX_RETRIES`,
  `DEFAULT_BACKOFF_FACTOR`, `SAFE_RETRY_METHODS` and `TRANSIENT_STATUS_CODES`
  are no longer exported from `weclappy`.

The full list is in the [1.0.0 changelog entry](https://github.com/Wals-pro/weclappy/blob/main/CHANGELOG.md).

## Versioning and support policy

- weclappy follows [Semantic Versioning](https://semver.org/). The public API
  is everything exported in `weclappy.__all__` plus the documented methods and
  attributes of those objects. Names starting with an underscore, module paths
  below `weclappy`, log message texts and the exact retry jitter are not part
  of it.
- Deprecations emit a `DeprecationWarning` for at least one minor release
  before removal in the next major release.
- Supported Python versions are the three newest CPython feature releases
  (currently 3.12, 3.13, 3.14). Dropping a version that reached end of life is
  done in a minor release and noted in the changelog.
- Pin a compatible range in applications: `weclappy>=1.0,<2`.
- Security fixes target the latest 1.x release; see [SECURITY.md](https://github.com/Wals-pro/weclappy/blob/main/SECURITY.md).

## Development

```bash
git clone https://github.com/Wals-pro/weclappy.git
cd weclappy
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"        # or: python -m pip install -e ".[dev]"

ruff check src tests examples
ruff format --check src tests examples
mypy
pytest -m "not integration" --cov=weclappy --cov-report=term-missing --cov-fail-under=90
```

Integration tests (`-m integration`) need a live tenant; write tests are
additionally marked `write` and need explicit opt-in. See
[CONTRIBUTING.md](https://github.com/Wals-pro/weclappy/blob/main/CONTRIBUTING.md) and [RELEASING.md](https://github.com/Wals-pro/weclappy/blob/main/RELEASING.md). The
[examples](https://github.com/Wals-pro/weclappy/tree/main/examples) use only the public API and read credentials from the
environment.

## License

MIT. See [LICENSE](https://github.com/Wals-pro/weclappy/blob/main/LICENSE).
