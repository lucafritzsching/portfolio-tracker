"""Probe: WARUM liefern `think:false` und `think:true` (qwen3) andere Ergebnisse?

Schickt den EXAKTEN Produktions-Prompt des NL-Agenten (`_format_prompt`, ein gebatchter Call über
mehrere Schlagzeilen) zweimal an das lokale qwen3 — Thinking AUS vs. AN — und erfasst pro Lauf:
Latenz, die von Ollama gelieferten Felder (`content` vs. separates `thinking`), ob `<think>` in den
Body leckt, das geparste Urteil-JSON und wie der Clamp es auflöst. Zwei Szenarien: ein klarer und ein
grenzwertiger Fall (dort würde eine Divergenz am ehesten sichtbar). Temperatur 0 → je Call deterministisch.

Lauf (Repo-Root):  .venv? -> backend/.venv/bin/python docs/evidence/think_mode_probe.py
                   bzw.  PYTHONPATH=backend python docs/evidence/think_mode_probe.py
Read-only ggü. der App. Befund: siehe think_mode_findings.md.
"""
import asyncio
import sys
import time
from pathlib import Path

# Maschinen-unabhängig: backend/ relativ zu dieser Datei auf den Pfad legen.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import httpx  # noqa: E402
from config import settings  # noqa: E402
from services.nl_target import (  # noqa: E402
    NLItem, _format_prompt, _parse_llm_response, combine_verdict, prefilter,
)

CRITERION = "aktuelle Turnaround-Story"

SCENARIOS = {
    "klar (starker Katalysator)": [
        NLItem("Acme Bio Announces Positive Phase 3 Topline Results, Meets Primary Endpoint", "GlobeNewswire"),
        NLItem("Acme Bio to Present at the Upcoming J.P. Morgan Healthcare Conference", "Business Wire"),
        NLItem("Acme Bio Reports Q3 Results: Revenue Up 28%, Narrows Net Loss", "GlobeNewswire"),
        NLItem("3 Beaten-Down Biotech Stocks That Could Double", "Motley Fool"),
    ],
    "grenzwertig (schwache/mehrdeutige Signale)": [
        NLItem("Acme Corp Reports Q3: Revenue Roughly Flat, Management Cites 'Early Signs of Stabilization'", "GlobeNewswire"),
        NLItem("Acme Corp Names New CFO Amid Ongoing Restructuring", "Business Wire"),
        NLItem("Analyst Upgrades Acme Corp to Hold, Citing Improving Cost Discipline", "Zacks"),
        NLItem("Acme Corp Secures $50M Credit Facility to Fund Turnaround Plan", "GlobeNewswire"),
    ],
}


async def call(items: list[NLItem], think: bool) -> dict:
    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": _format_prompt(CRITERION, items)}],
        "stream": False,
        "think": think,
        "options": {"temperature": 0},
    }
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=240) as client:
        resp = await client.post(f"{settings.ollama_base_url}/api/chat", json=payload)
        resp.raise_for_status()
        msg = resp.json().get("message", {}) or {}
    return {"dt": time.perf_counter() - t0, "msg": msg}


def report(label: str, out: dict, regex_strength: int, qualifying, survivor_texts):
    msg = out["msg"]
    content = msg.get("content", "") or ""
    thinking = msg.get("thinking", "") or ""
    parsed = _parse_llm_response(content)
    print(f"\n  {label}  ·  {out['dt']:.1f}s")
    print(f"    message keys   : {sorted(msg.keys())}")
    print(f"    thinking field : {len(thinking)} chars")
    print(f"    '<think>' body : {'<think>' in content}")
    print(f"    content        : {content[:200]!r}")
    if parsed is not None:
        v = combine_verdict(CRITERION, regex_strength, qualifying, survivor_texts, parsed)
        print(f"    -> verdict     : matches={v.matches} strength={v.strength} "
              f"(regex={v.regex_strength} llm_raw={v.llm_strength})")
    else:
        print("    -> verdict     : PARSE FAILED -> regex fallback")


async def main():
    for name, items in SCENARIOS.items():
        survivors, regex_strength, qualifying = prefilter(items)
        print(f"\n{'='*72}\nSzenario: {name}  (regex_strength={regex_strength})")
        texts = [it.text for it in items]
        for label, think in [("think=False", False), ("think=True", True)]:
            out = await call(items, think)
            report(label, out, regex_strength, qualifying, texts)


if __name__ == "__main__":
    asyncio.run(main())
