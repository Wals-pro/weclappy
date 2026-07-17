# Releasing weclappy to PyPI

This is a maintainer guide. Publishing is automated from a GitHub Release with
PyPI Trusted Publishing. The release workflow is the source of truth for its
short-lived OpenID Connect credentials and build steps.

## One-time publisher setup

Configure a Trusted Publisher for the `weclappy` project in PyPI:

- GitHub organization or user: `Wals-pro`
- Repository: `weclappy`
- Workflow: `publish.yml`
- Environment: `pypi`

Create the matching `pypi` environment in the GitHub repository. Protected
environment reviewers are optional but useful for release approval. No PyPI
token or repository secret is required.

## Prepare the release

1. Choose a version according to [Semantic Versioning](https://semver.org/).
2. Update `version` in `pyproject.toml`.
3. Move the relevant `CHANGELOG.md` entries from `Unreleased` to a versioned
   heading with the release date.
4. Verify the full release candidate locally:

   ```bash
   python -m pytest -m "not integration" -v
   python -m pip install --upgrade build twine
   python -m build
   python -m twine check --strict dist/*
   ```

5. Inspect the wheel and source archive. Confirm that package metadata,
   `README.md`, `LICENSE`, and the intended module are present.
6. Commit the release changes, open or merge the release pull request, and make
   sure CI is green on every supported Python version.

Use a clean checkout or remove stale build artifacts before the local build so
an older distribution is not mistaken for the release candidate.

## Publish through GitHub

1. Create a GitHub Release from the release commit.
2. Create the tag `vX.Y.Z`; it must match the version in `pyproject.toml`.
3. Use `vX.Y.Z` as the release title.
4. Copy the matching changelog section into the release notes.
5. Publish the release.

The `Publish to PyPI` workflow first requires the release tag to equal `v` plus
the package version and a dated `## [X.Y.Z] - YYYY-MM-DD` section to exist in
`CHANGELOG.md`. It then runs every non-integration test, builds the
distributions, validates their metadata, installs the wheel in a clean virtual
environment, and publishes those exact artifacts through Trusted Publishing.

After publishing, verify:

- the GitHub workflow completed successfully;
- `https://pypi.org/project/weclappy/X.Y.Z/` shows the expected metadata;
- `python -m pip install weclappy==X.Y.Z` works in a fresh environment; and
- importing `Weclapp`, `WeclappAPIError`, and `WeclappEntity` succeeds.

PyPI versions are immutable. If the uploaded artifact is wrong, fix the issue
and publish a new patch version rather than trying to replace it.
