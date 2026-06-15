"""Configurable natural-language target evaluator (Alt-B Schicht 2-4, ADR-13/ADR-14).

Given a stock's recent headlines and a free-text *criterion* (e.g. "aktuelle Turnaround-Story"),
decide whether the stock currently matches it. The criterion is a **parameter** — NOT hardcoded
to "turnaround" — so the same machinery can test how well a local LLM judges different NL targets.

Pipeline (cheap → expensive, so it stays MacBook-friendly):
  1. prefilter()       deterministic regex (reuse event_strength): drop irrelevant + negative
                       headlines, compute the regex strength baseline. Free.
  2. (LLM, Schicht 4)  one batched local-LLM judgment over the survivors → see evaluate_nl_target
                       in the LLM layer. Runs only on funnel survivors.
  3. combine_verdict() blend LLM significance with the regex baseline, CLAMPED so the LLM can
                       never invent a catalyst the deterministic prefilter rejected. Graceful
                       regex fallback when the LLM is unavailable (zero regression).

This module does the NL judgment only — it does not fetch data or score the strategy.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import httpx

from config import settings
from services.event_strength import classify_event, is_relevant

MIN_QUALIFY = 3        # strength >= 3 qualifies (mirrors event_strength qualifying threshold)
MAX_HEADLINES = 8      # cap headlines sent to the LLM (compute budget)
DEFAULT_CRITERION = "aktuelle Turnaround-Story"


@dataclass
class NLItem:
    text: str                  # headline (optionally headline + summary joined)
    source: str | None = None


@dataclass
class NLVerdict:
    matches: bool              # does the stock satisfy the criterion?
    strength: int              # 0..5 final significance (after clamp)
    reason: str                # short grounded rationale
    evidence: list[str] = field(default_factory=list)  # cited headlines (subset of inputs)
    source: str = "llm"        # llm | regex_fallback | no_signal
    regex_strength: int = 0    # deterministic baseline (for the Phase-6 hallucination metric)
    llm_strength: int | None = None  # raw LLM strength before clamp (None if no LLM ran)
    mode: str = "fast"         # fast | agentic — which evaluation path produced this verdict


def prefilter(items: list[NLItem], ticker: str = "", name: str = "") -> tuple[list[NLItem], int, list[str]]:
    """Deterministic regex prefilter.

    Returns (survivors, regex_strength, qualifying_headlines):
    - survivors: relevant, non-negative headlines to hand to the LLM (capped at MAX_HEADLINES)
    - regex_strength: max event strength among *qualifying* (>=3, positive, relevant) headlines
    - qualifying_headlines: the headlines behind that baseline
    """
    survivors: list[NLItem] = []
    qualifying_headlines: list[str] = []
    regex_strength = 0
    for it in items:
        text = (it.text or "").strip()
        if not text:
            continue
        if (ticker or name) and not is_relevant(text, "", ticker, name):
            continue
        ev = classify_event(text, "", it.source)
        if ev.direction == "negative":
            continue  # negatives never reach the LLM
        survivors.append(it)
        if ev.qualifies:
            regex_strength = max(regex_strength, ev.strength)
            qualifying_headlines.append(text)
    return survivors[:MAX_HEADLINES], regex_strength, qualifying_headlines


def combine_verdict(
    criterion: str,
    regex_strength: int,
    qualifying_headlines: list[str],
    survivor_texts: list[str],
    llm_result: dict | None,
) -> NLVerdict:
    """Blend the LLM judgment with the regex baseline (regex is the guardrail).

    ``llm_result`` is the parsed LLM dict {matches, strength, evidence:[idx], reason} or None.
    With None → deterministic regex fallback (matches == regex qualified). With a result →
    final strength is clamped to regex_strength ± 1 so the LLM can nudge but never fabricate a
    catalyst the prefilter rejected; ``matches`` additionally requires final strength >= MIN_QUALIFY.
    """
    if llm_result is None:
        return NLVerdict(
            matches=regex_strength >= MIN_QUALIFY,
            strength=regex_strength,
            reason="LLM nicht verfügbar – deterministischer Regex-Befund (Fallback).",
            evidence=qualifying_headlines[:3],
            source="regex_fallback",
            regex_strength=regex_strength,
            llm_strength=None,
        )

    try:
        raw = int(llm_result.get("strength") or 0)
    except (TypeError, ValueError):
        raw = 0
    low, high = max(0, regex_strength - 1), min(5, regex_strength + 1)
    final = max(low, min(high, raw))
    matches = bool(llm_result.get("matches")) and final >= MIN_QUALIFY

    ev_idx = llm_result.get("evidence") or []
    cited = [survivor_texts[i] for i in ev_idx
             if isinstance(i, int) and 0 <= i < len(survivor_texts)]
    reason = str(llm_result.get("reason") or "").strip()[:300]

    return NLVerdict(
        matches=matches,
        strength=final,
        reason=reason or f"LLM-Urteil zu „{criterion}“.",
        evidence=cited or qualifying_headlines[:3],
        source="llm",
        regex_strength=regex_strength,
        llm_strength=raw,
    )


# ── LLM layer (Schicht 4: one batched "fast" judgment) ───────────────────────────

_VERDICT_CACHE: dict[str, NLVerdict] = {}


def _format_prompt(criterion: str, items: list[NLItem]) -> str:
    numbered = "\n".join(f"{i}. {it.text}" for i, it in enumerate(items))
    return (
        "Du bewertest, ob eine Aktie aktuell ein bestimmtes Kriterium erfüllt — AUSSCHLIESSLICH "
        f"auf Basis der folgenden Schlagzeilen.\n\nKriterium: „{criterion}“\n\n"
        f"Schlagzeilen:\n{numbered}\n\n"
        "Antworte NUR mit JSON, ohne weiteren Text:\n"
        '{"matches": true|false, "strength": 1-5, "evidence": [Indizes], "reason": "kurze Begründung"}\n'
        "strength: 1 = unbedeutend/Routine, 3 = relevant, 5 = transformativ. "
        "evidence: nur Indizes der Schlagzeilen, die dein Urteil stützen. "
        "Erfinde nichts; stützen die Schlagzeilen das Kriterium nicht, dann matches=false."
    )


def _parse_llm_response(text: str | None) -> dict | None:
    """Extract the first JSON object from the model output; None if absent/invalid."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or "matches" not in obj:
        return None
    return obj


async def _call_ollama(criterion: str, items: list[NLItem]) -> dict | None:
    """One batched judgment via the local Ollama model (temperature 0). None on any failure."""
    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": _format_prompt(criterion, items)}],
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
            resp.raise_for_status()
            text = resp.json().get("message", {}).get("content", "")
    except Exception:
        return None
    return _parse_llm_response(text)


def _cache_key(criterion: str, items: list[NLItem], mode: str = "fast") -> str:
    blob = f"{mode}::{criterion}::" + "|".join(it.text for it in items)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ── Agentic mode (Schicht 4: the LLM "works through it" via a self-contained tool-loop) ──
#
# Deliberately self-contained — a small Ollama tool-loop living here, NOT the orchestrator's
# _run_agent_loop (which is SSE-streaming, DB-bound and returns free text). The single tool
# exposes the deterministic event classification per headline, so the agent can consult the
# regex signal while reasoning. The loop's final output is the same verdict JSON the fast path
# produces, so combine_verdict applies the identical clamp + regex fallback.

_AGENTIC_MAX_ITERS = 3

_NL_TOOLS = [{
    "type": "function",
    "function": {
        "name": "inspect_headline",
        "description": ("Liefert Volltext, Quelle und die deterministische Ereignis-Klassifikation "
                        "(Stärke 0-5, Richtung, Typ, Quellen-Deckelung) einer Schlagzeile per Index."),
        "parameters": {
            "type": "object",
            "properties": {"index": {"type": "integer", "description": "0-basierter Index der Schlagzeile"}},
            "required": ["index"],
        },
    },
}]


def _format_agentic_prompt(criterion: str, items: list[NLItem]) -> str:
    numbered = "\n".join(f"{i}. {it.text}" for i, it in enumerate(items))
    return (
        "Beurteile, ob eine Aktie aktuell das folgende Kriterium erfüllt — AUSSCHLIESSLICH auf Basis "
        f"dieser Schlagzeilen.\n\nKriterium: „{criterion}“\n\nSchlagzeilen:\n{numbered}\n\n"
        "Du KANNST das Tool inspect_headline(index) aufrufen, um Volltext, Quelle und die deterministische "
        "Ereignis-Klassifikation einer Schlagzeile zu prüfen (nutze es für starke/verdächtige Schlagzeilen). "
        "Wenn du genug weißt, antworte AUSSCHLIESSLICH mit JSON, ohne weiteren Text:\n"
        '{"matches": true|false, "strength": 1-5, "evidence": [Indizes], "reason": "kurze Begründung"}\n'
        "Erfinde nichts; stützen die Schlagzeilen das Kriterium nicht, dann matches=false."
    )


def _inspect_headline(index, survivors: list[NLItem]) -> str:
    """Tool body: full text/source + deterministic regex classification for headline `index`."""
    try:
        i = int(index)
    except (TypeError, ValueError):
        return "Ungültiger Index."
    if not 0 <= i < len(survivors):
        return f"Index {index} außerhalb des Bereichs (0..{len(survivors) - 1})."
    it = survivors[i]
    ev = classify_event(it.text, "", it.source)
    return json.dumps({
        "index": i, "text": it.text, "source": it.source,
        "regex_strength": ev.strength, "direction": ev.direction, "type": ev.type,
        "capped_by_source": ev.capped_by_source, "qualifies": ev.qualifies,
    }, ensure_ascii=False)


async def _chat_once(messages: list[dict], tools: list[dict]) -> dict:
    """One Ollama /api/chat turn (temperature 0); returns the raw message dict. Raises on HTTP error."""
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "tools": tools,
        "options": {"temperature": 0},
    }
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json().get("message", {}) or {}


async def _run_nl_tool_loop(criterion: str, survivors: list[NLItem], *, chat_fn=None) -> dict | None:
    """Multi-turn tool-loop: the LLM may inspect headlines, then emits the verdict JSON. None on failure."""
    fn = chat_fn or _chat_once
    messages = [{"role": "user", "content": _format_agentic_prompt(criterion, survivors)}]
    for i in range(_AGENTIC_MAX_ITERS):
        is_last = i == _AGENTIC_MAX_ITERS - 1
        try:
            message = await fn(messages, [] if is_last else _NL_TOOLS)
        except Exception:
            return None
        message = message or {}
        tool_calls = message.get("tool_calls") or []
        content = message.get("content", "") or ""

        if not tool_calls:
            parsed = _parse_llm_response(content)
            if parsed is not None:
                return parsed
            if is_last:
                return None
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": "Gib jetzt das finale Urteil als JSON aus."})
            continue

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for tc in tool_calls:
            fn_def = tc.get("function", {})
            args = fn_def.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if fn_def.get("name") == "inspect_headline":
                result = _inspect_headline(args.get("index"), survivors)
            else:
                result = f"Unbekanntes Tool: {fn_def.get('name')}"
            messages.append({"role": "tool", "content": result})
    return None


async def evaluate_nl_target(
    criterion: str,
    items: list[NLItem],
    ticker: str = "",
    name: str = "",
    *,
    mode: str = "fast",
    llm_fn=None,
    chat_fn=None,
    cache: dict | None = None,
) -> NLVerdict:
    """Full evaluation: prefilter → (cached) LLM judgment → bounded verdict.

    ``mode="fast"`` makes one batched LLM call; ``mode="agentic"`` runs a self-contained tool-loop
    where the LLM can inspect headlines before judging. Both paths funnel through combine_verdict, so
    the regex clamp + fallback are identical. Only relevant, non-negative headlines reach the LLM, and
    verdicts are cached per (mode, criterion, headlines) — so this stays cheap on a MacBook. ``llm_fn``
    (fast) and ``chat_fn`` (agentic) are injectable for tests; defaults hit the local Ollama. Only
    successful LLM verdicts are cached, so a transient outage never poisons the cache.
    """
    survivors, regex_strength, qualifying = prefilter(items, ticker, name)
    if not survivors:
        return NLVerdict(
            matches=False, strength=0,
            reason="Keine relevanten, nicht-negativen Schlagzeilen.",
            evidence=[], source="no_signal", regex_strength=0, llm_strength=None, mode=mode,
        )

    cache = _VERDICT_CACHE if cache is None else cache
    key = _cache_key(criterion, survivors, mode)
    if key in cache:
        return cache[key]

    if mode == "agentic":
        llm_result = await _run_nl_tool_loop(criterion, survivors, chat_fn=chat_fn)
    else:
        fn = llm_fn or _call_ollama
        try:
            llm_result = await fn(criterion, survivors)
        except Exception:
            llm_result = None

    verdict = combine_verdict(criterion, regex_strength, qualifying,
                              [it.text for it in survivors], llm_result)
    verdict.mode = mode
    if verdict.source == "llm":
        cache[key] = verdict
    return verdict
