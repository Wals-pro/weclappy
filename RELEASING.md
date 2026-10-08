# Releasing weclappy

Maintainer guide. Releases are published from a GitHub Release by the
`Publish to PyPI` workflow (`.github/workflows/publish.yml`) through PyPI
Trusted Publishing. No PyPI token or repository secret exists or is needed.

## One-time setup

Trusted Publisher on PyPI for the project `weclappy`:

- Owner: `Wals-pro`
- Repository: `weclappy`
- Workflow: `publish.yml`
- Environment: `pypi`

Create the matching `pypi` environment in the GitHub repository settings and
add required reviewers, so every upload needs an explicit approval.

## Workflows

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `test.yml` | push to `main`, pull requests, manual | Python 3.12/3.13/3.14: `ruff check`, `ruff format --check`, `mypy`, `pytest -m "not integration"` with coverage ≥ 90 %. Package job: build, `twine check --strict`, wheel content assertions, install the wheel in a clean venv and import it. |
| `publish.yml` | GitHub Release published | `validate`: release tag equals `v` + `pyproject.toml` version, `CHANGELOG.md` has a dated `## [X.Y.Z] - YYYY-MM-DD` heading, tests, build, `twine check`, wheel smoke test, upload of `dist/` as an artifact. `publish`: downloads exactly that artifact and uploads it with `id-token: write` in the `pypi` environment. |

All actions are pinned to commit SHAs; Dependabot (`.github/dependabot.yml`)
proposes updates weekly.

## Release checklist (example: 1.0.0)

1. **Version.** `pyproject.toml` `version = "1.0.0"`. `weclappy.__version__`
   is read from the installed metadata; there is no second place to edit.
2. **Changelog gate.** Move the entries from `## Unreleased` into
   `## [1.0.0] - YYYY-MM-DD` with the actual release date. The publish
   workflow fails without this exact heading.
3. **Local verification** from a clean checkout:

   ```bash
   rm -rf dist build
   uv venv --python 3.12 && source .venv/bin/activate
   uv pip install -e ".[dev]"
   ruff check src tests examples
   ruff format --check src tests examples
   mypy
   pytest -m "not integration" --cov=weclappy --cov-fail-under=90
   python -m build
   python -m twine check --strict dist/*
   unzip -l dist/weclappy-1.0.0-py3-none-any.whl   # weclappy/__init__.py, py.typed, LICENSE
   ```

4. **Live check (optional, sandbox only).** Run the read-only probe against
   the sandbox tenant, never against a production tenant:

   ```bash
   WECLAPP_RUN_LIVE_CONTRACT=1 python examples/live_contract.py
   ```

5. **Merge.** Open the release pull request, wait for green CI on all Python
   versions, merge to `main`.
6. **Release candidate (major releases).** For a new major version publish
   `1.0.0rc1` first (version `1.0.0rc1`, tag `v1.0.0rc1`, changelog heading
   `## [1.0.0rc1] - YYYY-MM-DD`) and run it in the core consumers before the
   final release.
7. **Tag and release.** Create a GitHub Release from the merge commit with the
   new tag `v1.0.0`, title `v1.0.0`, and the changelog section as release
   notes. Publishing the release starts `publish.yml`.
8. **Approve** the `pypi` environment deployment when the `validate` job is
   green.
9. **Verify:**
   - `https://pypi.org/project/weclappy/1.0.0/` shows the expected metadata
     and README;
   - `python -m pip install weclappy==1.0.0` works in a fresh environment;
   - `python -c "import weclappy; print(weclappy.__version__)"` prints
     `1.0.0`.

PyPI versions are immutable. If an artifact is wrong, fix it and publish a new
patch version; never try to replace a file.

## Consumer pin checklist

Update and test the known consumers after every minor or major release.
Each change goes through the consumer's own pull request and CI.

| Consumer | Pin before 1.0 | Target | Check before bumping |
| --- | --- | --- | --- |
| `weclapp-mcp` | `==0.6.0` | `weclappy>=1.0,<2` | Replace `_send_request(...)` with `client.request(...)`; replace the session swap with `Weclapp(session=...)` and `before_request`/`on_response`; keep `threaded=False` where the tenant circuit breaker and the `context.call` timeout must apply; Python ≥ 3.12 in the image. |
| `walspro.tradehub` | pyproject `>=0.6.0,<0.7`; deployed `functions/requirements.txt` `==0.4.1` | `weclappy>=1.0,<2` in both files | Align the deployed pin with the codebase; remove the own `RetryingWeclappClient` retry layer for writes (weclappy no longer retries writes, and stacking retries multiplies load); test the cursor scan with `sort=lastModifiedDate` + `limit` under `threaded="auto"`. |
| `walspro.weclapp.n8n-cicd` | `>=0.1.0` | `weclappy~=1.0` | Find absolute base URLs passed as `endpoint` and make them relative; replace `WeclappEntity._unwrap` with `unwrap()`/`to_payload()`; `max_workers` > 10 needs `Weclapp(max_concurrency=...)`; replace direct `session.get/post` with `request()`. |
| `walspro.multicarrier` (4Fulfillment) | `~=0.3.1` | `weclappy>=1.0,<2` | Replace `session.request` + `_check_response` + `_send_request` with `request()`; keep `sort=-lastModifiedDate` explicit (the `sort=id` default only applies when no sort is given). |

Also check unpinned or loosely pinned users (Docker images that install
`weclappy` without a version) and pin them to `>=1.0,<2` before they rebuild.
