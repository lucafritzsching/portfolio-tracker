"""HTTP integration tests via httpx ASGITransport against an isolated SQLite DB.

These drive the real FastAPI app (routing, Pydantic validation, DB session, SSE framing) without
a network or Postgres. The DB URL is set to async SQLite in conftest.py; each test resets the
schema first. yfinance is monkeypatched where a route would otherwise hit the network.
"""
import asyncio

import httpx
import pandas as pd
from httpx import ASGITransport

import services.market_data as market_data
from database import engine, Base
from main import app


async def _reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def test_health():
    async def _run():
        async with _client() as c:
            return await c.get("/health")

    r = asyncio.run(_run())
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_position_crud_and_transaction_updates_shares():
    async def _run():
        await _reset_db()
        async with _client() as c:
            # create (ticker lower-cased on the way in → stored upper-case)
            r = await c.post("/api/portfolio/positions",
                             json={"ticker": "aapl", "name": "Apple", "shares": "0", "sector": "Technologie"})
            assert r.status_code == 201, r.text
            assert r.json()["ticker"] == "AAPL"

            # duplicate is rejected
            dup = await c.post("/api/portfolio/positions", json={"ticker": "AAPL", "name": "Apple"})
            assert dup.status_code == 400

            # listed
            lst = await c.get("/api/portfolio/positions")
            assert [p["ticker"] for p in lst.json()] == ["AAPL"]

            # a buy transaction increases the position's shares
            tx = await c.post("/api/portfolio/positions/AAPL/transactions",
                              json={"type": "buy", "shares": "10", "price": "150", "date": "2024-01-02"})
            assert tx.status_code == 201, tx.text
            got = await c.get("/api/portfolio/positions/AAPL")
            assert float(got.json()["shares"]) == 10.0

            # delete → gone
            assert (await c.delete("/api/portfolio/positions/AAPL")).status_code == 204
            assert (await c.get("/api/portfolio/positions/AAPL")).status_code == 404

    asyncio.run(_run())


def test_import_legacy_data_then_rejects_when_not_empty():
    async def _run():
        await _reset_db()
        async with _client() as c:
            payload = {
                "positions": [{"ticker": "msft", "name": "Microsoft", "shares": 5.0, "sector": "Technologie"}],
                "transactions": [],
            }
            first = await c.post("/api/portfolio/import", json=payload)
            assert first.status_code == 201, first.text
            assert first.json()["imported_positions"] == 1

            # second import is refused because the DB is no longer empty
            second = await c.post("/api/portfolio/import", json=payload)
            assert second.status_code == 409

            lst = await c.get("/api/portfolio/positions")
            assert [p["ticker"] for p in lst.json()] == ["MSFT"]

    asyncio.run(_run())


def test_invalid_ticker_is_rejected_with_400():
    async def _run():
        await _reset_db()
        async with _client() as c:
            create = await c.post("/api/portfolio/positions", json={"ticker": "bad symbol!", "name": "X"})
            get = await c.get("/api/portfolio/positions/<script>")
            return create, get

    create, get = asyncio.run(_run())
    assert create.status_code == 400
    assert get.status_code == 400


def test_quick_stats_without_price_data_returns_error(monkeypatch):
    # No cached prices + yfinance returns an empty frame → endpoint reports "no data" (no crash).
    monkeypatch.setattr(market_data.yf, "download", lambda *a, **k: pd.DataFrame())

    async def _run():
        await _reset_db()
        async with _client() as c:
            return await c.get("/api/agent/quick-stats/FAKE")

    r = asyncio.run(_run())
    assert r.status_code == 200
    assert "error" in r.json()


def test_ask_persists_run_and_lists_it():
    # Even with Ollama unavailable in the test env, ask_stream persists the run (status=error);
    # the new read endpoint must then return it. Validates the end-to-end persistence wiring.
    async def _run():
        await _reset_db()
        async with _client() as c:
            await c.get("/api/agent/ask", params={"question": "Hallo Persistenz"})
            return await c.get("/api/agent/runs")

    r = asyncio.run(_run())
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["question"] == "Hallo Persistenz"
    assert "trace" not in data[0]   # list view is the lightweight summary (no trace)


def test_ask_endpoint_streams_and_terminates():
    # Ollama is unavailable in the test env; the SSE wrapper must degrade gracefully and still
    # frame a well-formed stream that terminates with [DONE] (validates endpoint + DB + SSE plumbing).
    async def _run():
        await _reset_db()
        async with _client() as c:
            return await c.get("/api/agent/ask", params={"question": "Hallo"})

    r = asyncio.run(_run())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "[DONE]" in r.text
