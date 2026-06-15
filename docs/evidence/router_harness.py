"""Reproduzierbare Routing-Evidenz: leitet der eine Chat-Agent verschiedene Anfragetypen korrekt?

Schickt repräsentative Fragen (Statistik · NL/News · Strategie-Screen · gemischt) durch
``orchestrator.ask_stream`` gegen das echte qwen3 und protokolliert pro Frage, WELCHE Tools der Agent
aufgerufen hat (aus der sichtbaren Tool-Trace) + einen Auszug der Antwort. Plausibilitätsprüfung:
erwartetes Tool wurde verwendet. Read-only ggü. der App; braucht Postgres + Ollama.

Lauf (Repo-Root):  backend/.venv/bin/python docs/evidence/router_harness.py
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from database import AsyncSessionLocal          # noqa: E402
from agent.orchestrator import ask_stream        # noqa: E402

# (Frage, erwartetes Tool im Routing)
CASES = [
    ("Wie ist das ARIMA- und Random-Forest-Signal für AAPL?", "run_statistical_model"),
    ("Hat AAPL laut den aktuellen News zuletzt gute Nachrichten?", "judge_news"),
    ("Finde Nasdaq-Biotech-Aktien unter 15 Mrd. Market Cap mit über 20% Umsatzwachstum.", "screen_by_strategy"),
    ("Zeig mir die technischen Indikatoren (RSI, MACD) für MSFT.", "calculate_technical_indicators"),
]

TOOL_RE = re.compile(r"Führe Tool aus: \*\*(\w+)\*\*")


async def run_case(question: str) -> tuple[list[str], str]:
    out = ""
    async with AsyncSessionLocal() as db:
        async for chunk in ask_stream(question, db):
            out += chunk
    tools = TOOL_RE.findall(out)
    return tools, out


async def main():
    print("=" * 78)
    ok = 0
    for question, expected in CASES:
        tools, out = await run_case(question)
        used = expected in tools
        ok += used
        answer = out.split("…\n", 1)[-1].strip().replace("\n", " ")[:200]
        print(f"\nFRAGE: {question}")
        print(f"  Tools: {tools}  | erwartet: {expected}  -> {'OK' if used else 'ABWEICHUNG'}")
        print(f"  Antwort (Auszug): {answer}")
    print("\n" + "=" * 78)
    print(f"ERGEBNIS: {ok}/{len(CASES)} Anfragen korrekt geroutet.")


if __name__ == "__main__":
    asyncio.run(main())
