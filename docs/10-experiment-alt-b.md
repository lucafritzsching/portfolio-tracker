# 10. Alt-B-Experiment: NL-Ziel-Agent (Freitext → Output)

> **Refactor-Hinweis (ADR-17):** Der NL-Ziel-Agent ist jetzt **sektor-agnostisch + beleggebunden**
> (Relevanz + Subjekt-Fokus + Pflicht-Zitate echter Schlagzeilen) — die unten beschriebene
> **Regex-Clamp/Biotech-Rubrik** ist abgelöst (Anti-Halluzination jetzt über Belegbindung). Die
> `fast`/`agentic`- und `think:false`-Befunde bleiben gültig. Aktuell: ADR-17 + Flowchart 8.

> Worum es bei Alt-B wirklich geht — und wie man die Ergebnisse liest. Ergänzt ADR-13/ADR-14
> ([07-entscheidungslog.md](07-entscheidungslog.md)) und das Agent-Design ([03-agent-design.md](03-agent-design.md)).

## Forschungsfrage

Wie gut übersetzt ein **lokales LLM** (Ollama, `qwen3:14b`) **Freitext** in **gute, belastbare Outputs** —
und wie stark halluziniert es dabei, verglichen mit einer rein deterministischen Berechnung? Das
Biotech-Screening war nur eine Engpass-Vermeidung; Gegenstand ist die **Freitext→Output-Qualität**.

## Versuchsaufbau: 3 Achsen (die Basis bleibt konstant)

| Achse | Variable | Alt-A | Alt-B |
|---|---|---|---|
| **A — Ziel-Typ** | was das Zusatzsignal ist | DS-Ziel („Bollinger > x"), von Hand backtestbar | **NL-Ziel** (konfigurierbares Freitext-Kriterium), LLM-beurteilt |
| **B — Rechen-Ort** | wer rechnet, ist es vertrauenswürdig | deterministisch | **`fast` (1 LLM-Call) vs. `agentic` (Tool-Loop)** |
| **C — Architektur** | jetzt vs. später | ein Agent | ein Agent jetzt; Multi-Agent (Orchestrator→Worker→Evaluator) als dokumentierte Zukunft |

Alt-A lebt im **KI-Chat**-Bereich, Alt-B in der eigenen **„Alt B"**-Sektion — gespiegelt, getrennte Routen.

## Wie das NL-Ziel funktioniert (`services/nl_target.py`)

```
Schlagzeilen einer Aktie
   │  Regex-Prefilter (event_strength): Relevanz + Negation + Materialität   → günstig, deterministisch
   ▼
überlebende, nicht-negative Schlagzeilen   +   Regex-Basis-Stärke (0–5)
   │  mode=fast: 1 gebündelter LLM-Aufruf        mode=agentic: Tool-Loop (inspect_headline)
   ▼
LLM-Urteil { matches, strength 1–5, evidence[], reason }
   │  CLAMP auf Regex-Basis ±1   (Anti-Halluzination)
   ▼
NLVerdict   →   in der „Alt B"-Sektion gestreamt (Urteil + Trace)
```

- **Kriterium ist ein Parameter** (Default „aktuelle Turnaround-Story"), NICHT hartcodiert.
- **LLM-Ausfall → Regex-Fallback** (kein Regress; die Demo überlebt ohne Ollama).
- **Cache** pro (Modus, Kriterium, Schlagzeilen) — günstig auf dem MacBook (LLM nur auf Survivor-News).

## Wie Halluzination gemessen wird

Jedes Urteil zeigt im **Trace**:
- **Regex-Basis** (deterministische Stärke 0–5) — die „Wahrheit" aus dem Code.
- **LLM-Rohstärke** (was das LLM wollte) **→ finale Stärke** (nach Clamp auf Basis ±1).

Die Divergenz zeigt, wie weit das LLM von der deterministischen Basis abweichen wollte; der Clamp verhindert
erfundene Katalysatoren. Damit ist „Agent vs. deterministisch" **und** „fast vs. agentic" pro Lauf ablesbar
(verwandt mit dem Evidence-/Faithfulness-Gate, ADR-11).

## Ausprobieren

```bash
docker-compose up -d postgres
ollama serve                     # einmalig: ollama pull qwen3:14b
cd backend && source .venv/bin/activate && uvicorn main:app --reload
cd frontend && npm run dev       # Menü „Alt B" → Ticker + Freitext-Kriterium + Modus
```
Endpoint direkt (SSE): `GET /api/agent/nl-target?ticker=AAPL&criterion=…&mode=fast|agentic`.
Tests: `cd backend && PYTHONPATH=. .venv/bin/pytest tests/ -q`.

## Gebaut vs. offen

- ✅ `nl_target` (fast + agentic, Clamp, Fallback, Cache), Decision-Trace (`services/trace.py`),
  „Alt B"-UI (`views/AltBView.vue`), SSE-Endpoint (`GET /api/agent/nl-target`).
- ⏳ Reddit/weitere NL-Quellen hinter `NLItem`; Multi-Agent (Achse C); Backtest als Wirksamkeitsnachweis.
  Eine Verdrahtung in den Biotech-Score (`score_alt_b`) bleibt bewusst aus — Freitext→Output ist das Ziel.
