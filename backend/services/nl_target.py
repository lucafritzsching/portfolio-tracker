"""Configurable natural-language judge — sector-agnostic, evidence-grounded (Alt-B / ADR-17).

Given a stock's recent headlines and ANY free-text *criterion* (e.g. „aktuelle Turnaround-Story",
„zuletzt gute News", „Übernahme-Fantasie", „Margendruck"), decide whether the stock currently matches
it. The criterion is a **parameter** and NOTHING here is tuned to a sector or outcome.

Design (deliberately simple + general):
  1. prefilter()    light relevance only (mentions the ticker/name) — no catalyst rubric, no
                    direction/negation rules. The criterion alone decides what counts. Free.
  2. (LLM)          the model judges the criterion against the surviving headlines and MUST cite the
                    headline indices that support its verdict (fast = 1 call; agentic = tool-loop).
  3. build_verdict() **anti-hallucination via grounding**: cited evidence must map to REAL headlines;
                    a positive match requires >= 1 valid cited headline AND significance >= MIN_QUALIFY.
                    No clamp to a hand-built rubric — the guard is "you cannot cite a headline that
                    does not exist". If the LLM is unavailable we return an honest "no judgment".

Earlier versions clamped the LLM to a biotech event-strength rubric (`event_strength`); that biased the
judge toward clinical catalysts and silenced non-biotech news. Replaced by relevance + grounding.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import httpx

from config import settings
from services.event_strength import is_relevant

MIN_QUALIFY = 3        # significance >= 3 (on the LLM's 0..5 scale) qualifies as a real match
MAX_HEADLINES = 8      # cap headlines sent to the LLM (compute budget)
DEFAULT_CRITERION = "aktuelle Turnaround-Story"


@dataclass
class NLItem:
    text: str                  # headline (optionally headline + summary joined)
    source: str | None = None


@dataclass
class NLVerdict:
    matches: bool              # does the stock satisfy the criterion?
    strength: int              # 0..5 significance (the LLM's, validated to range)
    reason: str                # short grounded rationale
    evidence: list[str] = field(default_factory=list)  # cited headlines that REALLY exist (subset of inputs)
    source: str = "llm"        # llm | no_signal | no_llm
    llm_strength: int | None = None  # raw LLM strength (kept for trace/eval; == strength after range clamp)
    mode: str = "fast"         # fast | agentic — which evaluation path produced this verdict


def prefilter(items: list[NLItem], ticker: str = "", name: str = "") -> list[NLItem]:
    """Light, sector-agnostic relevance filter. Returns the headlines handed to the LLM (capped).

    Only drops empty text and — IF a ticker/name is given — headlines that don't mention the company.
    No catalyst rubric and no direction/negation rules: the free-text criterion alone decides relevance.
    (Callers that pass already ticker-scoped news pass ticker="" to skip the mention check.)
    """
    survivors: list[NLItem] = []
    for it in items:
        text = (it.text or "").strip()
        if not text:
            continue
        if (ticker or name) and not is_relevant(text, "", ticker, name):
            continue
        survivors.append(it)
    return survivors[:MAX_HEADLINES]


def build_verdict(
    criterion: str,
    survivor_texts: list[str],
    llm_result: dict | None,
    *,
    mode: str = "fast",
) -> NLVerdict:
    """Turn the LLM's parsed result into a grounded verdict (no rubric clamp).

    ``llm_result`` is {matches, strength, evidence:[idx], reason} or None. Anti-hallucination = the cited
    evidence indices must point to REAL headlines; a positive match additionally requires significance
    >= MIN_QUALIFY and at least one valid cited headline. None → honest "LLM unavailable".
    """
    if llm_result is None:
        return NLVerdict(
            matches=False, strength=0,
            reason="LLM nicht verfügbar — keine Beurteilung möglich.",
            evidence=[], source="no_llm", llm_strength=None, mode=mode,
        )

    try:
        raw = int(llm_result.get("strength") or 0)
    except (TypeError, ValueError):
        raw = 0
    strength = max(0, min(5, raw))

    ev_idx = llm_result.get("evidence") or []
    cited = [survivor_texts[i] for i in ev_idx
             if isinstance(i, int) and 0 <= i < len(survivor_texts)]
    reason = str(llm_result.get("reason") or "").strip()[:300]

    # Grounding: claim only counts if it is backed by a real cited headline and is significant enough.
    matches = bool(llm_result.get("matches")) and strength >= MIN_QUALIFY and len(cited) >= 1

    return NLVerdict(
        matches=matches,
        strength=strength,
        reason=reason or f"LLM-Urteil zu: {criterion}",
        evidence=cited,
        source="llm",
        llm_strength=raw,
        mode=mode,
    )


# ── LLM layer (fast: one batched judgment) ───────────────────────────────────────

_VERDICT_CACHE: dict[str, NLVerdict] = {}


def _focus_line(subject: str) -> str:
    if not subject:
        return ""
    return (f"Es geht um {subject}. Beziehe dich AUSSCHLIESSLICH auf dieses Unternehmen; ignoriere "
            "Schlagzeilen, in denen es nur beiläufig oder als reiner Vergleich vorkommt.\n\n")


def _format_prompt(criterion: str, items: list[NLItem], subject: str = "") -> str:
    numbered = "\n".join(f"{i}. {it.text}" for i, it in enumerate(items))
    return (
        "Du bewertest, ob eine Aktie aktuell ein bestimmtes Kriterium erfüllt — AUSSCHLIESSLICH "
        f"auf Basis der folgenden Schlagzeilen.\n\n{_focus_line(subject)}Kriterium: {criterion}\n\n"
        f"Schlagzeilen:\n{numbered}\n\n"
        "Antworte NUR mit JSON, ohne weiteren Text:\n"
        '{"matches": true|false, "strength": 1-5, "evidence": [Indizes], "reason": "kurze Begründung"}\n'
        "strength: 1 = unbedeutend/Routine, 3 = relevant, 5 = sehr stark. "
        "evidence: NUR Indizes der Schlagzeilen, die dein Urteil konkret stützen (Pflicht bei matches=true). "
        "Erfinde nichts und zitiere keine Schlagzeile, die nicht in der Liste steht; stützen die "
        "Schlagzeilen das Kriterium nicht, dann matches=false."
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


async def _call_ollama(criterion: str, items: list[NLItem], subject: str = "") -> dict | None:
    """One batched judgment via the local Ollama model (temperature 0). None on any failure."""
    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": _format_prompt(criterion, items, subject)}],
        "stream": False,
        "think": False,  # disables qwen3 "thinking" → faster + stable JSON (see think_mode_findings.md)
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


# ── Agentic mode (the LLM "works through it" via a self-contained tool-loop) ──────
#
# Deliberately self-contained. The single tool returns a headline's full text + source by index, so the
# model can re-read a headline before judging. The loop's final output is the same verdict JSON the fast
# path produces, so build_verdict applies the identical grounding check.

_AGENTIC_MAX_ITERS = 3

_NL_TOOLS = [{
    "type": "function",
    "function": {
        "name": "inspect_headline",
        "description": "Liefert Volltext und Quelle einer Schlagzeile per Index (zum genauen Nachlesen).",
        "parameters": {
            "type": "object",
            "properties": {"index": {"type": "integer", "description": "0-basierter Index der Schlagzeile"}},
            "required": ["index"],
        },
    },
}]


def _format_agentic_prompt(criterion: str, items: list[NLItem], subject: str = "") -> str:
    numbered = "\n".join(f"{i}. {it.text}" for i, it in enumerate(items))
    return (
        "Beurteile, ob eine Aktie aktuell das folgende Kriterium erfüllt — AUSSCHLIESSLICH auf Basis "
        f"dieser Schlagzeilen.\n\n{_focus_line(subject)}Kriterium: {criterion}\n\nSchlagzeilen:\n{numbered}\n\n"
        "Du KANNST das Tool inspect_headline(index) aufrufen, um Volltext und Quelle einer Schlagzeile "
        "genau nachzulesen. Wenn du genug weißt, antworte AUSSCHLIESSLICH mit JSON, ohne weiteren Text:\n"
        '{"matches": true|false, "strength": 1-5, "evidence": [Indizes], "reason": "kurze Begründung"}\n'
        "evidence sind PFLICHT bei matches=true und müssen auf existierende Schlagzeilen zeigen. "
        "Erfinde nichts; stützen die Schlagzeilen das Kriterium nicht, dann matches=false."
    )


def _inspect_headline(index, survivors: list[NLItem]) -> str:
    """Tool body: full text + source for headline `index` (sector-agnostic — no rubric)."""
    try:
        i = int(index)
    except (TypeError, ValueError):
        return "Ungültiger Index."
    if not 0 <= i < len(survivors):
        return f"Index {index} außerhalb des Bereichs (0..{len(survivors) - 1})."
    it = survivors[i]
    return json.dumps({"index": i, "text": it.text, "source": it.source}, ensure_ascii=False)


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


async def _run_nl_tool_loop(criterion: str, survivors: list[NLItem], *, subject: str = "", chat_fn=None) -> dict | None:
    """Multi-turn tool-loop: the LLM may inspect headlines, then emits the verdict JSON. None on failure."""
    fn = chat_fn or _chat_once
    messages = [{"role": "user", "content": _format_agentic_prompt(criterion, survivors, subject)}]
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
    """Full evaluation: relevance prefilter → (cached) LLM judgment → grounded verdict.

    ``mode="fast"`` makes one batched LLM call; ``mode="agentic"`` runs a self-contained tool-loop where
    the LLM can re-read headlines before judging. Both funnel through build_verdict, so the grounding
    check (cited evidence must be real) is identical. Verdicts are cached per (mode, criterion, headlines).
    ``llm_fn`` (fast) and ``chat_fn`` (agentic) are injectable for tests; defaults hit the local Ollama.
    """
    survivors = prefilter(items, ticker, name)
    if not survivors:
        return NLVerdict(
            matches=False, strength=0,
            reason="Keine relevanten Schlagzeilen.",
            evidence=[], source="no_signal", llm_strength=None, mode=mode,
        )

    cache = _VERDICT_CACHE if cache is None else cache
    key = _cache_key(criterion, survivors, mode)
    if key in cache:
        return cache[key]

    subject = (f"{name} ({ticker})" if name else ticker).strip()
    if mode == "agentic":
        llm_result = await _run_nl_tool_loop(criterion, survivors, subject=subject, chat_fn=chat_fn)
    elif llm_fn is not None:        # injected (tests): keep the (criterion, items) signature
        try:
            llm_result = await llm_fn(criterion, survivors)
        except Exception:
            llm_result = None
    else:
        try:
            llm_result = await _call_ollama(criterion, survivors, subject=subject)
        except Exception:
            llm_result = None

    verdict = build_verdict(criterion, [it.text for it in survivors], llm_result, mode=mode)
    if verdict.source == "llm":
        cache[key] = verdict
    return verdict
