"""End-to-end: the real client over real HTTP against :class:`fakeserver.FakeWeclappServer`.

Everything runs on 127.0.0.1 with sub-second backoffs and cooldowns; tests
never sleep to wait for something, they join on the client calls.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from itertools import pairwise
from typing import Any

import pytest

from fakeserver import (
    CLOSE,
    HANG,
    OPENAPI_HIDDEN_YAML,
    OPENAPI_YAML,
    FakeTenant,
    FakeWeclappServer,
    Reply,
    closed_port,
    make_rows,
    problem,
)
from weclappy import (
    ConcurrencyController,
    ConcurrencySettings,
    RequestMetrics,
    RetryPolicy,
    Weclapp,
    WeclappAPIError,
    WeclappNotFoundError,
    WeclappTransportError,
)

FAST_RETRIES = RetryPolicy(backoff_factor=0.01, rate_limit_backoff=0.05, max_backoff=0.2)

type ServerFactory = Callable[..., FakeWeclappServer]
type ClientFactory = Callable[..., Weclapp]


@pytest.fixture
def start_server() -> Iterator[ServerFactory]:
    servers: list[FakeWeclappServer] = []

    def start(tenant: FakeTenant | None = None, **kwargs: Any) -> FakeWeclappServer:
        server = FakeWeclappServer(tenant, **kwargs).start()
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.shutdown()


@pytest.fixture
def make_client() -> Iterator[ClientFactory]:
    clients: list[Weclapp] = []

    def make(base_url: str, **kwargs: Any) -> Weclapp:
        kwargs.setdefault("timeout", 2.0)
        kwargs.setdefault("retry_policy", FAST_RETRIES)
        kwargs.setdefault(
            "concurrency",
            ConcurrencyController(
                ConcurrencySettings(
                    max_concurrency=kwargs.pop("max_concurrency", 10),
                    min_rate_limit_cooldown=0.05,
                )
            ),
        )
        client = Weclapp(base_url, "e2e-token", **kwargs)
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def articles(count: int) -> FakeTenant:
    return FakeTenant({"article": make_rows(count)})


def ids(rows: Any) -> list[str]:
    return [row["id"] for row in rows]


def expected_ids(count: int) -> list[str]:
    return [str(i) for i in range(1, count + 1)]


# ------------------------------------------------------------ bulk reads
def test_get_all_under_a_tenant_concurrency_limit(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    """3,500 rows in 35 pages against a tenant that queues above 3 and rejects above 6."""
    server = start_server(
        articles(3500), concurrency_limit=3, reject_above=6, processing_delay=0.005
    )
    seen: list[RequestMetrics] = []
    client = make_client(server.base_url, on_response=seen.append)
    result = client.get_all("article", {"pageSize": 100})

    assert ids(result) == expected_ids(3500)
    assert len(set(ids(result))) == 3500
    assert client.concurrency.active == 0
    # The final target depends on how hard the runner saturates the server, so
    # the invariant is: feedback was acted on. Every queued response carries the
    # ``concurrency`` reason and must have lowered the target at least once.
    targets = [m.concurrency_target for m in seen]
    assert max(targets) <= client.concurrency.ceiling
    if any(m.wait_reason == "concurrency" for m in seen):
        assert any(later < earlier for earlier, later in pairwise(targets))
    stats = client.stats
    assert stats.rate_limited <= 5
    assert stats.requests == len(server.hits)
    assert len(server.tenant.hits_for("GET", "article/count")) == 1
    assert server.max_in_flight <= 6


def test_scripted_429s_are_absorbed(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    tenant = articles(1000)
    rejection = Reply(
        429,
        {"type": "https://api.weclapp.com/errors/too_many_requests"},
        headers={"X-Weclapp-Wait-Ms": "30000", "X-Weclapp-Wait-Reason": "concurrency"},
    )
    tenant.script("GET", "article", rejection, rejection)
    server = start_server(tenant)
    client = make_client(server.base_url)
    result = client.get_all("article", {"pageSize": 100})
    assert ids(result) == expected_ids(1000)
    assert client.stats.rate_limited == 2
    assert client.stats.retries == 2
    assert client.stats.max_wait_ms == 30000


def test_get_by_ids_round_trip(start_server: ServerFactory, make_client: ClientFactory) -> None:
    server = start_server(articles(1200))
    client = make_client(server.base_url)
    wanted = [str(i) for i in range(1200, 0, -2)] + ["99999"]
    result = client.get_by_ids("article", wanted, {"properties": "id,name"})
    assert ids(result) == wanted[:-1]
    assert result[0]["name"] == "Record 1200"
    chunk_hits = [hit for hit in server.hits if "id-in" in hit.query]
    assert len(chunk_hits) == 2
    assert sorted(int(hit.query["pageSize"]) for hit in chunk_hits) == [
        101,
        500,
    ]  # 600 even ids + one unknown id


def test_strategy_ids_round_trip(start_server: ServerFactory, make_client: ClientFactory) -> None:
    server = start_server(articles(1200))
    client = make_client(server.base_url)
    result = client.get_all("article", {"pageSize": 500, "properties": "id,name"}, strategy="ids")
    assert ids(result) == expected_ids(1200)
    assert set(result[0]) >= {"id", "name"}


def test_iter_keyset_round_trip(start_server: ServerFactory, make_client: ClientFactory) -> None:
    server = start_server(articles(250))
    client = make_client(server.base_url)
    assert ids(client.iter_keyset("article", {"pageSize": 100})) == expected_ids(250)
    assert [hit.query.get("id-gt") for hit in server.hits] == [None, "100", "200"]


# ------------------------------------------------- unofficial read endpoints
def test_query_query_count_batch_and_openapi(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    server = start_server(articles(1200))
    client = make_client(server.base_url)

    rows = client.query("article", filter="id in ['3','1']", properties=["id", "name"])
    assert [(row["id"], row["name"]) for row in rows] == [("1", "Record 1"), ("3", "Record 3")]
    assert client.query_count("article", filter="id > 1190") == 10

    batch = client.batch_query(["article?pageSize=2&sort=id", "/article/count", "nope/id/1"])
    assert [entry.index for entry in batch] == [0, 1, 2]
    assert ids(batch[0].body["result"]) == ["1", "2"]
    assert batch[1].body == {"result": 1200}
    assert (batch[2].status, batch[2].ok) == (404, False)

    assert client.openapi() == OPENAPI_YAML
    assert client.openapi(include_hidden=True) == OPENAPI_HIDDEN_YAML
    assert client.stats.requests == len(server.hits) == 5


# ------------------------------------------------------------ write safety
def test_post_on_500_hits_exactly_once(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    tenant = FakeTenant()
    tenant.script("POST", "article", problem(500, "internal"))
    server = start_server(tenant)
    with pytest.raises(WeclappAPIError) as info:
        make_client(server.base_url).post("article", {"name": "x"})
    assert info.value.status_code == 500
    assert len(tenant.hits_for("POST", "article")) == 1


def test_put_on_socket_close_hits_once_with_unknown_outcome(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    tenant = articles(1)
    tenant.script("PUT", "article/id/1", CLOSE)
    server = start_server(tenant)
    with pytest.raises(WeclappTransportError) as info:
        make_client(server.base_url).put("article", "1", {"name": "y"})
    assert len(tenant.hits_for("PUT", "article/id/1")) == 1
    assert info.value.outcome_unknown is True
    assert info.value.request_sent is True
    assert tenant.hits_for("PUT", "article/id/1")[0].body == {"name": "y"}


def test_post_on_read_timeout_hits_once_with_unknown_outcome(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    tenant = FakeTenant()
    tenant.script("POST", "article", HANG)
    server = start_server(tenant)
    client = make_client(server.base_url, timeout=(1.0, 0.2))
    with pytest.raises(WeclappTransportError, match="ReadTimeout") as info:
        client.post("article", {"name": "x"})
    assert info.value.outcome_unknown is True
    assert len(tenant.hits_for("POST", "article")) == 1


def test_get_on_read_timeout_is_retried(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    tenant = articles(2)
    tenant.script("GET", "article", HANG)
    server = start_server(tenant)
    client = make_client(
        server.base_url,
        timeout=(1.0, 0.2),
        retry_policy=RetryPolicy(max_retries=1, backoff_factor=0.01, max_backoff=0.2),
    )
    assert ids(client.get("article")) == ["1", "2"]
    assert len(tenant.hits_for("GET", "article")) == 2


def test_post_on_connection_refused_is_retried_then_not_sent(
    make_client: ClientFactory,
) -> None:
    seen: list[RequestMetrics] = []
    client = make_client(
        f"http://127.0.0.1:{closed_port()}/webapp/api/v2/", on_response=seen.append
    )
    with pytest.raises(WeclappTransportError) as info:
        client.post("article", {"name": "x"})
    assert info.value.request_sent is False
    assert info.value.outcome_unknown is False
    assert [m.attempt for m in seen] == [1, 2, 3, 4]
    assert [m.will_retry for m in seen] == [True, True, True, False]
    assert {m.error for m in seen} == {"ConnectionError"}
    assert client.stats.transport_errors == 4


def test_get_retries_503_until_success(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    tenant = articles(3)
    tenant.script("GET", "article", problem(503, "unavailable"), problem(503, "unavailable"))
    server = start_server(tenant)
    seen: list[RequestMetrics] = []
    client = make_client(server.base_url, on_response=seen.append)
    assert ids(client.get("article")) == ["1", "2", "3"]
    assert len(tenant.hits_for("GET", "article")) == 3
    assert [m.status_code for m in seen] == [503, 503, 200]
    stats = client.stats
    assert (stats.requests, stats.retries, stats.http_errors) == (3, 2, 2)
    assert stats.by_status == {503: 2, 200: 1}


def test_crud_round_trip_and_stats_match_hits(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    server = start_server(FakeTenant())
    seen: list[RequestMetrics] = []
    client = make_client(server.base_url, on_response=seen.append)

    created = client.post("article", {"name": "new"})
    entity_id = created["id"]
    assert client.put("article", entity_id, {"name": "renamed"})["name"] == "renamed"
    assert client.get("article", entity_id).name == "renamed"
    assert client.delete("article", entity_id) == {}
    with pytest.raises(WeclappNotFoundError):
        client.get("article", entity_id)

    assert [hit.method for hit in server.hits] == ["POST", "PUT", "GET", "DELETE", "GET"]
    assert server.hits[1].query == {"ignoreMissingProperties": "True"}
    assert len(seen) == len(server.hits) == client.stats.requests


def test_default_headers_reach_the_server(
    start_server: ServerFactory, make_client: ClientFactory
) -> None:
    server = start_server(articles(1))
    make_client(server.base_url).get("article")
    (hit,) = server.hits
    assert hit.headers["AuthenticationToken"] == "e2e-token"
    assert hit.headers["User-Agent"].startswith("weclappy/")
    assert hit.headers["X-Weclapp-Wait-Timeout-Ms"] == "30000"
    assert int(hit.headers["X-Weclapp-Request-Timeout-Ms"]) < 2000
