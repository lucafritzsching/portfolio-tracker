# 5. Frontend (Vue 3 + TypeScript)

> **Refactor-Hinweis (ADR-16):** Die getrennten Agenten-Views (KI-Analyse, Alt-B, Vergleich) sind zu
> **einem Chat-Fenster** zusammengeführt (`ChatView.vue`, „KI-Agent", ruft `GET /api/agent/ask`). Unten
> beschriebene Einzel-Views/Nav sind teils historischer Kontext.

## Struktur

```
frontend/src/
├── main.ts                 App-Bootstrap (Pinia; KEIN vue-router)
├── App.vue                 Layout + View-Switching (v-if über ui-Store)
├── types/index.ts          TS-Interfaces (Position, Transaction, SavingsPlan, Quote, …)
├── api/client.ts           Typed fetch-Wrapper + EventSource für den Agenten
├── stores/
│   ├── portfolio.ts        Pinia: Positionen, Sparpläne, Kennzahlen, Quotes
│   └── ui.ts               Pinia: aktive View, Modals, Sidebar
├── composables/
│   ├── useFormatters.ts    fmt(), fmtPct(), fmtCurrency(), fmtDate(), fmtLargeNumber()
│   ├── useSignal.ts        getSignal() (Verkaufen/Nachkaufen/Beobachten/Halten)
│   └── useMarkdown.ts      Markdown-Rendering für Agent-Output
├── components/
│   ├── AppHeader.vue        Topbar + Desktop-Navigation + Aktionen
│   ├── AppSidebar.vue       Mobile-Sidebar
│   ├── AddPositionModal.vue Position hinzufügen (mit Ticker-Lookup)
│   └── PortfolioCharts.vue  Chart.js Doughnuts (Allokation + Sektoren)
├── views/
│   ├── DashboardView.vue    Kennzahlen, Big-Mover-Alerts, Charts, Tabelle
│   ├── PositionsView.vue    Positionskarten, Transaktionshistorie, Transaktions-Modal
│   ├── SavingsView.vue      Sparpläne anlegen/ausführen
│   ├── NewsView.vue         News je Position (Finnhub) inkl. Sentiment
│   ├── AnalysisView.vue     KI-Analyse (SSE-Stream) — das Showcase
│   ├── ChatView.vue         KI-Chat (freie Fragen, Tool-Agent)
│   └── EvalView.vue         Agent-Metriken + Ensemble-Backtest
└── assets/main.css          Design-System (CSS Custom Properties, Light/Dark)
```

## Kein Router

Views werden **nicht** über vue-router umgeschaltet, sondern über `stores/ui.ts` (`activeView`) und
`v-if` in `App.vue`. `vue-router` und der Scaffold-Code wurden entfernt (siehe ADR-10). Das ist für
eine kleine Single-Window-App einfacher und genügt vollständig.

## State (`stores/portfolio.ts`)

Der zentrale Pinia-Store hält `positions` und `savingsPlans` und berechnet abgeleitete Werte als
`computed`:
- `stats` – `total_value`, `total_cost`, `day_pnl`, `total_pnl`, `total_ret`, `has_cost`.
- `currentPrices` – `{ ticker: current_price }`, wird an den Agenten übergeben.

Aktionen kapseln die API-Aufrufe: `loadPositions`, `refreshQuotes` (Batch-Quotes), `addPosition`,
`updatePosition`, `removePosition`, `addTransaction`, sowie die Sparplan-Aktionen. `enrichPosition`
ergänzt jede Position um `avg_buy_price`, `unrealized_pnl`, `unrealized_pnl_pct` aus den Transaktionen.

> Hinweis: Kennzahlen wie der durchschnittliche Kaufpreis werden client-seitig aus den Transaktionen
> berechnet (`enrichPosition`), während der Agent dieselbe Logik server-seitig in
> `pipeline.compute_portfolio_context` nutzt.

## API-Client (`api/client.ts`)

Dünner typisierter `fetch`-Wrapper gegen `http://localhost:8000/api`. Gruppen: `positions`,
`transactions`, `savingsPlans`, `quotes`, `marketData` (inkl. `warmup`), `agent`, `import`.

Die Agent-Analyse nutzt **`EventSource`** (SSE):
```ts
agent.analyzeStock(ticker, currentPrices): EventSource  // GET /api/agent/analyze/{ticker}?current_prices=…
agent.analyzePortfolio(currentPrices): EventSource       // GET /api/agent/analyze-portfolio?current_prices=…
```
`current_prices` wird als JSON-Query-Parameter übergeben (URL-encoded).

## SSE-Konsum (`views/AnalysisView.vue`)

- Öffnet `EventSource`, sammelt `onmessage`-Daten; `\n`-Escapes werden zu echten Zeilenumbrüchen.
- Endet bei `data: [DONE]` → schließt die Quelle (sonst würde EventSource automatisch neu verbinden
  und die ganze Analyse erneut starten!).
- `onerror` schließt ebenfalls und zeigt ggf. einen Verbindungsfehler.

### Darstellung der Analyse
Der Stream liefert zuerst den **deterministischen Block** (`## Deterministische Bewertung: …`), dann
den Marker `## Begründung des Agenten`. `splitAnalysis()` trennt beides und rendert **zwei Karten**:
1. „Deterministische Bewertung" (mit blauem Akzentrand) – Signal, Konfidenz, Komponenten.
2. „Begründung des Agenten" – sichtbare Tool-Aufrufe + gestreamte Begründung.

### Weitere Funktionen der View
- **Agent-Status-Banner:** zeigt, ob Ollama erreichbar ist und ob das Modell vorhanden ist; Button
  „Modell laden" (streamt den Pull-Fortschritt).
- **„Daten vorbereiten":** ruft `POST /api/market-data/warmup` (Vorab-Cache für die Demo).
- **Portfolio-Analyse** und **Einzelanalyse** je Position.

## Charts (`components/PortfolioCharts.vue`)

Chart.js wird per CDN in `index.html` geladen (`Chart` global). Zwei Doughnut-Charts (Allokation,
Sektoren), die bei Änderungen des Stores neu gerendert und vorher zerstört werden (kein Memory-Leak).

## Build & Typprüfung

```
npm run dev        # Vite Dev-Server (localhost:5173)
npm run build      # type-check (vue-tsc) + vite build
```
