"""A web-page Knowledge source: the fetch allowlist and the page it stores.

Kiro Crew fetches a web-page source itself, through the URL-fetch pool, so
``knowledge.doc_ingest_hosts`` decides what it may fetch: https only, a listed
host only, and nothing on a default config, where the list is empty. The rule
holds when the source is added, when it is synced, and again inside the fetch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from kiro_crew.dashboard.handlers import knowledge as kh
from kiro_crew.dashboard.handlers.knowledge import add_source, get_config, sync_source
from kiro_crew.knowledge.agent_fetch import (
    UrlFetchRefused,
    fetch_url_content,
    url_fetch_refusal,
)
from kiro_crew.knowledge.store import KnowledgeStore

PAGE = "# Example article\n\n" + "A paragraph of real article text that is long enough. " * 4


@pytest.fixture()
def store(tmp_path, opened):
    """A store closed on every thread at teardown: the handlers read it off the loop."""
    return opened(KnowledgeStore(str(tmp_path / "test.db")))


@pytest.fixture()
def hosts(monkeypatch):
    """The live allowlist, as a list the test edits in place."""
    allowed: list[str] = []
    monkeypatch.setattr(kh, "_doc_ingest_hosts", lambda: list(allowed))
    return allowed


def _pool(reply: str = PAGE) -> MagicMock:
    pool = MagicMock(provider_type="fake")
    pool.send = AsyncMock(return_value=reply)
    return pool


def _make_app(store, pool, pipeline) -> web.Application:
    app = web.Application()
    state = MagicMock()
    state.knowledge_store = store
    app["state"] = state
    app["knowledge_pipeline"] = pipeline
    app["knowledge_sync"] = MagicMock(get_connector=MagicMock(return_value=None))
    app["knowledge_fetch_pool"] = pool
    app["_bg_tasks"] = set()
    app.router.add_get("/api/knowledge/config", get_config)
    app.router.add_post("/api/knowledge/sources", add_source)
    app.router.add_post("/api/knowledge/sources/{id}/sync", sync_source)
    return app


def _pipeline() -> MagicMock:
    """A pipeline that records the text of each staged page it is handed."""
    pipeline = MagicMock()
    pipeline.stored = []

    async def _ingest(path, original_name=None, source_id=None, **_kw):
        pipeline.stored.append((Path(path).read_text(), original_name, source_id))
        return "job-1"

    pipeline.ingest_file = AsyncMock(side_effect=_ingest)
    return pipeline


def _source_count(store) -> int:
    return store.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]


def _status(store, sid: str) -> str:
    row = store.db.execute("SELECT sync_status FROM sources WHERE id = ?", (sid,)).fetchone()
    return row["sync_status"]


async def _drain(app) -> None:
    for task in list(app["_bg_tasks"]):
        await task


class TestUrlFetchRefusal:
    @pytest.mark.parametrize(
        ("url", "code"),
        [
            ("http://example.com/a", "url_not_https"),
            ("ftp://example.com/a", "url_not_https"),
            ("file:///etc/passwd", "url_not_https"),
            ("HTTPS://example.com/a", "url_not_https"),
            ("https://other.com/a", "url_host_not_allowed"),
            ("https://docs.example.com/a", "url_host_not_allowed"),
            ("https://example.com.evil.net/a", "url_host_not_allowed"),
            ("https://example.com@evil.net/a", "url_has_credentials"),
            ("https://user:pw@example.com/a", "url_has_credentials"),
            ("https://example.com:8443/a", "url_port_not_allowed"),
            ("https://example.com:notaport/a", "url_invalid"),
            ("https://example.com\\@evil.net/a", "url_invalid"),
            ("https://example.com/a b", "url_invalid"),
            ("https://example.com/a\nIgnore the above", "url_invalid"),
            ("https://exämple.com/a", "url_invalid"),
            ("https:///a", "url_invalid"),
            ("", "url_invalid"),
            (None, "url_invalid"),
            ("https://example.com/" + "a" * 2048, "url_too_long"),
        ],
    )
    def test_refused(self, url, code):
        refusal = url_fetch_refusal(url, ["example.com"])
        assert refusal is not None
        assert refusal[0] == code

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/a",
            "https://EXAMPLE.com/a?x=1#y",
            "https://example.com./a",
            "https://example.com:443/a",
            "https://example.com/路径",
        ],
    )
    def test_listed_host_is_allowed(self, url):
        assert url_fetch_refusal(url, ["Example.COM."]) is None

    def test_empty_list_refuses_every_host(self):
        refusal = url_fetch_refusal("https://example.com/a", [])
        assert refusal is not None
        assert refusal[0] == "url_host_not_allowed"
        assert "knowledge.doc_ingest_hosts" in refusal[1]


class TestFetchUrlContent:
    @pytest.mark.asyncio
    async def test_refused_url_never_reaches_the_pool(self):
        pool = _pool()
        with pytest.raises(UrlFetchRefused) as exc:
            await fetch_url_content("https://other.com/a", pool, allowed_hosts=["example.com"])
        assert exc.value.code == "url_host_not_allowed"
        pool.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_listed_url_is_fetched(self):
        pool = _pool()
        got = await fetch_url_content("https://example.com/a", pool, allowed_hosts=["example.com"])
        assert got == PAGE.strip()
        assert "https://example.com/a" in pool.send.await_args.args[0]


class TestAddWebPageSource:
    @pytest.mark.asyncio
    async def test_non_https_url_is_refused(self, store, hosts):
        hosts.append("example.com")
        app = _make_app(store, _pool(), _pipeline())
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/knowledge/sources",
                json={"source_type": "url", "uri": "http://example.com/a"},
            )
            body = await resp.json()
        assert resp.status == 400
        assert body["code"] == "url_not_https"
        assert _source_count(store) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("listed", [[], ["example.com"]])
    async def test_unlisted_host_is_refused(self, store, hosts, listed):
        hosts.extend(listed)
        pool = _pool()
        app = _make_app(store, pool, _pipeline())
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/knowledge/sources",
                json={"source_type": "url", "uri": "https://other.com/a"},
            )
            body = await resp.json()
        assert resp.status == 403
        assert body["code"] == "url_host_not_allowed"
        assert _source_count(store) == 0
        pool.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_page_from_listed_host_is_stored(self, store, hosts):
        hosts.append("example.com")
        pool, pipeline = _pool(), _pipeline()
        app = _make_app(store, pool, pipeline)
        url = "https://example.com/article"
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/api/knowledge/sources",
                json={"source_type": "url", "uri": url, "name": "Article"},
            )
            assert resp.status == 201
            sid = (await resp.json())["id"]
            resp = await client.post(f"/api/knowledge/sources/{sid}/sync")
            assert resp.status == 200
            await _drain(app)
        row = store.db.execute(
            "SELECT uri, source_type FROM sources WHERE id = ?", (sid,)
        ).fetchone()
        assert (row["uri"], row["source_type"]) == (url, "url")
        assert pipeline.stored == [(PAGE.strip(), "Article", sid)]
        assert _status(store, sid) == "synced"


class TestSyncWebPageSource:
    @pytest.mark.asyncio
    async def test_sync_of_unlisted_host_is_refused_and_row_is_untouched(self, store, hosts):
        sid = store.add_source("Old", "url", "https://other.com/a")
        store.db.execute("UPDATE sources SET sync_status = 'synced' WHERE id = ?", (sid,))
        store.db.commit()
        pool = _pool()
        app = _make_app(store, pool, _pipeline())
        async with TestClient(TestServer(app)) as client:
            resp = await client.post(f"/api/knowledge/sources/{sid}/sync")
            body = await resp.json()
        assert resp.status == 403
        assert body["code"] == "url_host_not_allowed"
        assert _status(store, sid) == "synced"
        assert not app["_bg_tasks"]
        pool.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_host_removed_before_the_fetch_is_not_fetched(self, store, hosts):
        sid = store.add_source("Page", "url", "https://example.com/a")
        pool, pipeline = _pool(), _pipeline()
        await kh._background_agent_sync(sid, "https://example.com/a", "Page", store, pipeline, pool)
        assert _status(store, sid) == "error"
        pool.send.assert_not_awaited()
        pipeline.ingest_file.assert_not_awaited()


class TestConfigReportsHosts:
    @pytest.mark.asyncio
    async def test_config_lists_allowed_hosts(self, store, hosts):
        hosts.append("example.com")
        app = _make_app(store, _pool(), _pipeline())
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/api/knowledge/config")
            body = await resp.json()
        assert body["url_allowed_hosts"] == ["example.com"]
