"""Screener-Endpoints: Alt-B-Scan (SSE), letzter Run, Universum-Status/-Refresh."""
import asyncio
import json
from contextlib import suppress

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from schemas import ScreenerResponseOut, ScreenerUniverseStatusOut
from services.screener import load_latest_run, run_alt_b_scan
from services.universe import crawl_biotech_universe, load_universe, save_universe

router = APIRouter(prefix="/screener", tags=["screener"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

_EMPTY_RESPONSE = {
    "universe_count": 0,
    "filter_funnel": [],
    "windows": {"event_days": 7, "context_days": 90, "insider_context_days": 180},
    "candidates": [],
    "created_at": None,
    "universe_source": "live",
    "universe_updated_at": None,
}


@router.get("/alt-b/latest")
async def get_latest_run(db: AsyncSession = Depends(get_db)):
    """Letzter persistierter Scan — sofort verfügbar, ohne neuen Scan zu starten."""
    run = await load_latest_run(db)
    if run is None:
        return _EMPTY_RESPONSE
    return run


# NOTE: GET, weil der Browser-EventSource nur GET kann; DB-Session lebt im Generator
# (siehe routers/agent.py).

@router.get("/alt-b/scan")
async def scan_alt_b(
    limit: int = Query(12, ge=1, le=25),
    min_score: int = Query(0, ge=0, le=100),
):
    """Alt-B-Scan über das volle Universum mit SSE-Fortschritt; Ergebnis wird gecacht."""

    async def event_stream():
        async with AsyncSessionLocal() as db:
            queue: asyncio.Queue = asyncio.Queue()

            async def put(event: dict) -> None:
                await queue.put(event)

            async def runner() -> None:
                try:
                    result = await run_alt_b_scan(db, limit=limit, min_score=min_score, progress=put)
                    await queue.put({"result": result.model_dump(mode="json")})
                except Exception as e:
                    await queue.put({"error": str(e)})
                finally:
                    await queue.put(None)

            task = asyncio.create_task(runner())
            completed = False
            try:
                while (event := await queue.get()) is not None:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                completed = True
                yield "data: [DONE]\n\n"
            finally:
                if not completed and not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/universe", response_model=ScreenerUniverseStatusOut)
async def get_universe_status(db: AsyncSession = Depends(get_db)):
    stocks, updated_at = await load_universe(db)
    if stocks:
        return ScreenerUniverseStatusOut(count=len(stocks), updated_at=updated_at, source="live")
    return ScreenerUniverseStatusOut(count=0, updated_at=None, source="live")


@router.get("/universe/refresh")
async def refresh_universe():
    """NASDAQ-Biotech/Pharma-Universum neu laden (NASDAQ Stock Screener, Sekunden) — SSE."""

    async def event_stream():
        async with AsyncSessionLocal() as db:
            queue: asyncio.Queue = asyncio.Queue()

            async def put(i: int, n: int, ticker: str) -> None:
                await queue.put({"stage": "Universum-Abruf", "i": i, "n": n, "ticker": ticker})

            async def runner() -> None:
                try:
                    stocks = await crawl_biotech_universe(progress=put)
                    if not stocks:
                        await queue.put({"error": "NASDAQ-Screener lieferte keine Daten — später erneut versuchen."})
                    else:
                        await save_universe(db, stocks)
                        await queue.put({"result": {"count": len(stocks)}})
                except Exception as e:
                    await queue.put({"error": str(e)})
                finally:
                    await queue.put(None)

            task = asyncio.create_task(runner())
            completed = False
            try:
                while (event := await queue.get()) is not None:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                completed = True
                yield "data: [DONE]\n\n"
            finally:
                if not completed and not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
