# weclappy

A small Python client for the weclapp REST API.

`weclappy` keeps the API close to ordinary HTTP: choose an endpoint, pass
query parameters or a JSON payload, and receive Python objects. It adds the
parts that are useful in most integrations—authentication, connection pooling,
pagination, safe retries, structured errors, and binary transfers—without
entity-specific business logic.

- Python 3.9+
- one runtime dependency: [`requests`](https://pypi.org/project/requests/)
- generic access to the weclapp API instead of generated entity classes
- sequential or parallel pagination
- convenient `WeclappEntity` objects that remain compatible with `dict`

This is an independent, community-maintained project and is not affiliated
with weclapp. The project is still below version 1.0, so public interfaces may
evolve. Breaking changes are documented in
[CHANGELOG.md](https://github.com/Wals-pro/weclappy/blob/main/CHANGELOG.md).
Pin the version in production integrations when reproducible upgrades matter.

## Installation

```bash
python -m pip install weclappy
```

For new integrations, use the weclapp API v2 base URL:

```text
https://your-tenant.weclapp.com/webapp/api/v2
```

The client does not choose an API version for you; it uses the URL you provide.
The documentation and examples in this repository target v2.

## Quick start

Keep credentials outside your source code:

```bash
export WECLAPP_BASE_URL="https://your-tenant.weclapp.com/webapp/api/v2"
export WECLAPP_API_KEY="your-api-key"
```

Then make a read-only request:

```python
import os

from weclappy import Weclapp

with Weclapp(
    os.environ["WECLAPP_BASE_URL"],
    os.environ["WECLAPP_API_KEY"],
) as client:
    articles = client.get(
        "article",
        params={
            "active-eq": "true",
            "pageSize": 5,
            "properties": "id,articleNumber,name",
            "sort": "id",
        },
    )
    for article in articles:
        print(article.id, article.articleNumber, article.name)
```

`get()` without an `id` reads one API page. Inside the same `with` block, use
`get_all()` when the client should follow pagination for you, and give the
query a projection and stable sort:

```python
orders = client.get_all(
    "salesOrder",
    params={"properties": "id,orderNumber", "sort": "id"},
    limit=2_000,
)
```

Filters, projections, sorting, `additionalProperties`, and other query options
are ordinary entries in `params`; their exact availability depends on the
weclapp endpoint.

The shorter `client` snippets below assume they run inside an active
`with Weclapp(...) as client:` block.

## Public API at a glance

| Method | Purpose | Typical return value |
| --- | --- | --- |
| `get(endpoint, id=None, params=None)` | Read one record by id or one list page | `WeclappEntity` or `list[WeclappEntity]` |
| `get_all(entity, params=None, limit=None, ...)` | Read all matching pages | `list[WeclappEntity]` |
| `iter_all(entity, params=None, limit=None)` | Yield matching records page by page | iterator of `WeclappEntity` |
| `post(endpoint, data, params=None)` | Create a record | API JSON |
| `put(endpoint, id, data, params=None)` | Update a record | API JSON |
| `delete(endpoint, id, params=None)` | Delete a record | usually `{}` |
| `call_method(entity, action, ...)` | Call a GET or POST entity action | API JSON or binary result |
| `upload(endpoint, data, ...)` | Upload bytes | API JSON |
| `download(endpoint, id=None, ...)` | Download a file | `{"content": bytes, "content_type": str}` |
| `request(method, endpoint, ...)` | Use a relative endpoint as an escape hatch | parsed API response |

Response parsing is consistent across methods:

| API response | Python value |
| --- | --- |
| JSON | decoded `dict`, `list`, or scalar; read result rows become `WeclappEntity` |
| 204 or empty body | `{}` |
| text media type | `{"content": str, "content_type": str}` |
| other media type | `{"content": bytes, "content_type": str}` plus `filename` when supplied |

All endpoint arguments are relative to the configured base URL. Absolute and
cross-origin endpoint URLs are rejected so the authentication token cannot be
sent to another host accidentally. Redirect responses are surfaced as errors
instead of being followed automatically; this also prevents a `307` or `308`
from replaying a write body.

The client owns a pooled HTTP session. Prefer the context-manager form shown
above, or call `client.close()` when a long-lived client is no longer needed.

## Entities, custom attributes, and references

Read methods return `WeclappEntity`, a `dict` subclass. Existing dict-style
code keeps working, while attribute access makes common reads shorter. This
article query deliberately projects the result fields, the additional price,
and the referenced unit:

```python
article = client.get(
    "article",
    id="12345",
    params={
        "properties": (
            "id,version,articleNumber,name,unitId,customAttributes,"
            "unit:id,unit:name"
        ),
        "additionalProperties": "currentSalesPrice",
        "includeReferencedEntities": "unitId",
    },
)

print(article["articleNumber"])
print(article.currentSalesPrice)  # merged, read-only additionalProperty
print(article.unitId)             # native reference id on the article
print(article.unit.name)          # side-loaded referenced entity
```

The include parameter names the reference field (`unitId`). Referenced fields
use colon projection (`unit:id,unit:name`), not `unit.id`. Include `unit:id`:
the client needs that id to normalize the native reference list and resolve
`article.unit`.

`customAttributes` are exposed under the matching
`attributeDefinition.attributeKey` (the configured internal key). This may
trigger one cached definition lookup for the lifetime of the client.

Flattened custom attributes are writable through attribute syntax. Passing a
fetched entity to `put()` or an appropriate update-style POST `call_method()`
converts it back to an API payload and removes synthetic additional-property
fields:

```python
setattr(article, "yourExistingAttributeKey", "new value")
client.put("article", id=article.id, data=article, params={"dryRun": True})
```

Built-in fields are intentionally read-only through attribute syntax. Update
them with an explicit payload such as
`client.put("article", id=article.id, data={"description": "Updated"})`.
Create calls are different: pass an explicit dictionary to `post()` instead of
reusing a fetched entity, because ids, versions, and other response metadata
are not valid create fields.

### Custom-attribute write boundaries

Flattened assignment updates an existing `customAttributes` entry that was
present in the read response. It does not invent a new definition or append a
missing entry. For a safe update roundtrip:

1. request `id,version,customAttributes` plus any normal fields you need;
2. only select a definition whose `readOnly` value is `false` and for which the
   API credential has update permission;
3. change the flattened `attributeKey`; and
4. pass the entity to `put()`—preferably with `dryRun=True` first.

For create payloads, or when adding an attribute not present on the fetched
entity, provide the native `customAttributes` array yourself. Each entry needs
its `attributeDefinitionId` and the value field dictated by
`attributeType`:

| Definition type | Native value field | Python/wire value |
| --- | --- | --- |
| `BOOLEAN` | `booleanValue` | `bool` |
| `DATE` | `dateValue` | Unix timestamp in milliseconds (`int`) |
| `DECIMAL`, `INTEGER` | `numberValue` | decimal string |
| `ENTITY` | `entityId` | entity id string |
| `REFERENCE` | `entityReferences` | list of `{"entityId": str, "entityName": str}` |
| `LIST` | `selectedValueId` | selectable-value id string |
| `MULTISELECT_LIST` | `selectedValues` | list of `{"id": str}` |
| `STRING`, `LARGE_TEXT`, `URL` | `stringValue` | string |

Do not send the flattened `attributeKey` as a top-level API property. Read-only
definitions, system attributes, and computed `additionalProperties` are not
writable. `version` is useful on updates for optimistic locking even though it
is response metadata; omit `id`, `version`, `createdDate`, and
`lastModifiedDate` when creating a new entity.

Nested dictionaries and dictionaries inside lists are wrapped recursively.
For example, a requested `orderItems.articleId` reference can be read as
`order.orderItems[0].article.articleNumber`.

Two edge cases are worth knowing:

- A built-in field wins if its name collides with a custom attribute or an
  additional property. The raw source data remains available through keys such
  as `entity["customAttributes"]`.
- Names that collide with `dict` methods—such as `items`, `keys`, or `get`—must
  be accessed with brackets: `entity["items"]`.

## Pagination

Adaptive threaded pagination is the default for `get_all()`. It uses the
queue/load feedback returned by weclapp to increase concurrency when the API
is clear and reduce it before sustained queueing or `429` responses occur.
For small or ordering-sensitive reads, opt into sequential pagination:

```python
articles = client.get_all(
    "article",
    params={"properties": "id,articleNumber", "sort": "id"},
    limit=5_000,
    threaded=False,
)
```

For large result sets, the adaptive default can be used directly:

```python
articles = client.get_all(
    "article",
    params={"properties": "id,articleNumber", "sort": "id"},
    limit=20_000,
)
```

Threaded mode performs an additional count request, keeps API page order in the
returned list, and raises if any page fails. `max_workers` is an optional
adaptive ceiling, not a fixed worker count; the internal safety ceiling is 10
when it is omitted. Always provide a stable sort such as `sort=id` when a
result spans pages; otherwise concurrent changes or an unstable server order
can move records across page boundaries.

When projected rows contain `id`, the client detects duplicate IDs before
merging or yielding a page. This catches a common symptom of a moving result
set, but it cannot turn offset pagination into a database snapshot. `iter_all`
keeps only the IDs seen for that check, not the complete result collection.

When the full result should not be retained in memory, iterate sequentially:

```python
for article in client.iter_all(
    "article",
    params={
        "pageSize": 500,
        "properties": "id,articleNumber",
        "sort": "id",
    },
    limit=10_000,
):
    process(article)
```

## Structured responses

Most callers can use the merged entity view. When the original response
sections are also needed, request a `WeclappResponse`:

```python
response = client.get_all(
    "salesOrder",
    limit=100,
    params={
        "additionalProperties": "availability",
        "includeReferencedEntities": "customerId",
        "properties": (
            "id,orderNumber,customerId,party:id,party:company,"
            "party:firstName,party:lastName"
        ),
        "sort": "id",
    },
    return_weclapp_response=True,
)

orders = response.result
additional = response.additional_properties
references = response.referenced_entities
raw = response.raw_response
```

`additionalProperties` are computed, read-only values. The client merges the
value at each result index onto its matching entity for convenience, while
`response.additional_properties` retains the index-aligned arrays. These
synthetic fields are removed by `entity.to_payload()`.

`response.referenced_entities` is the client-normalized shape
`{entity_type: {id: entity}}`. The API-native shape remains available at
`response.raw_referenced_entities` (and in
`response.raw_response["referencedEntities"]`), where each entity type contains
a list. This preserves valid colon projections that omit an `id` and therefore
cannot enter the normalized map. Result rows retain their native `*Id` fields;
attribute access such as `article.unit` is only a convenience resolver over
those side-loaded lists.

## Writes and retry safety

Writes are deliberately explicit through `post()`, `put()`, `delete()`, and
POST `call_method()` calls.

Where the endpoint supports it, a dry run can be passed as a normal query
parameter:

```python
client.post("salesOrder", payload, params={"dryRun": True})
```

Automatic HTTP-status retries apply only to `GET`, `HEAD`, and `OPTIONS`.
`POST`, `PUT`, and `DELETE` do not receive automatic transport, status, or
problem-response retries because a lost response can make a successful write
look like a failure. For important business operations, reconcile the result
with a stable business identifier before deciding whether to repeat a write.

## Timeouts and retries

The defaults are conservative and can be configured per client:

| Setting | Default | Meaning |
| --- | ---: | --- |
| `timeout` | `120` seconds | Client-side request timeout |
| `max_retries` | `3` | Shared safe-method retry budget for transport failures, 429, and transient 5xx responses |
| `backoff_factor` | `0.3` | Exponential retry backoff; `Retry-After` is respected |
| `problem_retries` | `1` | Extra retry for safe requests on `request_timeout` or `persistence` problems |
| `wait_timeout_ms` | `30000` | `X-Weclapp-Wait-Timeout-Ms`; use `None` to omit |
| `request_timeout_ms` | `120000` | `X-Weclapp-Request-Timeout-Ms`; use `None` to omit |
| `slow_threshold_ms` | `2000` | Log successful slower requests at warning level |

For example, pass `timeout=60`, `max_retries=2`, or `problem_retries=0` to
`Weclapp(...)`. `client.request()` also accepts a one-off `timeout`. Setting
both retry counts to zero disables automatic response retries.

## Errors

API and transport failures raise `WeclappAPIError` with the response attached
when one is available:

```python
from weclappy import WeclappAPIError

try:
    article = client.get(
        "article",
        id="12345",
        params={"properties": "id,articleNumber"},
    )
except WeclappAPIError as exc:
    print(exc.status_code, exc.detail)
    if exc.is_not_found:
        print("Article not found")
    elif exc.is_validation_error:
        print(exc.get_validation_messages())
```

Additional helpers include `is_request_timeout`, `is_persistence_error`,
`is_retryable`, `retry_after`, `wait_ms`, `wait_reason`, `correlation_id`, and
`get_all_messages()`. A retryable error describes the response, not whether
repeating a particular business operation is safe.

## Files and custom actions

Downloads return bytes together with their media type:

```python
result = client.download(
    "salesInvoice",
    id="12345",
    action="downloadLatestSalesInvoicePdf",
)

with open("invoice.pdf", "wb") as output:
    output.write(result["content"])
```

Uploads accept bytes. The media type is inferred from `filename`, can be set
with `content_type`, and otherwise falls back to
`application/octet-stream`. A guarded upload example is available in
[`examples/upload_document.py`](https://github.com/Wals-pro/weclappy/blob/main/examples/upload_document.py).

For uncommon endpoints, use the public same-origin escape hatch instead of
accessing the internal session:

```python
count = client.request(
    "GET",
    "article/count",
    params={"filter": "active = true"},
)
print(count["result"])
```

## Logging

The library uses Python's standard `logging` module and does not configure
application logging for you. Enable it, for example, with
`logging.basicConfig(level=logging.INFO)`.

INFO logs contain the method, endpoint path, status, and duration. Query
parameters, request bodies, and the API key are omitted from these timing
records. When weclapp supplies queue or correlation headers, a separate
`[API_QUEUE]` record exposes them for diagnostics. Treat DEBUG output as
potentially sensitive in production because filters and payload metadata may
contain business data.

## Examples

The scripts in
[`examples/`](https://github.com/Wals-pro/weclappy/tree/main/examples) use only
the standard library and `weclappy`. They read credentials from environment
variables; they do not load `.env` files automatically.

```bash
cp examples/.env.example examples/.env
# Edit examples/.env, then export it in your shell:
set -a
source examples/.env
set +a

python examples/count_entities.py
```

Examples that write require `WECLAPP_ENABLE_WRITES=1` and explain their effect
before doing anything. Use those only with a tenant and record where the write
is intended.

For an optional dependency-free live contract check, run the guarded article
probe. It exercises sequential and threaded pagination with `sort=id`,
`currentSalesPrice`, and the `unitId` reference projection, then prints a JSON
report without exposing credentials:

```bash
WECLAPP_RUN_LIVE_CONTRACT=1 \
  python examples/live_contract.py
```

The probe uses `WECLAPP_BASE_URL` and `WECLAPP_API_KEY` from the environment.
It performs reads only. It can also expose the same check as a local webhook:

```bash
export WECLAPP_LIVE_CONTRACT_BEARER_TOKEN='replace-with-a-high-entropy-token'

WECLAPP_RUN_LIVE_CONTRACT=1 \
  python examples/live_contract.py --serve

curl http://127.0.0.1:8765/health
curl -X POST \
  -H "Authorization: Bearer $WECLAPP_LIVE_CONTRACT_BEARER_TOKEN" \
  http://127.0.0.1:8765/run
```

The server binds to `127.0.0.1` by default. `GET /health` only checks the
process and never needs weclapp credentials; `POST /run` returns the JSON
contract report. `WECLAPP_LIVE_CONTRACT_BEARER_TOKEN` is always required for
server mode, including on loopback, and every `/run` request must send it as
`Authorization: Bearer ...`. Use a separate high-entropy token, never the
weclapp API key. The server does not write access logs or include either token
in its reports. The stdlib server does not terminate TLS; place it behind a
TLS-enabled reverse proxy before exposing it across an untrusted network.

## Contributing

Bug reports, focused improvements, documentation fixes, and tested pull
requests are welcome. If you are unsure whether an idea fits the intentionally
small scope, opening an issue first is a good way to discuss it without doing
unnecessary work.

See
[CONTRIBUTING.md](https://github.com/Wals-pro/weclappy/blob/main/CONTRIBUTING.md)
for setup and pull-request guidance. Please report security issues privately as
described in
[SECURITY.md](https://github.com/Wals-pro/weclappy/blob/main/SECURITY.md).

## Design scope

`weclappy` is a general-purpose API client with a thin response-shaping layer.
To keep it easy to adopt, the project generally avoids generated entity models,
module-specific workflows, automatic parallel writes, and additional runtime
dependencies. Generic improvements that help integrations across weclapp
modules are very welcome.

## Related projects

- [weclapp Toolbox](https://github.com/niclas-niclasen/weclapp-toolbox) — a
  browser extension with developer tools for weclapp ERP

## License

MIT. See [LICENSE](https://github.com/Wals-pro/weclappy/blob/main/LICENSE).
