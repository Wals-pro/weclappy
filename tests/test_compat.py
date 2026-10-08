"""Backwards-compatibility shims kept for the 1.x line."""

import logging

import pytest

from weclappy import Weclapp, WeclappAPIError, WeclappConcurrencyTimeoutError


@pytest.mark.parametrize(
    ("method", "kwargs", "expected_path"),
    [
        ("get", {}, "/webapp/api/v2/article"),
        ("put", {"data": {"name": "x"}}, "/webapp/api/v2/article/id/7"),
        ("delete", {}, "/webapp/api/v2/article/id/7"),
        ("download", {}, "/webapp/api/v2/article/id/7/download"),
        ("upload", {"data": b"x", "action": "upload"}, "/webapp/api/v2/article/id/7/upload"),
    ],
)
def test_legacy_id_keyword_warns_and_maps_to_entity_id(
    make_client, fake_transport, make_response, method, kwargs, expected_path
):
    api = make_client()
    transport = fake_transport(api, make_response(200, {"result": [{"id": "7"}]}))
    with pytest.warns(DeprecationWarning, match="entity_id"):
        getattr(api, method)("article", id="7", **kwargs)
    _, url = transport.call_args.args[:2]
    assert url.endswith(expected_path)
    if method == "get":
        assert transport.call_args.kwargs["params"]["id-eq"] == "7"


def test_legacy_id_and_entity_id_together_is_an_error(make_client):
    api = make_client()
    with pytest.raises(TypeError, match="both"):
        api.get("article", "1", id="2")


def test_put_and_delete_require_an_entity_id(make_client):
    api = make_client()
    with pytest.raises(TypeError, match="entity_id"):
        api.put("article", data={"name": "x"})
    with pytest.raises(TypeError, match="data"):
        api.put("article", "1")
    with pytest.raises(TypeError, match="entity_id"):
        api.delete("article")


def test_max_workers_above_ceiling_is_clamped_with_a_warning(make_client, caplog):
    api = make_client(max_concurrency=4)
    with caplog.at_level(logging.WARNING, logger="weclappy"):
        assert api._resolve_workers(20) == 4
    assert "max_workers=20 exceeds max_concurrency=4" in caplog.text


def test_concurrency_timeout_is_an_api_error():
    assert issubclass(WeclappConcurrencyTimeoutError, WeclappAPIError)
    assert WeclappConcurrencyTimeoutError("slot").status_code is None


def test_for_tenant_accepts_a_full_host():
    api = Weclapp.for_tenant("erp.example.com", "key")
    assert api.base_url == "https://erp.example.com/webapp/api/v2/"
