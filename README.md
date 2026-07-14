# PortfAIo — Lokale KI, die rechnet statt rät

Ein **lokaler Portfolio-Tracker mit einem routenden KI-Agenten**, der Analyse-, News- und
Strategiefragen beantwortet und den Markt screent — ohne zu halluzinieren. Entstanden im
Uni-Modul **Unternehmenssoftware** (GenAI-Projekt).

**Team:** Luca Fritzsching · Le Anh Minh Bui · Sandro Ngoga · Aliya Aktürk

## Was es kann

- **Depot verwalten:** Positionen, Transaktionen, Sparpläne, Live-Kurse und News.
- **Ein Chat-Fenster, ein Agent:** Eine Freitext-Frage → das LLM erkennt die Absicht und
  wählt das passende Werkzeug (sichtbare 🔧-Tool-Trace per SSE).
- **100 % lokal:** LLM (qwen3:14b) läuft nativ per Ollama — keine Cloud, keine KI-Kosten.

## Architektur

```
Browser (Vue 3 SPA)  ──HTTP/SSE──►  FastAPI Backend  ──►  PostgreSQL (Daten + Cache)
   localhost:5173                     localhost:8000        localhost:5432
                                          │
                                          ├──►  Ollama (qwen3:14b)   localhost:11434   (lokales LLM, nativ)
                                          ├──►  yfinance             (Kurse, Fundamentaldaten, Screens)
                                          └──►  Finnhub              (Quotes, News)
```

## Der Agent: LLM entscheidet den Weg, Code liefert die Zahlen

Der Orchestrator ([`backend/agent/orchestrator.py`](backend/agent/orchestrator.py), `ask_stream`)
führt eine Ollama-Tool-Schleife bei Temperatur 0. **Das LLM** erkennt die Absicht, wählt die
Werkzeuge und formuliert die belegte deutsche Antwort. **Deterministischer Code** liefert alle
Zahlen:

| Werkzeug | Aufgabe |
|---|---|
| `screen_by_strategy(mandate)` | Freitext-Mandat → yfinance-`EquityQuery`-Screen |
| `judge_news(ticker, criterion)` | Sektor-agnostisches NL-Urteil, beleggebunden + Clamp (±1 Stufe) |
| `discover_news_movers(direction)` | Ticker-freie News-Discovery: Mover-Screen → NL-Urteil je Kandidat |
| `run_backtest(ticker)` | Walk-Forward-Signal-Güte **vs. Buy&Hold-Baseline** |
| `run_statistical_model(ticker)` | ARIMA(2,1,2)-Prognose + RandomForest-Signal, ehrlich ausgewiesen |
| `calculate_technical_indicators` / Fundamentals / News | RSI, MACD, SMA, KGV, Schlagzeilen … |

**Ehrliche Data Science mit Baselines auf allen Ebenen:** RandomForest vs. Mehrheitsklasse
(purged Holdout, 20-Tage-Gap), ARIMA vs. Random Walk (MAE), Trading-Signale vs. Buy&Hold.
Befund offen ausgewiesen: kein verlässlicher Prognose-Vorteil — der Wert liegt im
disziplinierten, reproduzierbaren Prozess. Details:
[`docs/12-data-science-methodik.md`](docs/12-data-science-methodik.md).

## Schnellstart

```bash
# 1. PostgreSQL (Docker)
docker-compose up -d postgres

# 2. Ollama nativ (einmalig; im Container wäre 14B CPU-only und zu langsam)
ollama serve
ollama pull qwen3:14b

# 3. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # FINNHUB_API_KEY eintragen
uvicorn main:app --reload

# 4. Frontend
cd frontend
npm install
npm run dev                 # → http://localhost:5173
```

Details und Umgebungsvariablen: [`docs/06-setup-und-betrieb.md`](docs/06-setup-und-betrieb.md).

## Dokumentation

Die vollständige Doku (deutsch) liegt in [`docs/`](docs/README.md) — Vision, Architektur,
Agent-Design, Entscheidungslog (ADRs), DS-Methodik, Eval-Ergebnisse. Maschinenlesbarer
Einstieg für KI-Agenten: [`CLAUDE.md`](CLAUDE.md).

## Evaluation (Kurzfassung)

- **NL-Urteil:** 36 Läufe gegen qwen3:14b — Trefferquote 83 % (agentic 89 % / fast 78 %),
  **0 Halluzinationen**, 3 überzogene Urteile vom Clamp geblockt.
- **Modelle:** RF-Holdout ≈ 51 % vs. ≈ 50 % Mehrheitsklassen-Baseline; ARIMA-Intervalle breit,
  schlägt Random Walk oft nicht — bewusst so berichtet.
- **Trading:** Walk-Forward-Backtest je Signal vs. Buy&Hold, live im Chat via `run_backtest`.

## Branches

- `main` — aktueller, präsentierter Stand (unified Routing-Agent, inkl. `feature/alt-b-refactor`)
- `feature/strategy-alt-a` / `feature/strategy-alt-b` — historische Experiment-Stufen
- Tag `v2.0-baseline` — Stand der Zwischenpräsentation
