# Testing weclappy

The test suite separates fast, self-contained tests from checks against a live
weclapp tenant. Persistent writes have an additional opt-in so they cannot run
accidentally.

## Setup

From the repository root, with Python 3.12 or newer:

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

The package lives in `src/weclappy/` and is installed in editable mode, so the
tests import `weclappy` directly; there is no `sys.path` manipulation.

## Local tests

Run every test that does not contact a live tenant (a few seconds; no test
sleeps for real):

```bash
.venv/bin/pytest -m "not integration" -q
```

Run one test by name:

```bash
.venv/bin/pytest tests/test_weclappy_unit.py -k "test_name" -v
```

Coverage (the configured floor is 90 %):

```bash
.venv/bin/pytest -m "not integration" --cov=weclappy --cov-report=term-missing
```

Lint, format and type-check before sending a change:

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format src tests
.venv/bin/mypy
```

## Live integration tests

Use a dedicated test tenant and provide its API v2 URL and token:

```bash
export WECLAPP_BASE_URL="https://your-instance.weclapp.com/webapp/api/v2"
export WECLAPP_API_KEY="your-api-key"
```

The following command runs live checks that do not persist changes. Some tests
use weclapp's `dryRun` mode to validate write-shaped requests safely.

```bash
.venv/bin/pytest -m "integration and not write" -v
```

`WECLAPP_TEST_SALESORDER_ID` may be set to exercise lookup of a known existing
sales order:

```bash
export WECLAPP_TEST_SALESORDER_ID="existing-sales-order-id"
```

The structured 404 contracts require a valid numeric article id that is known
not to exist in the selected tenant:

```bash
export WECLAPP_TEST_MISSING_ARTICLE_ID="999999999"
```

Live tests skip only when such an explicit tenant fixture—or suitable sample
data such as a referenced unit or writable custom attribute—is absent. API,
projection, authentication, and schema errors fail the run.

## Persistent-write integration test

The create/update/delete lifecycle is marked `write`, requires a customer in an
isolated test tenant, and is disabled unless explicitly enabled:

```bash
export WECLAPP_TEST_CUSTOMER_ID="test-customer-id"
WECLAPP_RUN_WRITE_TESTS=1 \
  .venv/bin/pytest -m "integration and write" -v
```

The test creates a uniquely named sales order and deletes it in a `finally`
block. Do not enable it against a production tenant. If the process itself is
terminated before cleanup, search for orders whose number starts with `TEST-`
and remove the test record manually.

The custom-attribute roundtrip is not a persistent write: it projects
`id,version,customAttributes`, selects an active definition with
`readOnly=false`, and sends only a `dryRun` PUT. The credential still needs
permission to update that attribute for the contract to pass.

## Standalone live contract report

For a quick dependency-free probe outside pytest, export the API v2 credentials
above and run:

```bash
WECLAPP_RUN_LIVE_CONTRACT=1 \
  .venv/bin/python examples/live_contract.py
```

The probe performs reads only. It samples articles with `pageSize=1` and
`sort=id`, compares sequential and threaded pagination, verifies the
index-aligned `currentSalesPrice` additional property, and checks both the
API-native unit reference list and the normalized id-keyed client view. It
prints a JSON report and exits non-zero when a contract fails. Set
`WECLAPP_LIVE_CONTRACT_LIMIT` to change the default sample size of three.

The same probe can run as a small stdlib-only webhook service:

```bash
export WECLAPP_LIVE_CONTRACT_BEARER_TOKEN='replace-with-a-high-entropy-token'

WECLAPP_RUN_LIVE_CONTRACT=1 \
  .venv/bin/python examples/live_contract.py --serve

curl http://127.0.0.1:8765/health
curl -X POST \
  -H "Authorization: Bearer $WECLAPP_LIVE_CONTRACT_BEARER_TOKEN" \
  http://127.0.0.1:8765/run
```

`GET /health` checks only the process, while `POST /run` executes the contract.
Server mode always requires a separate high-entropy token in
`WECLAPP_LIVE_CONTRACT_BEARER_TOKEN`; `/run` requires it as an
`Authorization: Bearer ...` header even on loopback. Never reuse
`WECLAPP_API_KEY` for webhook authentication. Reports and server logs do not
expose either credential.
The stdlib server does not provide TLS, so use a TLS-enabled reverse proxy
before exposing it across an untrusted network.

## Test layout

Offline tests (no credentials, transport mocked):

- `test_weclappy_unit.py`: request construction, response parsing, upload and
  download, request logging, `WeclappAPIError` fields and the `WeclappEntity`
  model.
- `test_safety_regressions.py`: the safety contract in one auditable place:
  URL confinement, redirects, retry boundaries for reads and writes, 429
  budget and `Retry-After` cap, pagination order and limits, entity payload
  conversion.
- `test_response_shape_contracts.py`, `test_additional_referenced.py`:
  `additionalProperties` alignment and `referencedEntities` merging across
  pages, duplicate-id detection.
- `test_custom_attribute_contracts.py`, `test_definition_lookup.py`: custom
  attribute flattening, write payloads and the lazy
  `customAttributeDefinition` cache.
- `test_concurrency.py`, `test_retry.py`, `test_errors.py`, `test_metrics.py`
  and further `test_client_*.py` / `test_e2e_*.py` modules cover the
  concurrency controller, retry policy, error hierarchy and statistics in
  depth; `fakeserver.py` provides a local fake weclapp server for them.
- `test_live_contract_example.py`: offline checks of
  `examples/live_contract.py`.

Live tests:

- `test_weclappy_integration.py` contacts a live tenant and is marked
  `integration` at module level; it skips without credentials.
- Tests marked `write` may persist data and require
  `WECLAPP_RUN_WRITE_TESTS=1`.

Shared fixtures in `conftest.py`:

- `make_response(status, body, headers, *, content, content_type, url)` builds
  a real `requests.Response` without network I/O; `make_problem(status,
  suffix)` builds a weclapp problem document.
- `fake_transport(api, *replies, handler=None)` replaces
  `api.session.request` with a recording `MagicMock`. Replies are served in
  order (a `Response`, an exception to raise, or any JSON body); `handler`
  receives `(method, url, **kwargs)` instead.
- `make_client(base_url=..., api_key=..., **kwargs)` builds a `Weclapp` whose
  concurrency controller uses a fast fake clock, so 429 cooldowns never block.
  Patch `weclappy.client.time.sleep` for retry back-off.

Small, focused regression tests are welcome. A bug fix is easiest to review
when the test demonstrates the previous failure and does not require external
credentials. A known library defect may be pinned with
`@pytest.mark.xfail(strict=True, reason=...)` until it is fixed.
