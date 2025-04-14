# Building and Publishing weclappy to PyPI

This guide explains how to build the weclappy package and publish it to the Python Package Index (PyPI).

## Prerequisites

Before you begin, make sure you have the following:

1. A PyPI account (register at [https://pypi.org/account/register/](https://pypi.org/account/register/))
2. The latest version of pip, setuptools, wheel, and twine:

```bash
pip install --upgrade pip setuptools wheel twine
```

## Updating Package Version

1. Before building a new release, update the version number in `pyproject.toml`:

```toml
[project]
name = "weclappy"
version = "0.2.1"  # Update this version number
```

Follow [Semantic Versioning](https://semver.org/) principles:
- MAJOR version for incompatible API changes
- MINOR version for added functionality in a backward compatible manner
- PATCH version for backward compatible bug fixes

## Building the Package

1. Clean up any previous builds:

```bash
rm -rf build/ dist/ *.egg-info/
```

2. Build the package:

```bash
python -m build
```

This will create both source distribution (`.tar.gz`) and wheel (`.whl`) files in the `dist/` directory.

## Testing the Package Locally (Optional)

It’s a good idea to validate the distribution metadata before uploading:
```bash
pip install dist/weclappy-*.whl
```

Run some basic tests to ensure the package works correctly:

```bash
twine check dist/*
```

## Uploading to TestPyPI (Recommended)

TestPyPI is a separate instance of the Python Package Index that allows you to test your package without affecting the real index:

1. Upload to TestPyPI:

```bash
twine upload dist/*
```

2. Install from TestPyPI to verify:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ weclappy
```

## Uploading to PyPI

Once you've verified everything works correctly, upload to the real PyPI:

```bash
python -m twine upload dist/*
```

You'll be prompted for your PyPI username and password.

## Verifying the Upload

After uploading, verify that your package is available on PyPI:

1. Check the PyPI page: [https://pypi.org/project/weclappy/](https://pypi.org/project/weclappy/)
2. Install the package from PyPI:

```bash
pip install --upgrade weclappy
```

## Release Checklist

Before each release, ensure:

- [ ] All tests pass
- [ ] Documentation is up-to-date
- [ ] Version number is updated in `pyproject.toml`
- [ ] CHANGELOG.md is updated (if you maintain one)
- [ ] README.md reflects any new features or changes

## Troubleshooting

### Common Issues

1. **Authentication Errors**: Make sure your PyPI credentials are correct. Consider using a `.pypirc` file or environment variables for authentication.

2. **Version Conflicts**: If you get an error that the version already exists, you need to increment the version number. You cannot overwrite an existing version on PyPI.

3. **Missing Dependencies**: If your package has dependencies that aren't properly specified in `pyproject.toml`, users may encounter errors when installing your package.

### Setting Up a .pypirc File

To avoid entering your credentials each time, create a `.pypirc` file in your home directory:

```
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = your_username
password = your_password

[testpypi]
repository = https://test.pypi.org/legacy/
username = your_username
password = your_password
```

Make sure to set appropriate permissions:

```bash
chmod 600 ~/.pypirc
```

## Automating Releases with GitHub Actions (Optional)

You can automate the release process using GitHub Actions. Create a workflow file at `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [created]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.x'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install build twine
    - name: Build and publish
      env:
        TWINE_USERNAME: ${{ secrets.PYPI_USERNAME }}
        TWINE_PASSWORD: ${{ secrets.PYPI_PASSWORD }}
      run: |
        python -m build
        twine upload dist/*
```

With this setup, creating a new release on GitHub will automatically build and publish your package to PyPI.
