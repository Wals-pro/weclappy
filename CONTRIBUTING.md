# Contributing to weclappy

Thank you for considering a contribution. Small bug fixes, clearer examples,
careful API improvements, and reports from real integrations all help.

`weclappy` is intentionally a small, generic client. If a larger idea may add
a dependency, change public behavior, or introduce module-specific business
logic, please open an issue first. That gives everyone a chance to agree on the
shape of the change before much work is invested.

## Reporting an issue

For a bug, please include:

- the `weclappy` and Python versions;
- the public method and weclapp endpoint involved;
- the expected and actual behavior;
- a small reproducible example when possible; and
- a sanitized traceback or response status.

Remove API keys, tenant names, customer data, document contents, and other
sensitive information. Security vulnerabilities should not be filed publicly;
use the process in [SECURITY.md](SECURITY.md).

For a feature request, it helps to describe the integration problem rather
than only a proposed implementation. Generic capabilities that apply across
weclapp modules are the best fit for this library.

## Development setup

```bash
git clone https://github.com/Wals-pro/weclappy.git
cd weclappy
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install pytest
```

Run every self-contained test; these do not require a tenant or credentials:

```bash
python -m pytest -m "not integration" -v
```

Integration tests require real credentials and may exercise tenant data. Do
not run write tests unless you have inspected them, selected an appropriate
test tenant, and explicitly enabled them.

## Making a change

- Keep the public API request-like and straightforward.
- Preserve compatibility with Python 3.9 and newer.
- Prefer the standard library; discuss any new runtime dependency first.
- Keep endpoint-specific business rules outside the client.
- Use only public `weclappy` methods in documentation and examples.
- Add or update mocked tests for behavior changes and edge cases.
- Update `README.md` when users need to learn something new.
- Add user-visible changes under `## Unreleased` in `CHANGELOG.md`.

The repository does not require a large formatting toolchain. Follow the style
of the surrounding code and keep names and type hints clear.

## Pull requests

Focused pull requests are easier to review and release. A useful description
explains what changed, why it is needed, and how it was verified. Before opening
the pull request, please check that:

- unit tests pass locally;
- no credentials or tenant data are included;
- new failure paths raise a clear, structured error;
- write behavior and retry implications were considered;
- documentation and changelog entries are current; and
- unrelated refactors are left for a separate change.

Maintainers may suggest a smaller or more generic approach to protect the
library's simple scope. That discussion is part of collaboration, and
alternative ideas are welcome.

Please be respectful, patient, and constructive in issues and reviews. People
contribute with different levels of familiarity and available time.
