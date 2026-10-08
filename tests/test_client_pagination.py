"""get_all / get_by_ids / iter_all / iter_keyset against a socket-free fake tenant."""

from __future__ import annotations

import json
import threading
from typing import Any

import pytest
import requests

from fakeserver import FakeSession, FakeTenant, Hit, Interceptor, Outcome, Reply, make_rows
from weclappy import Weclapp, WeclappEntity, WeclappPaginationError, WeclappResponse

BASE = "https://acme.weclapp.com/webapp/api/v2/"


def make_client(
    tenant: FakeTenant, interceptor: Interceptor | None = None, *, max_concurrency: int = 10
) -> Weclapp:
    client = Weclapp(BASE, "k", max_concurrency=max_concurrency)
    client.session.request = FakeSession(tenant, interceptor)  # type: ignore[method-assign]
    return client


def tenant_with(count: int) -> FakeTenant:
    return FakeTenant({"article": make_rows(count)})


def list_hits(tenant: FakeTenant) -> list[Hit]:
    return tenant.hits_for("GET", "article")


def pages(tenant: FakeTenant) -> list[int]:
    return [int(hit.query["page"]) for hit in list_hits(tenant) if "page" in hit.query]


def ids(rows: Any) -> list[str]:
    return [row["id"] for row in rows]


def expected_ids(count: int, start: int = 1) -> list[str]:
    return [str(i) for i in range(start, start + count)]


# --------------------------------------------------------------- auto mode
def test_short_first_page_skips_the_count() -> None:
    tenant = tenant_with(3)
    result = make_client(tenant).get_all("article", {"pageSize": 5})
    assert ids(result) == expected_ids(3)
    assert all(isinstance(row, WeclappEntity) for row in result)
    assert pages(tenant) == [1]
    assert tenant.hits_for("GET", "article/count") == []


def test_full_first_page_counts_then_fetches_the_rest_in_order() -> None:
    tenant = tenant_with(23)
    result = make_client(tenant).get_all("article", {"pageSize": 5, "version-eq": "0"})
    assert ids(result) == expected_ids(23)
    assert sorted(pages(tenant)) == [1, 2, 3, 4, 5]
    assert pages(tenant)[0] == 1
    (count_hit,) = tenant.hits_for("GET", "article/count")
    assert count_hit.query == {"version-eq": "0"}


def test_threaded_true_is_an_alias_of_auto() -> None:
    tenant = tenant_with(12)
    result = make_client(tenant).get_all("article", {"pageSize": 5}, threaded=True)
    assert ids(result) == expected_ids(12)
    assert len(tenant.hits_for("GET", "article/count")) == 1


def test_page_order_is_restored_when_later_pages_finish_first() -> None:
    tenant = tenant_with(5)
    page3_done = threading.Event()
    completed: list[int] = []

    def interceptor(method: str, path: str, query: dict[str, str], body: Any) -> Outcome | None:
        if path != "article":
            return None
        page = query.get("page")
        if page == "2":
            assert page3_done.wait(timeout=2), "page 3 never ran concurrently"
        outcome = tenant.dispatch(method, path, query, body)
        completed.append(int(page or 0))
        if page == "3":
            page3_done.set()
        return outcome

    result = make_client(tenant, interceptor).get_all("article", {"pageSize": 2})
    assert completed == [1, 3, 2]
    assert ids(result) == expected_ids(5)


def test_shortfall_against_the_count_raises() -> None:
    tenant = tenant_with(10)

    def interceptor(method: str, path: str, query: dict[str, str], body: Any) -> Outcome | None:
        return Reply(200, {"result": 14}) if path == "article/count" else None

    with pytest.raises(WeclappPaginationError, match="10 of 14"):
        make_client(tenant, interceptor).get_all("article", {"pageSize": 5})


def test_duplicate_ids_between_pages_raise() -> None:
    tenant = tenant_with(10)

    def interceptor(method: str, path: str, query: dict[str, str], body: Any) -> Outcome | None:
        if path == "article" and query.get("page") == "2":
            return Reply(200, {"result": make_rows(5, start=5)})
        return None

    with pytest.raises(WeclappPaginationError, match="duplicate entity id '5'"):
        make_client(tenant, interceptor).get_all("article", {"pageSize": 5})


def test_more_rows_than_counted_are_kept() -> None:
    """Rows inserted after the count are not an error; only a shortfall is."""
    tenant = tenant_with(10)

    def interceptor(method: str, path: str, query: dict[str, str], body: Any) -> Outcome | None:
        return Reply(200, {"result": 9}) if path == "article/count" else None

    result = make_client(tenant, interceptor).get_all("article", {"pageSize": 5})
    assert ids(result) == expected_ids(10)


# ---------------------------------------------------------------- limit
def test_limit_below_page_size_needs_one_request() -> None:
    tenant = tenant_with(50)
    result = make_client(tenant).get_all("article", limit=3)
    assert ids(result) == expected_ids(3)
    (hit,) = list_hits(tenant)
    assert hit.query["pageSize"] == "3"
    assert tenant.hits_for("GET", "article/count") == []


def test_limit_slices_rows_additional_properties_and_merges_references() -> None:
    tenant = tenant_with(10)
    response = make_client(tenant).get_all(
        "article",
        {"pageSize": 2, "additionalProperties": "extra", "includeReferencedEntities": "customerId"},
        limit=5,
        return_weclapp_response=True,
    )
    assert isinstance(response, WeclappResponse)
    assert ids(response.result) == expected_ids(5)
    assert response.additional_properties == {"extra": [f"extra:{i}" for i in range(1, 6)]}
    assert [row["extra"] for row in response.result] == [f"extra:{i}" for i in range(1, 6)]  # type: ignore[index, union-attr]
    assert response.referenced_entities is not None
    assert set(response.referenced_entities["party"]) == {"c0", "c1", "c2", "c3", "c4"}
    assert sorted(pages(tenant)) == [1, 2, 3]


def test_additional_properties_stay_in_lockstep_when_a_page_lacks_them() -> None:
    tenant = tenant_with(4)

    def interceptor(method: str, path: str, query: dict[str, str], body: Any) -> Outcome | None:
        if path == "article" and query.get("page") == "1":
            return Reply(200, {"result": make_rows(2)})  # no additionalProperties
        return None

    response = make_client(tenant, interceptor).get_all(
        "article", {"pageSize": 2, "additionalProperties": "extra"}, return_weclapp_response=True
    )
    assert response.additional_properties == {"extra": [None, None, "extra:3", "extra:4"]}


def test_limit_zero_returns_empty_without_requests() -> None:
    tenant = tenant_with(3)
    client = make_client(tenant)
    assert client.get_all("article", limit=0) == []
    empty = client.get_all("article", limit=0, return_weclapp_response=True)
    assert isinstance(empty, WeclappResponse)
    assert empty.result == []
    assert tenant.hits == []


# ----------------------------------------------------------- max_records
def test_max_records_refuses_before_fetching_remaining_pages() -> None:
    tenant = tenant_with(10)
    with pytest.raises(WeclappPaginationError, match="max_records=5"):
        make_client(tenant).get_all("article", {"pageSize": 2}, max_records=5)
    assert pages(tenant) == [1]
    assert len(tenant.hits_for("GET", "article/count")) == 1


def test_max_records_on_a_short_first_page() -> None:
    tenant = tenant_with(4)
    with pytest.raises(WeclappPaginationError, match="max_records=3"):
        make_client(tenant).get_all("article", {"pageSize": 5}, max_records=3)


def test_max_records_equal_to_total_is_allowed() -> None:
    tenant = tenant_with(6)
    assert len(make_client(tenant).get_all("article", {"pageSize": 2}, max_records=6)) == 6


def test_max_records_sequential_stops_on_the_exceeding_page() -> None:
    tenant = tenant_with(10)
    with pytest.raises(WeclappPaginationError, match="page 2"):
        make_client(tenant).get_all("article", {"pageSize": 2}, max_records=3, threaded=False)
    assert pages(tenant) == [1, 2]


# ------------------------------------------------------------- sequential
def test_threaded_false_reads_sequentially_without_count() -> None:
    tenant = tenant_with(7)
    result = make_client(tenant).get_all("article", {"pageSize": 3}, threaded=False)
    assert ids(result) == expected_ids(7)
    assert pages(tenant) == [1, 2, 3]
    assert tenant.hits_for("GET", "article/count") == []


def test_threaded_false_reads_one_empty_page_on_exact_multiples() -> None:
    tenant = tenant_with(4)
    make_client(tenant).get_all("article", {"pageSize": 2}, threaded=False)
    assert pages(tenant) == [1, 2, 3]


# ------------------------------------------------------------- validation
@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_workers": 4},
        {"max_workers": 0},
        {"max_workers": True},
        {"limit": -1},
        {"max_records": -1},
        {"limit": 1.5},
        {"threaded": "yes"},
        {"strategy": "cursor"},
    ],
)
def test_get_all_argument_validation(kwargs: dict[str, Any]) -> None:
    tenant = tenant_with(1)
    with pytest.raises(ValueError):  # noqa: PT011 - several distinct messages
        make_client(tenant, max_concurrency=3).get_all("article", **kwargs)
    assert tenant.hits == []


@pytest.mark.parametrize("page_size", [0, -1, "100", True])
def test_get_all_rejects_bad_page_size(page_size: Any) -> None:
    with pytest.raises(ValueError, match="pageSize"):
        make_client(tenant_with(1)).get_all("article", {"pageSize": page_size})


def test_max_workers_equal_to_the_ceiling_is_allowed() -> None:
    tenant = tenant_with(2)
    assert len(make_client(tenant, max_concurrency=3).get_all("article", max_workers=3)) == 2


# ------------------------------------------------------------------- sort
@pytest.mark.parametrize(
    ("params", "expected_sort"),
    [
        (None, "id"),
        ({"sort": None}, None),
        ({"orderBy": "name"}, None),
        ({"sort": "-id"}, "-id"),
    ],
)
def test_default_sort(params: dict[str, Any] | None, expected_sort: str | None) -> None:
    tenant = tenant_with(2)
    make_client(tenant).get_all("article", params)
    assert list_hits(tenant)[0].query.get("sort") == expected_sort
    assert params is None or "pageSize" not in params, "caller params must not be mutated"


# ---------------------------------------------------------- strategy="ids"
def test_strategy_ids_reads_ids_then_rows_in_chunks() -> None:
    tenant = tenant_with(7)
    result = make_client(tenant).get_all(
        "article", {"pageSize": 3, "properties": "id,name"}, strategy="ids"
    )
    assert ids(result) == expected_ids(7)
    assert result[0]["name"] == "Record 1"
    hits = list_hits(tenant)
    id_pages = [hit for hit in hits if "id-in" not in hit.query]
    chunks = [hit for hit in hits if "id-in" in hit.query]
    assert {hit.query["properties"] for hit in id_pages} == {"id"}
    assert {hit.query["sort"] for hit in id_pages} == {"id"}
    assert len(tenant.hits_for("GET", "article/count")) == 1
    (chunk,) = chunks
    assert json.loads(chunk.query["id-in"]) == expected_ids(7)
    assert chunk.query["pageSize"] == "7"
    assert chunk.query["properties"] == "id,name"
    assert "sort" not in chunk.query
    assert "page" not in chunk.query
    assert hits.index(chunk) > hits.index(id_pages[-1])


def test_strategy_ids_respects_limit() -> None:
    tenant = tenant_with(9)
    result = make_client(tenant).get_all("article", {"pageSize": 2}, strategy="ids", limit=3)
    assert ids(result) == expected_ids(3)


# -------------------------------------------------------------- get_by_ids
def test_get_by_ids_dedupes_and_keeps_input_order() -> None:
    tenant = tenant_with(5)
    result = make_client(tenant).get_by_ids("article", ["3", "1", "3", 5])  # type: ignore[list-item]
    assert ids(result) == ["3", "1", "5"]
    (hit,) = list_hits(tenant)
    assert json.loads(hit.query["id-in"]) == ["3", "1", "5"]
    assert hit.query["pageSize"] == "3"


def test_get_by_ids_missing_ids_are_absent() -> None:
    tenant = tenant_with(5)
    result = make_client(tenant).get_by_ids("article", ["5", "2", "99", "1"])
    assert ids(result) == ["5", "2", "1"]


def test_get_by_ids_chunks_by_count() -> None:
    tenant = tenant_with(5)
    result = make_client(tenant).get_by_ids("article", ["5", "4", "3", "2", "1"], chunk_size=2)
    assert ids(result) == ["5", "4", "3", "2", "1"]
    sizes = sorted(int(hit.query["pageSize"]) for hit in list_hits(tenant))
    assert sizes == [1, 2, 2]


def test_get_by_ids_chunks_by_url_length() -> None:
    wanted = expected_ids(100, start=1000)
    tenant = FakeTenant({"article": make_rows(100, start=1000)})
    result = make_client(tenant).get_by_ids(
        "article", wanted, {"properties": "id"}, max_url_length=300
    )
    assert ids(result) == wanted
    hits = list_hits(tenant)
    assert len(hits) > 1
    seen: list[str] = []
    for hit in hits:
        url = requests.Request("GET", BASE + "article", params=hit.query).prepare().url
        assert url is not None
        assert len(url) <= 300, url
        seen.extend(json.loads(hit.query["id-in"]))
    assert sorted(seen) == wanted


def test_get_by_ids_strips_pagination_and_sort() -> None:
    tenant = tenant_with(3)
    make_client(tenant).get_by_ids(
        "article", ["1", "2"], {"page": 3, "pageSize": 9, "sort": "id", "properties": "id"}
    )
    (hit,) = list_hits(tenant)
    assert set(hit.query) == {"id-in", "pageSize", "properties"}
    assert hit.query["pageSize"] == "2"


def test_get_by_ids_runs_chunks_concurrently() -> None:
    tenant = tenant_with(4)
    barrier = threading.Barrier(2, timeout=2)

    def interceptor(method: str, path: str, query: dict[str, str], body: Any) -> Outcome | None:
        if "id-in" in query:
            barrier.wait()  # breaks (and fails the read) if chunks ran one at a time
        return None

    result = make_client(tenant, interceptor).get_by_ids(
        "article", ["1", "2", "3", "4"], chunk_size=1
    )
    assert ids(result) == ["1", "2", "3", "4"]


def test_get_by_ids_empty_and_validation() -> None:
    tenant = tenant_with(1)
    client = make_client(tenant, max_concurrency=2)
    assert client.get_by_ids("article", []) == []
    empty = client.get_by_ids("article", [], return_weclapp_response=True)
    assert isinstance(empty, WeclappResponse)
    with pytest.raises(ValueError, match="chunk_size"):
        client.get_by_ids("article", ["1"], chunk_size=0)
    with pytest.raises(ValueError, match="max_workers"):
        client.get_by_ids("article", ["1"], max_workers=3)
    assert tenant.hits == []


# ----------------------------------------------------------------- iter_all
def test_iter_all_is_lazy_and_pages_sequentially() -> None:
    tenant = tenant_with(5)
    iterator = make_client(tenant).iter_all("article", {"pageSize": 2})
    assert tenant.hits == []
    first = next(iterator)
    assert isinstance(first, WeclappEntity)
    assert pages(tenant) == [1]
    assert ids([first, *iterator]) == expected_ids(5)
    assert pages(tenant) == [1, 2, 3]
    assert list_hits(tenant)[0].query["sort"] == "id"


def test_iter_all_limit_stops_early() -> None:
    tenant = tenant_with(10)
    assert ids(make_client(tenant).iter_all("article", {"pageSize": 2}, limit=3)) == ["1", "2", "3"]
    assert pages(tenant) == [1, 2]


def test_iter_all_detects_duplicates() -> None:
    tenant = tenant_with(6)

    def interceptor(method: str, path: str, query: dict[str, str], body: Any) -> Outcome | None:
        if query.get("page") == "2":
            return Reply(200, {"result": make_rows(2, start=2)})
        return None

    iterator = make_client(tenant, interceptor).iter_all("article", {"pageSize": 2})
    assert ids([next(iterator), next(iterator)]) == ["1", "2"]
    with pytest.raises(WeclappPaginationError, match="duplicate"):
        next(iterator)


# -------------------------------------------------------------- iter_keyset
def test_iter_keyset_progresses_with_id_gt() -> None:
    tenant = tenant_with(5)
    result = list(make_client(tenant).iter_keyset("article", {"pageSize": 2}))
    assert ids(result) == expected_ids(5)
    queries = [hit.query for hit in list_hits(tenant)]
    assert [query.get("id-gt") for query in queries] == [None, "2", "4"]
    assert {query["sort"] for query in queries} == {"id"}
    assert all("page" not in query for query in queries)


def test_iter_keyset_start_after_and_trailing_empty_page() -> None:
    tenant = tenant_with(5)
    result = list(make_client(tenant).iter_keyset("article", {"pageSize": 2}, start_after="3"))
    assert ids(result) == ["4", "5"]
    assert [hit.query.get("id-gt") for hit in list_hits(tenant)] == ["3", "5"]


def test_iter_keyset_limit() -> None:
    tenant = tenant_with(10)
    result = list(make_client(tenant).iter_keyset("article", {"pageSize": 2}, limit=3))
    assert ids(result) == ["1", "2", "3"]
    assert len(list_hits(tenant)) == 2


@pytest.mark.parametrize("key", ["page", "sort", "orderBy", "id-gt"])
def test_iter_keyset_rejects_managed_params(key: str) -> None:
    tenant = tenant_with(2)
    iterator = make_client(tenant).iter_keyset("article", {key: "1"})
    with pytest.raises(ValueError, match=key):
        next(iterator)
    assert tenant.hits == []


def test_iter_keyset_needs_id_in_the_projection() -> None:
    tenant = tenant_with(3)
    iterator = make_client(tenant).iter_keyset("article", {"pageSize": 2, "properties": "name"})
    with pytest.raises(WeclappPaginationError, match="needs 'id'"):
        list(iterator)
