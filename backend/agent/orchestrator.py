"""Ollama agent orchestrator — hybrid design.

Phase 1+2 (deterministic, agent/pipeline.py) compute the authoritative decision.
Phase 3 lets the LLM investigate via tools (visible in the UI).
Phase 4 streams the LLM's German explanation of the decision (real token streaming).
The LLM never overrides the decision — it only explains it.
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.data_science import EnsembleDecision
from agent.pipeline import build_ensemble_decision
from agent.prompts import SYSTEM_PROMPT, EXPLAIN_STOCK_PROMPT, EXPLAIN_PORTFOLIO_PROMPT
from config import settings
from models import Position, AnalysisResult

_COMPONENT_LABELS = {
    "technical": "Technischer Trend",
    "arima": "ARIMA-Prognose",
    "random_forest": "Random Forest",
    "fundamentals": "Fundamentaldaten",
    "news": "News-Sentiment",
    "portfolio_rule": "Portfolio-Regel",
}


def _format_components(decision: EnsembleDecision) -> str:
    lines = []
    for name, c in decision.components.items():
        label = _COMPONENT_LABELS.get(name, name)
        value = c["value"]
        value_str = f"{value:+.2f}" if isinstance(value, (int, float)) else str(value)
        if c.get("weight") is not None:
            lines.append(
                f"- {label}: Wert {value_str}, Gewicht {int(c['weight'] * 100)}%, "
                f"Beitrag {c['contribution']:+.2f}"
            )
        else:
            lines.append(f"- {label}: {value_str} (Beitrag {c['contribution']:+.2f})")
    return "\n".join(lines)


def render_decision_block(ticker: str, decision: EnsembleDecision) -> str:
    """The deterministic decision, streamed to the UI first (independent of the LLM)."""
    rationale = "\n".join(f"- {r}" for r in decision.rationale)
    return (
        f"## Deterministische Bewertung: {ticker}\n\n"
        f"**Empfehlung: {decision.signal}** "
        f"(Score {decision.score:+.2f} auf Skala −1..+1, Konfidenz {decision.confidence:.0%})\n\n"
        f"Komponenten:\n{_format_components(decision)}\n\n"
        f"Begründung der Pipeline:\n{rationale}\n\n"
        f"---\n\n## Begründung des Agenten\n\n"
    )


async def analyze_stock_stream(
    ticker: str,
    db: AsyncSession,
    current_prices: dict[str, float],
) -> AsyncGenerator[str, None]:
    """Stream a single-stock analysis: deterministic decision first, then LLM explanation."""
    ticker = ticker.upper()

    # Phase 1 + 2: deterministic data collection and decision.
    decision, context = await build_ensemble_decision(ticker, db, current_prices)

    block = render_decision_block(ticker, decision)
    yield block
    full_response = block

    # Phase 3: the deterministic pipeline already gathered prices, indicators,
    # fundamentals and news (all in `context`), so we hand that to the LLM and
    # stream its German explanation directly — no redundant tool round-trips,
    # which keeps the local 14B model responsive enough for live use.
    user_prompt = EXPLAIN_STOCK_PROMPT.format(
        ticker=ticker,
        signal=decision.signal,
        score=decision.score,
        confidence=decision.confidence,
        components=_format_components(decision),
        rationale="\n".join(f"- {r}" for r in decision.rationale),
        context=json.dumps(context, ensure_ascii=False, default=str),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    async for chunk in _stream_ollama_response(messages):
        full_response += chunk
        yield chunk

    db.add(AnalysisResult(ticker=ticker, analysis_text=full_response, model=settings.ollama_model))
    await db.commit()


async def analyze_portfolio_stream(
    db: AsyncSession,
    current_prices: dict[str, float],
) -> AsyncGenerator[str, None]:
    """Stream a portfolio-wide analysis: per-position deterministic decisions, then LLM summary."""
    positions = (await db.execute(select(Position))).scalars().all()
    if not positions:
        yield "Keine Positionen im Portfolio."
        return

    total_value = sum(current_prices.get(p.ticker, 0) * float(p.shares) for p in positions)

    yield "## Deterministische Bewertung je Position\n\n"
    decision_lines = []
    for pos in positions:
        decision, _ctx = await build_ensemble_decision(pos.ticker, db, current_prices)
        line = (f"- **{pos.ticker}** ({pos.name}): {decision.signal} "
                f"(Score {decision.score:+.2f}, Konfidenz {decision.confidence:.0%})")
        decision_lines.append(line)
        yield line + "\n"

    yield "\n---\n\n## Begründung des Agenten\n\n"

    user_prompt = EXPLAIN_PORTFOLIO_PROMPT.format(
        total_value=f"{total_value:.2f} €",
        decisions="\n".join(decision_lines),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    # Portfolio summary is narrative — stream directly without the per-ticker tool loop.
    async for chunk in _stream_ollama_response(messages):
        yield chunk


async def _stream_ollama_response(messages: list[dict]) -> AsyncGenerator[str, None]:
    """Real token streaming from Ollama /api/chat (no tools, so the output is pure text)."""
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": True,
        "think": False,  # qwen3 is a thinking model; disable to avoid slow <think> output
        "options": {"temperature": 0.3},
    }
    async with httpx.AsyncClient(timeout=180) as client:
        try:
            async with client.stream(
                "POST", f"{settings.ollama_base_url}/api/chat", json=payload
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
        except Exception as e:
            yield f"\n\n[Fehler beim Streaming: {e}]"
