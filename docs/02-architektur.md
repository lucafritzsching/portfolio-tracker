# 2. Architektur

## Gesamtbild

```
┌─────────────────────────┐         ┌──────────────────────────────────────┐
│  Frontend (Vue 3 SPA)   │         │  Backend (FastAPI, Python)            │
│  localhost:5173         │         │  localhost:8000                       │
│                         │  HTTP   │                                       │
│  - Pinia Stores         │◄───────►│  routers/   portfolio, quotes,        │
│  - 5 Views              │  + SSE  │             market_data, agent        │
│  - EventSource (Agent)  │         │  services/  market_data (fetch+cache) │
└─────────────────────────┘         │  agent/     pipeline, data_science,   │
                                     │             orchestrator, tools,      │
                                     │             sentiment, prompts        │
                                     └───────┬───────────────┬───────────────┘
                                             │               │
                         ┌───────────────────┘               └───────────────┐
                         ▼                                                     ▼
              ┌──────────────────────┐                          ┌──────────────────────────┐
              │  PostgreSQL          │                          │  Ollama (Qwen 2.5 14B)    │
              │  localhost:5432      │                          │  localhost:11434          │
              │  Portfolio + Cache   │                          │  lokales LLM (Tool-Use,   │
              └──────────────────────┘                          │  Streaming, Sentiment)    │
                                                                 └──────────────────────────┘
        externe Datenquellen:  yfinance (Kurse/Fundamentaldaten)  ·  Finnhub (Quotes/News)
```

Docker Compose startet **PostgreSQL + Ollama + Backend**. Das Frontend läuft per `npm run dev`
(Vite). Details in [06-setup-und-betrieb.md](06-setup-und-betrieb.md).

## Technologie-Stack & Begründung

| Schicht | Wahl | Warum diese Wahl |
|---|---|---|
| Frontend | **Vue 3 + TypeScript + Vite** | Reaktives Komponentenmodell, einfacher Einstieg, TS-Typsicherheit für das Datenmodell |
| State | **Pinia** | Offizieller Vue-Store, ersetzt globale Arrays sauber, TS-nativ |
| Backend | **Python + FastAPI** | Einzige sinnvolle Wahl für Data Science (pandas, scikit-learn, statsmodels, yfinance) + erstklassiges async/Streaming (SSE) |
| Datenbank | **PostgreSQL** | Persistente Daten + Cache für Kurszeitreihen/News; „production"-Optik fürs Uni-Projekt |
| LLM-Runtime | **Ollama** | Lokales Hosten von Open-Weight-Modellen über simple HTTP-API, Tool-Calling + Streaming |
| Modell | **Qwen 2.5 14B** | Gute Deutsch- und Reasoning-/Tool-Calling-Qualität; läuft auf 16 GB Apple Silicon (~9 GB q4). 7B als Low-RAM-Fallback |
| Deployment | **Docker Compose** | Ein Befehl startet Infrastruktur (DB + Ollama + Backend) reproduzierbar |

## Leitprinzipien

1. **Entscheidung deterministisch, Erklärung durch LLM.** Die Empfehlung kommt aus einer reinen
   Funktion (`compute_ensemble`), nicht aus dem LLM. Das LLM erklärt nur. → reproduzierbar & verteidigbar.
2. **Eine Datenquelle.** Aller Marktdaten-Abruf läuft über `services/market_data.py`. Router *und*
   Agent nutzen denselben Code und denselben Cache – keine Duplikate.
3. **Nicht-blockierendes I/O.** Alle blockierenden yfinance-Aufrufe laufen über `asyncio.to_thread`,
   damit der Event-Loop frei bleibt (sonst friert die ganze App während eines Abrufs ein).
4. **Cache-first für Robustheit.** Kurse/Fundamentaldaten/News werden in PostgreSQL gecacht; ein
   Warmup-Endpoint füllt den Cache vor der Demo.

## Daten- & Kontrollfluss (Beispiel: Einzelanalyse)

1. Frontend öffnet `EventSource` auf `GET /api/agent/analyze/{ticker}?current_prices=…`.
2. Backend öffnet eine **eigene DB-Session im Stream-Generator** (nicht via `Depends`, weil eine
   Request-Session beim Funktionsende geschlossen würde, bevor der Stream fertig ist).
3. **Phase 1+2 (deterministisch):** `pipeline.build_ensemble_decision` sammelt Daten (Services) und
   berechnet `EnsembleDecision`.
4. Der **deterministische Block** wird zuerst gestreamt (Signal, Konfidenz, Komponenten).
5. **Phase 3:** Tool-Calling-Loop (LLM ruft Tools auf, sichtbar in der UI).
6. **Phase 4:** Echte token-weise gestreamte Begründung des LLM.
7. Ergebnis wird als `AnalysisResult` persistiert.

Vollständige Beschreibung: [03-agent-design.md](03-agent-design.md).

## Bewusste Trade-offs (für die Verteidigung)

- **PostgreSQL ist für diese Datenmenge überdimensioniert.** Bewusst wegen Production-Optik gewählt;
  SQLite wäre schlanker. Da Docker ohnehin für Ollama läuft, ist der Zusatzaufwand gering.
- **Lokales 14B-Modell ist schwächer als Cloud-LLMs.** Bewusst wegen Lokalität/Datenschutz/Kosten;
  der **Hybrid-Ansatz** kompensiert, weil die Entscheidung nicht vom Modell abhängt.
- **ARIMA/Random Forest sind illustrative Modelle** (feste Ordnung bzw. Training pro Request auf einer
  Zeitreihe). Sie demonstrieren den DS-Prozess, sind aber kein Produktionssignal.
- **EventSource statt WebSocket/fetch-Streaming.** EventSource ist die einfachste SSE-Variante im
  Browser, kann aber nur **GET** – deshalb sind die Agent-Endpunkte GET (siehe ADR-04 in
  [07-entscheidungslog.md](07-entscheidungslog.md)).

## Verzeichnisstruktur (Top-Level)

```
portfolio-tracker/
├── backend/            FastAPI-App (siehe 04-backend.md)
├── frontend/           Vue-3-App (siehe 05-frontend.md)
├── docs/               diese Dokumentation
├── docker-compose.yml  PostgreSQL + Ollama + Backend
├── CLAUDE.md           maschinenlesbarer Einstieg für KI-Agenten
└── index.html          Legacy-Prototyp (nur noch Referenz)
```
