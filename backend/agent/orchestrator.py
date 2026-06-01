"""Ollama agent orchestrator with tool-use loop and SSE streaming."""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT_TEMPLATE, PORTFOLIO_ANALYSIS_PROMPT
from agent.tools import TOOL_DEFINITIONS, ToolExecutor
from config import settings
from models import Position, Transaction, AnalysisResult


MAX_TOOL_ITERATIONS = 8


async def analyze_stock_stream(
    ticker: str,
    db: AsyncSession,
    current_prices: dict[str, float],
) -> AsyncGenerator[str, None]:
    """Stream an SSE-compatible analysis for a single stock."""
    ticker = ticker.upper()

    # Build initial context
    result = await db.execute(select(Position).where(Position.ticker == ticker))
    pos = result.scalar_one_or_none()

    if pos:
        tx_result = await db.execute(
            select(Transaction).where(Transaction.ticker == ticker, Transaction.type == "buy")
        )
        buy_txs = tx_result.scalars().all()
        if buy_txs:
            total_cost = sum(float(t.shares) * float(t.price) for t in buy_txs)
            total_shares = sum(float(t.shares) for t in buy_txs)
            avg_buy = total_cost / total_shares if total_shares > 0 else None
        else:
            avg_buy = float(pos.manual_buy_price) if pos.manual_buy_price else None

        current = current_prices.get(ticker)
        unrealized_pnl = (current - avg_buy) * float(pos.shares) if avg_buy and current else None
        unrealized_pnl_pct = (current - avg_buy) / avg_buy * 100 if avg_buy and current else None

        all_positions_value = sum(
            current_prices.get(t, 0) * float(p.shares)
            for t, p in [(pos.ticker, pos)]
        )
        portfolio_weight = (
            ((current or 0) * float(pos.shares)) / all_positions_value * 100
            if all_positions_value > 0 else 0
        )

        user_prompt = ANALYSIS_PROMPT_TEMPLATE.format(
            ticker=ticker,
            name=pos.name,
            shares=f"{float(pos.shares):.4f}",
            avg_buy_price=f"{avg_buy:.2f} €" if avg_buy else "unbekannt",
            current_price=f"{current:.2f} €" if current else "unbekannt",
            unrealized_pnl=f"{unrealized_pnl:+.2f} €" if unrealized_pnl is not None else "unbekannt",
            unrealized_pnl_pct=f"{unrealized_pnl_pct:+.1f}" if unrealized_pnl_pct is not None else "unbekannt",
            portfolio_weight=f"{portfolio_weight:.1f}",
            sector=pos.sector,
        )
    else:
        user_prompt = f"Analysiere die Aktie {ticker}. Nutze alle verfügbaren Tools für eine vollständige Analyse."

    executor = ToolExecutor(db=db, current_prices=current_prices)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    full_response = ""

    async for chunk in _run_agent_loop(messages, executor):
        full_response += chunk
        yield chunk

    # Persist analysis result
    analysis = AnalysisResult(
        ticker=ticker,
        analysis_text=full_response,
        model=settings.ollama_model,
    )
    db.add(analysis)
    await db.commit()


async def analyze_portfolio_stream(
    db: AsyncSession,
    current_prices: dict[str, float],
) -> AsyncGenerator[str, None]:
    """Stream a portfolio-wide analysis."""
    result = await db.execute(select(Position))
    positions = result.scalars().all()

    if not positions:
        yield "Keine Positionen im Portfolio."
        return

    total_value = sum(current_prices.get(p.ticker, 0) * float(p.shares) for p in positions)

    positions_summary = "\n".join(
        f"- {p.ticker} ({p.name}): {float(p.shares):.2f} Aktien, "
        f"Kurs {current_prices.get(p.ticker, 0):.2f} €, "
        f"Wert {current_prices.get(p.ticker, 0) * float(p.shares):.2f} €, "
        f"Sektor: {p.sector}"
        for p in positions
    )

    user_prompt = PORTFOLIO_ANALYSIS_PROMPT.format(
        position_count=len(positions),
        total_value=f"{total_value:.2f} €",
        positions_summary=positions_summary,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    executor = ToolExecutor(db=db, current_prices=current_prices)
    async for chunk in _run_agent_loop(messages, executor):
        yield chunk


async def _run_agent_loop(
    messages: list[dict],
    executor: ToolExecutor,
) -> AsyncGenerator[str, None]:
    """Core agent loop: LLM → tool calls → LLM → ... → final response streaming."""
    iteration = 0

    while iteration < MAX_TOOL_ITERATIONS:
        iteration += 1
        is_last_iteration = iteration >= MAX_TOOL_ITERATIONS

        # Call Ollama
        payload = {
            "model": settings.ollama_model,
            "messages": messages,
            "stream": False,  # Non-streaming for tool-call phase
            "tools": TOOL_DEFINITIONS if not is_last_iteration else [],
            "options": {"temperature": 0.3},
        }

        async with httpx.AsyncClient(timeout=120) as client:
            try:
                resp = await client.post(
                    f"{settings.ollama_base_url}/api/chat",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                yield f"\n\n[Fehler bei Ollama-Anfrage: {e}]"
                return

        message = data.get("message", {})
        tool_calls = message.get("tool_calls", [])

        if not tool_calls:
            # No more tool calls — stream the final response
            content = message.get("content", "")
            messages.append({"role": "assistant", "content": content})

            # Stream final response token by token (simulate, since we have full response)
            async for chunk in _stream_final_response(content):
                yield chunk
            return

        # Execute tool calls
        messages.append({"role": "assistant", "content": message.get("content", ""), "tool_calls": tool_calls})

        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            arguments = fn.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}

            # Notify frontend that a tool is being called
            yield f"\n\n> Führe Tool aus: **{tool_name}**({_fmt_args(arguments)})...\n"

            tool_result = await executor.execute(tool_name, arguments)

            messages.append({
                "role": "tool",
                "content": tool_result,
            })

    # Fallback: ask for final summary without tools
    messages.append({
        "role": "user",
        "content": "Fasse jetzt alle gesammelten Daten zusammen und gib deine strukturierte Handlungsempfehlung.",
    })
    payload["stream"] = False
    payload["tools"] = []

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            async for chunk in _stream_final_response(content):
                yield chunk
        except Exception as e:
            yield f"\n\n[Fehler beim finalen Aufruf: {e}]"


async def _stream_final_response(content: str) -> AsyncGenerator[str, None]:
    """Stream a complete response string using Ollama's streaming endpoint."""
    # Use Ollama streaming for the final output so frontend sees tokens appearing
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "user", "content": f"Gib exakt folgenden Text aus, unverändert:\n\n{content}"}
        ],
        "stream": True,
        "options": {"temperature": 0.0},
    }

    # Actually: just stream the content directly, chunked
    # This is simpler and avoids double-inference cost
    chunk_size = 20
    for i in range(0, len(content), chunk_size):
        yield content[i:i + chunk_size]


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={repr(v)}" for k, v in args.items())
