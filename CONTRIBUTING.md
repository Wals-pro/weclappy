# Contributing to weclappy

Thank you for considering a contribution. Bug fixes, clearer examples, careful
API improvements and reports from real integrations all help.

weclappy is intentionally a small, generic client. If an idea adds a runtime
dependency, changes public behaviour, or introduces module-specific business
logic, please open an issue first so the shape of the change can be agreed
before much work is invested. Since 1.0 the public API follows Semantic
Versioning; see the [versioning and support policy](README.md#versioning-and-support-policy).

## Reporting an issue

For a bug, please include:

- the weclappy version (`python -c "import weclappy; print(weclappy.__version__)"`)
  and the Python version;
- the public method and weclapp endpoint involved;
- expected and actual behaviour;
- a small reproducible example when possible; and
- a sanitised traceback, the status code, and `RequestMetrics` or
  `client.stats` output if load management is involved.

Remove API keys, tenant names, customer data and document contents. Security
vulnerabilities must not be filed publicly; follow [SECURITY.md](SECURITY.md).

## Development setup

```bash
git clone https://github.com/Wals-pro/weclappy.git
cd weclappy
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"        # or: python -m pip install -e ".[dev]"
```

The `dev` extra installs pytest, pytest-cov, mypy, ruff, types-requests, build
and twine.

## Checks

CI runs exactly these commands on Python 3.12, 3.13 and 3.14. Run them before
opening a pull request:

```bash
ruff check src tests examples
ruff format --check src tests examples
mypy
pytest -m "not integration" --cov=weclappy --cov-report=term-missing --cov-fail-under=90
python -m compileall -q examples
```

## Code style

- Formatting and linting: `ruff` (line length 100, rules configured in
  `pyproject.toml`). Use `ruff format` instead of hand-formatting.
- Typing: `mypy --strict` over the package must stay clean. Public functions
  have complete annotations; avoid `Any` where a precise type is practical.
- Python ≥ 3.12 syntax (`X | None`, `type` aliases, `match`) is fine.
- Prefer the standard library. A new runtime dependency needs an issue first.
- Keep endpoint-specific business rules out of the client.
- Never log or store the API key, query strings or request bodies.
- Writes must never be retried unless the request provably never left the
  process. Any change near `retry.py` needs a test that counts requests per
  method.

## Tests

| Marker | Meaning | Runs in CI |
| --- | --- | --- |
| *(none)* | Offline tests with mocked transports and an injected fake clock | yes |
| `integration` | Needs a live weclapp tenant (`WECLAPP_BASE_URL`, `WECLAPP_API_KEY`) | no |
| `write` | Creates, updates or deletes data; additionally requires explicit opt-in | no |

Markers are strict (`--strict-markers`). Integration tests run only against a
sandbox or test tenant, never against production data. Do not enable write
tests without reading them first.

Tests must not sleep in real time: inject a clock into
`ConcurrencyController(clock=...)` and patch `time.sleep` for retry delays.
Coverage must stay at or above 90 %.

## Making a change

- Add or update tests for every behaviour change and its error paths.
- Use only public `weclappy` names in documentation and examples.
- Update `README.md` when users need to learn something new.
- Add user-visible changes under `## Unreleased` in `CHANGELOG.md`; mark
  breaking changes as such.
- Deprecate before removing: emit a `DeprecationWarning` for at least one minor
  release.

## Pull requests

Focused pull requests are easier to review. Describe what changed, why, and
how it was verified. Before opening one, check that:

- all checks above pass locally;
- no credentials or tenant data are included;
- new failure paths raise a typed `WeclappError` subclass;
- write and retry implications were considered;
- documentation and changelog are current; and
- unrelated refactors are left for a separate change.

Please be respectful, patient and constructive in issues and reviews.
