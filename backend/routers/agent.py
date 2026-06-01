"""Agent SSE streaming endpoint."""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from agent.orchestrator import analyze_stock_stream, analyze_portfolio_stream
from schemas import AnalyzeRequest

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/analyze/{ticker}")
async def analyze_stock(
    ticker: str,
    current_prices: str = Query("", description="JSON: {'AAPL': 185.0, ...}"),
    db: AsyncSession = Depends(get_db),
):
    """Stream Ollama agent analysis for a single stock via SSE."""
    try:
        prices = json.loads(current_prices) if current_prices else {}
    except json.JSONDecodeError:
        prices = {}

    async def event_stream():
        try:
            async for chunk in analyze_stock_stream(ticker.upper(), db, prices):
                # SSE format: "data: ...\n\n"
                escaped = chunk.replace("\n", "\\n")
                yield f"data: {escaped}\n\n"
        except Exception as e:
            yield f"data: [FEHLER: {e}]\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/analyze-portfolio")
async def analyze_portfolio(
    current_prices: str = Query("", description="JSON: {'AAPL': 185.0, ...}"),
    db: AsyncSession = Depends(get_db),
):
    """Stream Ollama agent portfolio-wide analysis via SSE."""
    try:
        prices = json.loads(current_prices) if current_prices else {}
    except json.JSONDecodeError:
        prices = {}

    async def event_stream():
        try:
            async for chunk in analyze_portfolio_stream(db, prices):
                escaped = chunk.replace("\n", "\\n")
                yield f"data: {escaped}\n\n"
        except Exception as e:
            yield f"data: [FEHLER: {e}]\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
