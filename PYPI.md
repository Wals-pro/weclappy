# Publishing weclappy to PyPI

This guide explains how to publish weclappy to the Python Package Index (PyPI).

## Automated Publishing (Recommended)

Releases are automatically published to PyPI via GitHub Actions when you create a new release on GitHub.

### Setup (One-time)

1. Create a PyPI API token at [https://pypi.org/manage/account/token/](https://pypi.org/manage/account/token/)
   - Scope: Project `weclappy`
   
2. Add the token to GitHub repository secrets:
   - Go to: Repository → Settings → Secrets and variables → Actions
   - Create secret: `PYPI_API_TOKEN`
   - Paste your PyPI token

### Release Process

1. **Update version** in `pyproject.toml`:
   ```toml
   version = "0.3.1"  # Increment appropriately
   ```

2. **Update CHANGELOG.md**:
   - Move items from `## Unreleased` to a new version section
   - Add the release date

3. **Commit and push**:
   ```bash
   git add -A
   git commit -m "Release v0.3.1"
   git push origin main
   ```

4. **Create GitHub Release**:
   - Go to: Repository → Releases → "Create a new release"
   - Tag: `v0.3.1` (create new tag)
   - Title: `v0.3.1`
   - Description: Copy from CHANGELOG.md
   - Click "Publish release"

5. **Verify**:
   - Check Actions tab for workflow status
   - Verify at [https://pypi.org/project/weclappy/](https://pypi.org/project/weclappy/)

## Manual Publishing (Fallback)

If you need to publish manually:

```bash
# Clean and build
rm -rf build/ dist/ *.egg-info/
python -m build

# Check distribution
twine check dist/*

# Upload (will prompt for token)
twine upload dist/*
# Username: __token__
# Password: <your PyPI API token>
```

## Version Guidelines

Follow [Semantic Versioning](https://semver.org/):
- **MAJOR** (1.0.0): Breaking API changes
- **MINOR** (0.3.0): New features, backward compatible
- **PATCH** (0.3.1): Bug fixes, backward compatible

## Troubleshooting

### Version Already Exists
PyPI doesn't allow overwriting versions. Increment the version number and try again.

### Authentication Failed
Ensure your `PYPI_API_TOKEN` secret is set correctly in GitHub repository settings.

### Build Failed
Run tests locally first:
```bash
python -m pytest tests/test_weclappy_unit.py -v
```
