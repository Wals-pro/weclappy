import os
import sys

import pytest

# Add the project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Require an explicit opt-in before any persistent-write test can run."""
    if (
        item.get_closest_marker("write") is not None
        and os.environ.get("WECLAPP_RUN_WRITE_TESTS") != "1"
    ):
        pytest.skip("set WECLAPP_RUN_WRITE_TESTS=1 to run persistent-write tests")
