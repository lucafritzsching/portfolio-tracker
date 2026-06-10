"""LLM-Ereignis-Klassifikation für den Alt-B-Screener (Schicht 2).

Das lokale LLM (Ollama) bestimmt nur den *Typ* eines Events aus der festen Rubrik in
`event_strength.EVENT_RUBRIC` plus eine kurze deutsche Story; die *Stärke-Skala* bleibt
deterministisch im Code. Guardrails:

  * `event_type` muss exakt in der Rubrik liegen, sonst Fallback.
  * `evidence_quote` muss wörtlich im Quelltext vorkommen (Anti-Halluzination).
  * Jeder Fehler (Ollama down, kaputtes JSON, Validierung) -> Regex-Fallback
    `classify_event()`. Der Scan bricht nie wegen des LLM ab.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from config import settings
from services.event_strength import (
    EVENT_RUBRIC,
    MIN_QUALIFYING_STRENGTH,
    NO_CATALYST_TYPE,
    EventClassification,
    classify_event,
)

_MAX_TEXT_CHARS = 4000

_SYSTEM_PROMPT = (
    "Du klassifizierst Nachrichten zu NASDAQ-Biotech-Unternehmen. "
    "Antworte ausschließlich mit einem JSON-Objekt, ohne weiteren Text."
)

_USER_PROMPT = """Klassifiziere das wichtigste Unternehmens-Ereignis im folgenden Text zu {company}.

TEXT:
{text}

Antworte als JSON mit genau diesen Feldern:
{{
  "event_type": <einer dieser Typen, wörtlich: {types}>,
  "direction": "positive" | "neutral" | "negative",
  "story_de": <1-2 deutsche Sätze: Was ist passiert und warum ist es eine Turnaround-Story (oder warum nicht)?>,
  "evidence_quote": <kurzes wörtliches Zitat aus dem TEXT, das das Ereignis belegt>
}}

Regeln:
- "direction" ist "negative", wenn das Ereignis ein Rückschlag ist (z. B. gescheiterte Studie, Ablehnung, Verzögerung, Klage).
- Wenn kein konkretes Unternehmens-Ereignis vorliegt, nimm "{no_catalyst}".
- "evidence_quote" muss exakt so im TEXT stehen."""


@dataclass(frozen=True)
class LLMEvent:
    classification: EventClassification
    story_de: str
    evidence_quote: str
    used_llm: bool


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def validate_llm_payload(payload: dict, source_text: str) -> tuple[str, str, str, str] | None:
    """(event_type, direction, story_de, quote) oder None, wenn die Antwort nicht belastbar ist."""
    event_type = str(payload.get("event_type") or "")
    direction = str(payload.get("direction") or "")
    story = str(payload.get("story_de") or "").strip()
    quote = str(payload.get("evidence_quote") or "").strip()

    if event_type != NO_CATALYST_TYPE and event_type not in EVENT_RUBRIC:
        return None
    if direction not in ("positive", "neutral", "negative"):
        return None
    if event_type != NO_CATALYST_TYPE:
        if not quote or _normalize(quote) not in _normalize(source_text):
            return None
    return event_type, direction, story, quote


def rubric_classification(event_type: str, llm_direction: str) -> EventClassification:
    """Deterministisches Mapping: LLM-Typ -> Stärke/Richtung aus der Rubrik.

    Sagt das LLM "negative", zählt das Event nie — egal welcher Typ.
    """
    if event_type == NO_CATALYST_TYPE or event_type not in EVENT_RUBRIC:
        return EventClassification(0, NO_CATALYST_TYPE, "none", False, False)
    if llm_direction == "negative":
        return EventClassification(0, event_type, "negative", False, False)
    strength, direction = EVENT_RUBRIC[event_type]
    return EventClassification(
        strength=strength,
        type=event_type,
        direction=direction,
        capped_by_source=False,
        qualifies=direction == "positive" and strength >= MIN_QUALIFYING_STRENGTH,
    )


async def _ollama_chat(messages: list[dict]) -> str:
    """Roher Ollama-Call (JSON-Modus). Getrennt gehalten, damit Tests ihn ersetzen können."""
    payload = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")


async def classify_event_llm(text: str, ticker: str = "", name: str = "") -> LLMEvent:
    """Event-Typ + Story per LLM, Stärke deterministisch. Fällt auf Regex zurück."""
    text = (text or "").strip()[:_MAX_TEXT_CHARS]
    if not text:
        return LLMEvent(classify_event(""), "", "", used_llm=False)

    company = f"{name} ({ticker})".strip() or ticker or "dem Unternehmen"
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _USER_PROMPT.format(
            company=company,
            text=text,
            types=", ".join(f'"{t}"' for t in [*EVENT_RUBRIC, NO_CATALYST_TYPE]),
            no_catalyst=NO_CATALYST_TYPE,
        )},
    ]
    try:
        raw = await _ollama_chat(messages)
        validated = validate_llm_payload(json.loads(raw), text)
    except Exception:
        validated = None

    if validated is None:
        return LLMEvent(classify_event(text), "", "", used_llm=False)

    event_type, direction, story, quote = validated
    return LLMEvent(rubric_classification(event_type, direction), story, quote, used_llm=True)
