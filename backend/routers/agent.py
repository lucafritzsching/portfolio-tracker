"""Agent SSE streaming endpoint."""
import asyncio
import json
import logging
import math
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from database import AsyncSessionLocal
from utils import normalize_ticker
from repositories.agent_repo import save_quick_stats, list_recent_runs, get_run
from schemas import AgentRunSummaryOut, AgentRunOut
from agent.orchestrator import (
    analyze_stock_stream, analyze_portfolio_stream,
    chat_stream, news_summary_stream, rebalance_stream, ask_stream,
)

logger = logging.getLogger("agent")

router = APIRouter(prefix="/agent", tags=["agent"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


MAX_PRICE_ENTRIES = 500  # Obergrenze gegen aufgeblähte Eingaben (Hosting)


def _parse_prices(current_prices: str) -> dict:
    """Parse the client-supplied price map and bound it: object only, max N entries, and only
    finite positive numbers (a negative/NaN price would silently corrupt downstream P&L/scoring)."""
    try:
        raw = json.loads(current_prices) if current_prices else {}
    except json.JSONDecodeError:
        logger.warning("current_prices ist kein gültiges JSON — ignoriert (%d Zeichen)", len(current_prices))
        return {}
    if not isinstance(raw, dict):
        logger.warning("current_prices ist kein JSON-Objekt — ignoriert")
        return {}
    clean: dict = {}
    for key, value in list(raw.items())[:MAX_PRICE_ENTRIES]:
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 0:
            clean[str(key)] = price
    if len(clean) < len(raw):
        logger.warning("current_prices: %d von %d Einträgen verworfen (ungültig oder über Limit)",
                       len(raw) - len(clean), len(raw))
    return clean


# NOTE: these are GET endpoints because the browser's EventSource API can only
# issue GET requests. The DB session is opened *inside* the generator (not via
# Depends) so it stays alive for the whole stream — a Depends(get_db) session is
# torn down when the handler returns, before StreamingResponse drains the body.

@router.get("/analyze/{ticker}")
async def analyze_stock(
    ticker: str,
    current_prices: str = Query("", description="JSON: {'AAPL': 185.0, ...}"),
    agentic: bool = Query(False, description="If true, the LLM investigates via tools (slower, visible)."),
):
    """Stream Ollama agent analysis for a single stock via SSE."""
    prices = _parse_prices(current_prices)

    async def event_stream():
        async with AsyncSessionLocal() as db:
            try:
                async for chunk in analyze_stock_stream(ticker.upper(), db, prices, agentic=agentic):
                    # SSE data lines can't contain raw newlines; escape them.
                    escaped = chunk.replace("\n", "\\n")
                    yield f"data: {escaped}\n\n"
            except Exception as e:
                yield f"data: [FEHLER: {e}]\n\n"
            finally:
                yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/analyze-portfolio")
async def analyze_portfolio(
    current_prices: str = Query("", description="JSON: {'AAPL': 185.0, ...}"),
):
    """Stream Ollama agent portfolio-wide analysis via SSE."""
    prices = _parse_prices(current_prices)

    async def event_stream():
        async with AsyncSessionLocal() as db:
            try:
                async for chunk in analyze_portfolio_stream(db, prices):
                    escaped = chunk.replace("\n", "\\n")
                    yield f"data: {escaped}\n\n"
            except Exception as e:
                yield f"data: [FEHLER: {e}]\n\n"
            finally:
                yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


def _sse(stream_factory):
    """Wrap an async chunk generator factory into an SSE event stream with its own DB session."""
    async def event_stream():
        async with AsyncSessionLocal() as db:
            try:
                async for chunk in stream_factory(db):
                    yield f"data: {chunk.replace(chr(10), chr(92) + 'n')}\n\n"
            except Exception:
                # Vollständige Diagnose ins Server-Log; an den Client nur eine generische
                # Meldung (keine internen Pfade/DB-Details leaken).
                logger.exception("SSE-Stream-Fehler")
                yield "data: [FEHLER: Interner Fehler bei der Verarbeitung. Details siehe Server-Log.]\n\n"
            finally:
                yield "data: [DONE]\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/chat")
async def chat(
    question: str = Query(..., description="Frage des Nutzers zum Portfolio"),
    current_prices: str = Query("", description="JSON: {'AAPL': 185.0, ...}"),
):
    """GenAI: free-text Q&A about the portfolio, grounded in a live snapshot (SSE)."""
    prices = _parse_prices(current_prices)
    return _sse(lambda db: chat_stream(question, db, prices))


@router.get("/ask")
async def ask(
    question: str = Query(..., description="Freitext-Anfrage an den Analyse-Agenten"),
    current_prices: str = Query("", description="JSON: {'AAPL': 185.0, ...}"),
    history: str = Query("", description="JSON-Liste vorheriger Turns: [{role, content}, ...] (Gedächtnis)"),
):
    """Unified routing agent: one free-text question (+ optional conversation history) → the LLM routes
    to the right tool (strategy screen / NL-news judgment / statistics) → visible tool-trace + explanation."""
    prices = _parse_prices(current_prices)
    try:
        hist = json.loads(history) if history else []
    except json.JSONDecodeError:
        hist = []
    if not isinstance(hist, list):
        hist = []
    return _sse(lambda db: ask_stream(question, db, prices, hist))


@router.get("/quick-stats/{ticker}")
async def quick_stats(ticker: str):
    """Deterministic statistical models (ARIMA + RandomForest) for a ticker — fast, NO LLM.

    Powers the "📊 Statistik" button in the positions view: one quick, reproducible call (CPU only,
    off the event loop) → ARIMA forecast/signal + RandomForest signal with honest confidence/OOS detail.
    """
    from services.market_data import fetch_and_store_prices, prices_to_dicts
    from agent.data_science import run_arima_forecast, run_ml_signal

    ticker = normalize_ticker(ticker)
    async with AsyncSessionLocal() as db:
        rows = await fetch_and_store_prices(ticker, db, period="2y")
        prices = prices_to_dicts(rows)
        if not prices:
            return {"ticker": ticker, "error": "Keine Kursdaten verfügbar."}
        arima = await asyncio.to_thread(run_arima_forecast, prices)
        ml = await asyncio.to_thread(run_ml_signal, prices)
        try:
            await save_quick_stats(db, ticker, arima, ml)   # persist (reuses analysis_results)
        except Exception:
            logger.exception("Persistenz der Quick-Stats fehlgeschlagen für %s", ticker)
    return {
        "ticker": ticker,
        "arima": {"signal": arima.signal, "confidence": arima.confidence,
                  "forecast_30d": arima.forecast_30d, "details": arima.details},
        "random_forest": {"signal": ml.signal, "confidence": ml.confidence, "details": ml.details},
    }


@router.get("/runs", response_model=list[AgentRunSummaryOut])
async def list_runs(limit: int = Query(50, ge=1, le=200)):
    """Persisted agent runs, newest first — the server-side chat history."""
    async with AsyncSessionLocal() as db:
        return await list_recent_runs(db, limit=limit)


@router.get("/runs/{run_id}", response_model=AgentRunOut)
async def get_run_detail(run_id: int):
    """One persisted run incl. the full (untruncated) tool trace."""
    async with AsyncSessionLocal() as db:
        run = await get_run(db, run_id)
    if not run:
        raise HTTPException(404, "Agent-Lauf nicht gefunden")
    return run


@router.get("/news-summary/{ticker}")
async def news_summary(ticker: str):
    """GenAI: summarize the latest news for a ticker into themes + risks (SSE)."""
    return _sse(lambda db: news_summary_stream(ticker.upper(), db))


@router.get("/rebalance")
async def rebalance(
    current_prices: str = Query("", description="JSON: {'AAPL': 185.0, ...}"),
):
    """GenAI: diversification analysis + rebalancing suggestions (SSE)."""
    prices = _parse_prices(current_prices)
    return _sse(lambda db: rebalance_stream(db, prices))


@router.get("/status")
async def agent_status():
    """Check if Ollama is reachable and the model is available."""
    import httpx
    from config import settings

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            models = resp.json().get("models", [])
            model_names = [m["name"] for m in models]
            available = settings.ollama_model in model_names or any(
                settings.ollama_model.split(":")[0] in name for name in model_names
            )
            return {
                "ollama_reachable": True,
                "model": settings.ollama_model,
                "model_available": available,
                "available_models": model_names,
            }
    except Exception as e:
        return {
            "ollama_reachable": False,
            "error": str(e),
            "model": settings.ollama_model,
        }


@router.post("/pull-model")
async def pull_model():
    """Trigger Ollama to pull the configured model."""
    import httpx
    from config import settings

    async def pull_stream():
        async with httpx.AsyncClient(timeout=600) as client:
            async with client.stream(
                "POST",
                f"{settings.ollama_base_url}/api/pull",
                json={"name": settings.ollama_model, "stream": True},
            ) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        yield f"data: {line}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(pull_stream(), media_type="text/event-stream")
