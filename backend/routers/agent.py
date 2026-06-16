"""Agent SSE streaming endpoint."""
import asyncio
import json
import logging
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from database import AsyncSessionLocal
from agent.orchestrator import (
    analyze_stock_stream, analyze_portfolio_stream,
    chat_stream, news_summary_stream, rebalance_stream, ask_stream,
)

logger = logging.getLogger("agent")

router = APIRouter(prefix="/agent", tags=["agent"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _parse_prices(current_prices: str) -> dict:
    try:
        return json.loads(current_prices) if current_prices else {}
    except json.JSONDecodeError:
        return {}


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
            except Exception as e:
                logger.exception("SSE-Stream-Fehler")
                yield f"data: [FEHLER: {e}]\n\n"
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

    ticker = ticker.upper()
    async with AsyncSessionLocal() as db:
        rows = await fetch_and_store_prices(ticker, db, period="2y")
    prices = prices_to_dicts(rows)
    if not prices:
        return {"ticker": ticker, "error": "Keine Kursdaten verfügbar."}
    arima = await asyncio.to_thread(run_arima_forecast, prices)
    ml = await asyncio.to_thread(run_ml_signal, prices)
    return {
        "ticker": ticker,
        "arima": {"signal": arima.signal, "confidence": arima.confidence,
                  "forecast_30d": arima.forecast_30d, "details": arima.details},
        "random_forest": {"signal": ml.signal, "confidence": ml.confidence, "details": ml.details},
    }


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
