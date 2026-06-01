"""LLM-based news sentiment scoring (one aggregate call per ticker).

Replaces the naive keyword counter for the decision input. Falls back to the
caller's keyword score when the LLM is unreachable or returns junk.
"""
from __future__ import annotations

import re

import httpx

from config import settings


async def score_sentiment_llm(headlines: list[str]) -> float | None:
    """Return an aggregate sentiment in [-1, 1] for the given headlines, or None on failure."""
    headlines = [h for h in headlines if h]
    if not headlines:
        return None

    joined = "\n".join(f"- {h}" for h in headlines[:12])
    prompt = (
        "Bewerte das Gesamt-Sentiment der folgenden Finanznachrichten-Schlagzeilen auf einer Skala "
        "von -1.0 (sehr negativ) bis +1.0 (sehr positiv). Antworte AUSSCHLIESSLICH mit einer einzelnen "
        f"Dezimalzahl zwischen -1 und 1, ohne weiteren Text.\n\n{joined}"
    )
    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": prompt}],
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

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return max(-1.0, min(1.0, float(match.group())))
