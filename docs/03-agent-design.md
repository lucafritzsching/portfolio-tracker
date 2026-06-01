# 3. Agent-Design (Kernstück)

> Dies ist das wichtigste Dokument. Es beschreibt, wie der KI-Agent zu seiner Empfehlung kommt
> und warum er so aufgebaut ist.

## Grundidee: Hybrid-Agent

Ein naiver „Agent" würde das LLM frei entscheiden lassen, welche Tools es aufruft, und es die
finale Kauf-/Verkaufsempfehlung formulieren lassen. Bei einem **lokalen 14B-Modell** ist das fragil:
Tools werden übersprungen, falsch parametrisiert, oder die Empfehlung widerspricht den berechneten
Zahlen. Für eine benotete Demo ist das riskant und **nicht reproduzierbar**.

Deshalb ist PortfAIo ein **Hybrid**:

> **Die Entscheidung ist deterministisch (Data-Science-Pipeline). Das LLM erklärt sie nur.**

Damit erhalten wir gleichzeitig:
- **Reproduzierbarkeit** – gleiche Daten ⇒ gleiche Empfehlung (verteidigbar vor dem Professor).
- **„Agenten"-Optik** – das LLM nutzt sichtbar Tools (Phase 3).
- **Nachvollziehbarkeit** – jede Empfehlung zeigt ihre gewichteten Komponenten.

## Die 4 Phasen

```
Phase 1  Deterministische Datensammlung           → agent/pipeline.py  (gather_market_data)
         Preise · Fundamentaldaten · News(+Sentiment)  → persistiert in PostgreSQL
                                  │
Phase 2  Deterministische Entscheidung (KEIN LLM)  → agent/data_science.py  (compute_ensemble)
         Technik + ARIMA + RandomForest + Fundamentaldaten + News + Portfolio-Regeln
         → gewichtetes Ensemble → BUY/HOLD/SELL + Konfidenz + Komponenten-Breakdown
                                  │
Phase 3  LLM-Pass MIT Tools (sichtbar)             → agent/orchestrator.py  (_run_agent_loop)
         LLM ruft Tools auf (live in der UI), erhält die EnsembleDecision im Kontext
                                  │
Phase 4  LLM erklärt die Entscheidung (Streaming)  → agent/orchestrator.py  (_stream_ollama_response)
         echtes Token-für-Token-Streaming der deutschen Begründung
```

Code-Einstieg: `agent/orchestrator.py → analyze_stock_stream()`.

## Phase 1 – Datensammlung (`agent/pipeline.py`)

`gather_market_data(ticker, db)` ruft die **gemeinsamen Services** ([04-backend.md](04-backend.md))
auf und persistiert in PostgreSQL:
- `fetch_and_store_prices` – 2 Jahre Tageskurse (yfinance), gecacht.
- `fetch_and_store_fundamentals` – KGV, Umsatzwachstum, Marktkap., EPS, Beta (yfinance), gecacht.
- `fetch_and_store_news` – Schlagzeilen (Finnhub), dedupliziert.

Anschließend wird das **News-Sentiment** bestimmt (siehe unten) und der **Portfolio-Kontext**
(`compute_portfolio_context`): durchschnittlicher Kaufpreis aus Transaktionen, unrealisierter P&L %,
Gewichtung über **alle** Positionen.

> Phase 1 schließt eine frühere Lücke: Das Tool `get_news` liest nur den Cache – ohne Phase 1
> hätte der Agent keine News gesehen.

## Phase 2 – Deterministisches Ensemble (`agent/data_science.py`)

`compute_ensemble(prices, fundamentals, news_sentiment, portfolio_ctx) -> EnsembleDecision`
ist eine **reine Funktion**: identische Eingaben liefern identische Ausgaben.

### Sub-Signale (jeweils auf [-1, +1] normiert)
| Komponente | Quelle | Mapping |
|---|---|---|
| `technical` | `calculate_technical_indicators` (RSI, MACD, Bollinger, SMA/EMA) → Trend BULLISH/NEUTRAL/BEARISH | +1 / 0 / −1 |
| `arima` | `run_arima_forecast` (ARIMA(2,1,2), 30-Tage-Prognose) | BUY/HOLD/SELL × Konfidenz |
| `random_forest` | `run_ml_signal` (RandomForest auf technischen Features) | BUY/HOLD/SELL × Konfidenz |
| `fundamentals` | `_fundamental_tilt` (Umsatzwachstum, KGV) | Tilt in [-1, 1] |
| `news` | News-Sentiment (LLM-Aggregat, sonst Keyword) | direkt [-1, 1] |

### Gewichtung & Schwellen (`ENSEMBLE_WEIGHTS`)
```
technical 0.30 | arima 0.20 | random_forest 0.25 | fundamentals 0.10 | news 0.15
score = Σ (gewicht × sub_signal)              # Bereich ca. [-1, +1]
Schwellen:  score > +0.25 → BUY   |   score < -0.25 → SELL   |   sonst → HOLD
```

### Portfolio-Regeln (additiver Tilt, gespiegelt aus `useSignal.ts`)
- Unrealisierte Rendite **> +20 %** → `score -= 0.15` (Gewinnmitnahme erwägen)
- Unrealisierte Rendite **< −12 %** → `score += 0.15` (Nachkauf-Chance prüfen)

### Konfidenz
Kombination aus **Score-Betrag** und **Übereinstimmung** der drei Modell-Signale (technical, arima,
random_forest). Hohe Konfidenz, wenn der Score deutlich ist *und* die Modelle einig sind.

### Ausgabe `EnsembleDecision`
```python
signal: "BUY" | "HOLD" | "SELL"
score: float            # gerundet, [-1, +1]
confidence: float       # [0, 1]
components: dict         # je Komponente: value, weight, contribution  (für Transparenz/UI)
rationale: list[str]     # menschenlesbare deutsche Stichpunkte
```

> **Determinismus-Hinweis:** Das News-Sentiment kann minimal schwanken (LLM, Temperatur 0). Die
> übrige Pipeline ist exakt deterministisch. In der Demo lässt sich Determinismus am stabilsten
> zeigen, wenn der Cache via Warmup gefüllt ist (gleiche Eingangsdaten).

## Phase 3 – Tool-Calling (`agent/orchestrator.py → _run_agent_loop`)

Das LLM bekommt die Tool-Definitionen (`agent/tools.py`) und die bereits berechnete
`EnsembleDecision` im Prompt. Es untersucht die Lage über Tools; jeder Aufruf wird als
`> Führe Tool aus: <name>(...)` in den Stream geschrieben und in der UI sichtbar.

**Verfügbare Tools** (`agent/tools.py`, `ToolExecutor`):
`get_historical_prices`, `calculate_technical_indicators`, `get_fundamentals`, `get_news`,
`run_statistical_model`, `get_portfolio_context`.

Der Loop läuft max. `MAX_TOOL_ITERATIONS = 8`. Nicht-streamende Aufrufe dienen der Tool-Erkennung;
sobald keine Tool-Calls mehr kommen, folgt Phase 4.

## Phase 4 – Erklärung mit echtem Streaming (`_stream_ollama_response`)

Die finale Begründung wird **echt token-weise** von Ollama gestreamt (`stream: true`, via
`httpx.AsyncClient.stream`, JSON-Zeilen). Der Prompt (`EXPLAIN_STOCK_PROMPT` in `agent/prompts.py`)
weist das LLM an, **das vorgegebene Signal zu begründen, nicht zu überstimmen**; Vorbehalte sind als
Risiken zu formulieren. Struktur der Antwort: Begründung → Wichtigste Treiber → Risiken → Fazit.

## News-Sentiment (`agent/sentiment.py`)

`score_sentiment_llm(headlines)` schickt **einen** aggregierten Prompt an Ollama (Temperatur 0) und
parst eine Zahl in [-1, 1]. Schlägt das fehl, greift der **Keyword-Fallback**
(`services/market_data.keyword_sentiment`). So fließt eine bessere Sentiment-Einschätzung in das
Ensemble, ohne schwere Zusatz-Abhängigkeit (kein FinBERT/torch).

## Portfolio-weite Analyse

`analyze_portfolio_stream` berechnet je Position eine `EnsembleDecision`, streamt die Liste und lässt
das LLM anschließend eine Gesamteinschätzung (Diversifikation, auffällige Positionen,
DEFENSIV/AUSGEWOGEN/OFFENSIV) formulieren – ohne Tool-Loop, direkt gestreamt.

## Warum diese Modelle (ehrliche Einordnung)

- **ARIMA(2,1,2):** klassisches Zeitreihenmodell, feste Ordnung → einfach erklärbar, demonstriert
  „statistische Prognose". Keine Modellselektion (bewusst, didaktisch).
- **Random Forest:** trainiert pro Request auf den technischen Features einer Zeitreihe →
  demonstriert „ML-Klassifikation Buy/Hold/Sell". Kleine Datenbasis, daher illustrativ.
- Beide werden **gewichtet zusammengeführt**, statt sich auf ein einzelnes Modell zu verlassen.

Siehe auch die Grenzen in [01-vision-und-ziele.md](01-vision-und-ziele.md#abgrenzung-was-portfaio-nicht-ist).
