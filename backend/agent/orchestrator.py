"""Ollama agent orchestrator — hybrid design.

Phase 1+2 (deterministic, agent/pipeline.py) compute the authoritative decision.
Phase 3 lets the LLM investigate via tools (visible in the UI).
Phase 4 streams the LLM's German explanation of the decision (gated via evidence catalog).
The LLM never overrides the decision — it only explains it.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.data_science import EnsembleDecision
from agent.evidence import build_evidence_catalog, format_catalog_for_prompt, EvidenceCatalog
from agent.pipeline import build_ensemble_decision, build_portfolio_snapshot
from agent.tools import TOOL_DEFINITIONS, ToolExecutor
from agent.prompts import (
    SYSTEM_PROMPT, EXPLAIN_STOCK_PROMPT, EXPLAIN_PORTFOLIO_PROMPT,
    CHAT_SYSTEM_PROMPT, CHAT_USER_PROMPT, NEWS_SUMMARY_PROMPT, REBALANCE_PROMPT,
    ROUTER_SYSTEM_PROMPT,
)
from config import settings
from eval.faithfulness import check_faithfulness, apply_faithfulness_gate
from agent.evidence import render as render_evidence
from models import Position, AnalysisResult, AnalysisMetric
from services.market_data import fetch_and_store_news

logger = logging.getLogger("agent")

_COMPONENT_LABELS = {
    "technical": "Technischer Trend",
    "arima": "ARIMA-Prognose",
    "random_forest": "Random Forest",
    "fundamentals": "Fundamentaldaten",
    "news": "News-Sentiment",
    "portfolio_rule": "Portfolio-Regel",
}

NO_DATA_MSG = (
    "## Keine Analyse möglich\n\n"
    "Für diesen Ticker liegen **keine Kursdaten** vor. "
    "Es wird keine Empfehlung erzeugt — bitte Ticker prüfen oder „Daten vorbereiten“ ausführen."
)


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


async def _gated_explanation_chunks(raw: str, catalog: EvidenceCatalog) -> AsyncGenerator[str, None]:
    """Render evidence placeholders, gate sentences, yield in chunks for SSE."""
    rendered = render_evidence(raw, catalog)
    gated = apply_faithfulness_gate(rendered, catalog)
    chunk_size = 120
    for i in range(0, len(gated), chunk_size):
        yield gated[i : i + chunk_size]


async def analyze_stock_stream(
    ticker: str,
    db: AsyncSession,
    current_prices: dict[str, float],
    agentic: bool = False,
) -> AsyncGenerator[str, None]:
    """Stream a single-stock analysis: deterministic decision first, then gated LLM explanation."""
    ticker = ticker.upper()

    decision, context = await build_ensemble_decision(ticker, db, current_prices)

    if not context.get("has_price_data", context.get("price_points", 0) > 0):
        yield NO_DATA_MSG
        return

    block = render_decision_block(ticker, decision)
    yield block
    full_response = block

    catalog = build_evidence_catalog(ticker, decision, context)
    evidence_block = format_catalog_for_prompt(catalog)

    user_prompt = EXPLAIN_STOCK_PROMPT.format(
        ticker=ticker,
        signal=decision.signal,
        score=decision.score,
        confidence=decision.confidence,
        components=_format_components(decision),
        rationale="\n".join(f"- {r}" for r in decision.rationale),
        evidence_catalog=evidence_block,
        context=json.dumps(context, ensure_ascii=False, default=str),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    stats: dict = {}
    explanation = ""

    if agentic:
        executor = ToolExecutor(db=db, current_prices=current_prices)
        raw_explanation = ""
        async for chunk in _run_agent_loop(messages, executor, stats, stream_final=False):
            if chunk.startswith("\n\n> 🔧"):
                full_response += chunk
                yield chunk
            else:
                raw_explanation += chunk
        async for chunk in _gated_explanation_chunks(raw_explanation, catalog):
            explanation += chunk
            full_response += chunk
            yield chunk
    else:
        raw = await _fetch_ollama_response(messages, stats)
        async for chunk in _gated_explanation_chunks(raw, catalog):
            explanation += chunk
            full_response += chunk
            yield chunk

    db.add(AnalysisResult(ticker=ticker, analysis_text=full_response, model=settings.ollama_model))
    await _record_metric(db, ticker, decision, explanation, stats, catalog)
    await db.commit()


MAX_TOOL_ITERATIONS = 5


async def _run_agent_loop(
    messages: list[dict],
    executor: ToolExecutor,
    stats: dict | None = None,
    show_tools: bool = True,
    stream_final: bool = True,
    temperature: float = 0.3,
    trace: list | None = None,
) -> AsyncGenerator[str, None]:
    """Tool-use loop: the LLM may call tools; the final answer is streamed or returned as one block."""
    iteration = 0
    while iteration < MAX_TOOL_ITERATIONS:
        iteration += 1
        is_last = iteration >= MAX_TOOL_ITERATIONS
        payload = {
            "model": settings.ollama_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "tools": TOOL_DEFINITIONS if not is_last else [],
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=180) as client:
            try:
                resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.exception("Ollama-Anfrage fehlgeschlagen (Iteration %d)", iteration)
                yield f"\n\n[Fehler bei Ollama-Anfrage: {e}]"
                return

        message = data.get("message", {})
        tool_calls = message.get("tool_calls", [])
        if not tool_calls:
            tool_calls = _extract_text_tool_calls(message.get("content", ""))
        logger.info("Agent-Loop It. %d: %d Tool-Call(s)%s", iteration, len(tool_calls),
                    "" if tool_calls else " → finale Antwort")
        if not tool_calls:
            if stream_final:
                async for token in _stream_ollama_response(messages, stats):
                    yield token
            else:
                text = await _fetch_ollama_response(messages, stats)
                yield text
            return

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
            if show_tools:
                yield f"\n\n> 🔧 Führe Tool aus: **{tool_name}**({_fmt_args(arguments)})…\n"
            tool_result = await executor.execute(tool_name, arguments)
            if trace is not None:
                trace.append({"step": iteration, "tool": tool_name, "args": arguments,
                              "result": tool_result[:2500]})
            messages.append({"role": "tool", "content": tool_result})

    messages.append({"role": "user", "content": "Fasse jetzt alle gesammelten Daten zusammen und begründe die Empfehlung."})
    if stream_final:
        async for token in _stream_ollama_response(messages, stats):
            yield token
    else:
        text = await _fetch_ollama_response(messages, stats)
        yield text


def _fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


def _extract_text_tool_calls(content: str) -> list[dict]:
    if not content or '"name"' not in content or '"arguments"' not in content:
        return []
    calls = []
    for line in content.splitlines():
        line = line.strip().strip(",").strip("`").strip()
        if not (line.startswith("{") and '"name"' in line and '"arguments"' in line):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "name" in obj and "arguments" in obj:
            calls.append({"function": {"name": obj["name"], "arguments": obj["arguments"]}})
    return calls


async def _record_metric(
    db: AsyncSession,
    ticker: str,
    decision: EnsembleDecision,
    explanation: str,
    stats: dict,
    catalog: EvidenceCatalog | None = None,
) -> None:
    try:
        eval_count = stats.get("eval_count")
        eval_duration = stats.get("eval_duration")
        tok_per_sec = (
            round(eval_count / (eval_duration / 1e9), 2)
            if eval_count and eval_duration else None
        )
        faith = check_faithfulness(decision, explanation, catalog)
        db.add(AnalysisMetric(
            ticker=ticker,
            model=settings.ollama_model,
            signal=decision.signal,
            score=decision.score,
            confidence=decision.confidence,
            total_ms=int(stats["total_duration"] / 1e6) if stats.get("total_duration") else None,
            load_ms=int(stats["load_duration"] / 1e6) if stats.get("load_duration") else None,
            prompt_tokens=stats.get("prompt_eval_count"),
            eval_tokens=eval_count,
            tokens_per_sec=tok_per_sec,
            faithful=faith["faithful"],
            faithfulness_notes=faith["notes"] or None,
        ))
    except Exception:
        pass


async def analyze_portfolio_stream(
    db: AsyncSession,
    current_prices: dict[str, float],
) -> AsyncGenerator[str, None]:
    positions = (await db.execute(select(Position))).scalars().all()
    if not positions:
        yield "Keine Positionen im Portfolio."
        return

    total_value = sum(current_prices.get(p.ticker, 0) * float(p.shares) for p in positions)

    yield "## Deterministische Bewertung je Position\n\n"
    decision_lines = []
    for pos in positions:
        decision, ctx = await build_ensemble_decision(pos.ticker, db, current_prices)
        if not ctx.get("has_price_data", ctx.get("price_points", 0) > 0):
            line = f"- **{pos.ticker}** ({pos.name}): NO_DATA"
        else:
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
    raw = await _fetch_ollama_response(messages)
    chunk_size = 120
    for i in range(0, len(raw), chunk_size):
        yield raw[i : i + chunk_size]


async def chat_stream(
    question: str, db: AsyncSession, current_prices: dict[str, float]
) -> AsyncGenerator[str, None]:
    snapshot = await build_portfolio_snapshot(db, current_prices)
    held = [p["ticker"] for p in snapshot["positions"]]
    messages = [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": CHAT_USER_PROMPT.format(
            held=", ".join(held) or "(leer)",
            snapshot=json.dumps(snapshot, ensure_ascii=False, default=str),
            question=question,
        )},
    ]
    executor = ToolExecutor(db=db, current_prices=current_prices)
    async for chunk in _run_agent_loop(messages, executor, show_tools=False):
        yield chunk


async def ask_stream(
    question: str,
    db: AsyncSession,
    current_prices: dict[str, float] | None = None,
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """Unified routing agent: ONE free-text question → the LLM picks the right tool(s) →
    visible tool-trace + a grounded German explanation. Routing is via native Ollama tool-calling
    (temperature 0 for reproducibility); the tools are deterministic/guarded (screen, NL-clamp, DS).

    ``history`` carries prior {role, content} turns (conversation memory) so a follow-up like
    "prüf News für CRNX" can refer back. Only the last few turns are kept (context/compute budget).
    """
    question = (question or "").strip()
    if not question:
        yield "_Keine Frage angegeben._\n"
        return
    logger.info("ask_stream: %r (history=%d)", question[:200], len(history or []))
    messages: list[dict] = [{"role": "system", "content": ROUTER_SYSTEM_PROMPT}]
    for m in (history or [])[-6:]:           # letzte ~3 Turns (user+assistant)
        role, content = m.get("role"), (m.get("content") or "")[:1500]
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question})
    executor = ToolExecutor(db=db, current_prices=current_prices or {})
    trace: list = []
    async for chunk in _run_agent_loop(messages, executor, show_tools=True, temperature=0, trace=trace):
        yield chunk
    # Final structured trace (tool calls + results) — the frontend captures it for the exportable log
    # and a collapsible trace view; it is NOT rendered into the visible answer.
    yield "␞TRACE␞" + json.dumps({"question": question, "trace": trace}, ensure_ascii=False, default=str)


async def news_summary_stream(ticker: str, db: AsyncSession) -> AsyncGenerator[str, None]:
    ticker = ticker.upper()
    news = await fetch_and_store_news(ticker, db, days=14)
    if not news:
        yield f"Keine aktuellen Nachrichten für {ticker} verfügbar."
        return

    pos = (await db.execute(select(Position).where(Position.ticker == ticker))).scalar_one_or_none()
    name = pos.name if pos else ticker
    headlines = "\n".join(f"- {n.headline}" for n in news[:15])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": NEWS_SUMMARY_PROMPT.format(ticker=ticker, name=name, headlines=headlines)},
    ]
    raw = await _fetch_ollama_response(messages)
    chunk_size = 120
    for i in range(0, len(raw), chunk_size):
        yield raw[i : i + chunk_size]


async def rebalance_stream(
    db: AsyncSession, current_prices: dict[str, float]
) -> AsyncGenerator[str, None]:
    snapshot = await build_portfolio_snapshot(db, current_prices)
    if not snapshot["positions"]:
        yield "Keine Positionen im Portfolio."
        return
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": REBALANCE_PROMPT.format(
            snapshot=json.dumps(snapshot, ensure_ascii=False, default=str),
        )},
    ]
    raw = await _fetch_ollama_response(messages)
    chunk_size = 120
    for i in range(0, len(raw), chunk_size):
        yield raw[i : i + chunk_size]


async def _fetch_ollama_response(
    messages: list[dict], stats: dict | None = None
) -> str:
    """Non-streaming Ollama /api/chat — full response text."""
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.3},
    }
    async with httpx.AsyncClient(timeout=180) as client:
        try:
            resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if stats is not None:
                stats.update(data)
            return data.get("message", {}).get("content", "")
        except Exception as e:
            return f"\n\n[Fehler bei Ollama-Anfrage: {e}]"


async def _stream_ollama_response(
    messages: list[dict], stats: dict | None = None
) -> AsyncGenerator[str, None]:
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": True,
        "think": False,
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
                        if stats is not None:
                            stats.update(data)
                        break
        except Exception as e:
            yield f"\n\n[Fehler beim Streaming: {e}]"
