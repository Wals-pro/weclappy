"""Shared pytest configuration and offline transport helpers.

The package is installed in editable mode (``pip install -e ".[dev]"``), so
tests import ``weclappy`` directly without touching ``sys.path``.
"""

from __future__ import annotations

import itertools
import json
import os
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from weclappy import ConcurrencyController, ConcurrencySettings, Weclapp

BASE_URL = "https://tenant.weclapp.com/webapp/api/v2"
API_ROOT = f"{BASE_URL}/"


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Require an explicit opt-in before any persistent-write test can run."""
    if (
        item.get_closest_marker("write") is not None
        and os.environ.get("WECLAPP_RUN_WRITE_TESTS") != "1"
    ):
        pytest.skip("set WECLAPP_RUN_WRITE_TESTS=1 to run persistent-write tests")


def build_response(
    status: int = 200,
    body: Any = None,
    headers: dict[str, str] | None = None,
    *,
    content: bytes | None = None,
    content_type: str | None = "application/json",
    url: str = f"{API_ROOT}article",
) -> requests.Response:
    """Build a real :class:`requests.Response` without network I/O.

    ``body`` is JSON-encoded unless raw ``content`` is given.
    """
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.reason = "Test Response"
    if content is None:
        content = b"" if body is None else json.dumps(body).encode("utf-8")
    response._content = content
    if content_type:
        response.headers["Content-Type"] = content_type
    if headers:
        response.headers.update(headers)
    return response


def build_problem(
    status: int, suffix: str, headers: dict[str, str] | None = None
) -> requests.Response:
    """A weclapp problem document response (``application/problem+json``)."""
    return build_response(
        status,
        {
            "type": f"/webapp/view/api/errors.html#!/errors/{suffix}",
            "title": suffix.replace("_", " ").title(),
            "status": status,
        },
        headers,
        content_type="application/problem+json",
    )


def fast_clock() -> Callable[[], float]:
    """A monotonic clock that jumps 1000 s per reading.

    Any 429 cooldown has expired by the next reading, so tests never block in
    ``Condition.wait``. Use it only where no read waits for a free slot.
    """
    return itertools.count(start=1000.0, step=1000.0).__next__


def build_client(base_url: str = BASE_URL, api_key: str = "secret-token", **kwargs: Any) -> Weclapp:
    """A client whose concurrency controller never waits out a real cooldown."""
    if "concurrency" not in kwargs:
        settings = ConcurrencySettings(max_concurrency=kwargs.pop("max_concurrency", 10))
        kwargs["concurrency"] = ConcurrencyController(settings, clock=fast_clock())
    return Weclapp(base_url, api_key, **kwargs)


def _as_response(reply: Any) -> requests.Response:
    if isinstance(reply, BaseException):
        raise reply
    if isinstance(reply, requests.Response):
        return reply
    return build_response(body=reply)


def install_transport(api: Weclapp, *replies: Any, handler: Any = None) -> MagicMock:
    """Replace ``api.session.request`` with a recording fake.

    Pass either ``replies`` (served in order) or ``handler(method, url, **kwargs)``.
    A reply may be a :class:`requests.Response`, an exception instance (raised)
    or any other value, which becomes a 200 JSON response body.
    """
    if handler is not None:
        mock = MagicMock(
            side_effect=lambda method, url, **kwargs: _as_response(handler(method, url, **kwargs))
        )
    else:
        queue = iter(replies)
        mock = MagicMock(side_effect=lambda method, url, **kwargs: _as_response(next(queue)))
    api.session.request = mock  # type: ignore[method-assign]
    return mock


@pytest.fixture
def make_response() -> Callable[..., requests.Response]:
    """Factory: ``make_response(status, body, headers, *, content, content_type, url)``."""
    return build_response


@pytest.fixture
def make_problem() -> Callable[..., requests.Response]:
    """Factory: ``make_problem(status, suffix, headers)``."""
    return build_problem


@pytest.fixture
def make_client() -> Callable[..., Weclapp]:
    """Factory for offline clients; see :func:`build_client`."""
    return build_client


@pytest.fixture
def fake_transport() -> Callable[..., MagicMock]:
    """Installs a fake ``session.request``; see :func:`install_transport`."""
    return install_transport
