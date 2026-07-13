# PortfAIo – Dokumentation

PortfAIo ist ein **lokaler Portfolio-Tracker mit einem KI-Agenten**, der Aktien analysiert und
fundierte Kauf-/Halte-/Verkaufsempfehlungen ableitet. Das Projekt entsteht im Rahmen eines
Uni-Moduls (Unternehmenssoftware); das Kernstück und der Bewertungsfokus ist der **Ollama-Agent**,
der einen vollständigen Data-Science-Prozess durchläuft.

Diese Dokumentation richtet sich an **Teammitglieder und KI-Agenten** und erklärt *was* wir bauen,
*warum* wir es so bauen und *wie* es technisch umgesetzt ist.

## Lesereihenfolge

| # | Dokument | Inhalt |
|---|---|---|
| **0** | **[00-gesamtanalyse.md](00-gesamtanalyse.md)** | **Gesamtanalyse (Präsentations-Einstieg): Alt-A vs. Alt-B, Ergebnisse, Projektkarte** |
| 1 | [01-vision-und-ziele.md](01-vision-und-ziele.md) | Use Case, Zielgruppe, Anforderungen, Demo-Kontext |
| 2 | [02-architektur.md](02-architektur.md) | Technologie-Stack, Gesamtbild, Entscheidungen + Trade-offs |
| 3 | [03-agent-design.md](03-agent-design.md) | **Der Hybrid-Agent** (4 Phasen), deterministisches Ensemble, Data Science |
| 4 | [04-backend.md](04-backend.md) | FastAPI-Struktur, Datenmodell, Services, Caching |
| 5 | [05-frontend.md](05-frontend.md) | Vue-3-Struktur, Pinia-Stores, Views, SSE-Streaming |
| 6 | [06-setup-und-betrieb.md](06-setup-und-betrieb.md) | Installation, Start, Umgebungsvariablen, API-Keys, Modell |
| 7 | [07-entscheidungslog.md](07-entscheidungslog.md) | Chronologische Architektur-Entscheidungen (ADRs) |
| 8 | [08-api-referenz.md](08-api-referenz.md) | Alle HTTP-Endpunkte |
| 9 | **[09-release-v2.0-baseline.md](09-release-v2.0-baseline.md)** | **Release v2.0-baseline: Evidence-Gate, Eval, Chat, Branching, Changelog** |
| 10 | [10-experiment-alt-b.md](10-experiment-alt-b.md) | **Alt-B-Experiment**: NL-Ziel-Agent (Freitext→Output), 3 Achsen, fast/agentic, Halluzinations-Messung |
| 11 | [11-projekt-journey.md](11-projekt-journey.md) | **Projekt-Journey**: Prozess, Team-Aufteilung, Cross-Team-Entscheidungen, Zeitleiste, Lessons |
| 12 | [12-data-science-methodik.md](12-data-science-methodik.md) | **DS-Methodik**: ARIMA/RandomForest/Ensemble — Daten, Labels, Validierung, Grenzen (ehrlich) |

> **Aktueller Stand (Refactor, ADR-16/17):** Die Agenten-Funktionen sind zu **einem Chat-Fenster**
> zusammengeführt, das je nach Anfrage **routet** — Strategie-Screen, **sektor-agnostisches** News-/
> Klarsprache-Urteil (beleggebunden, **kein** Biotech-Tuning mehr) oder statistische Modelle (ehrlich
> ausgewiesen). Endpoint `GET /api/agent/ask`; Architektur in
> [refactor_flowcharts.md](refactor_flowcharts.md) (Flowchart 8) + [12-data-science-methodik.md](12-data-science-methodik.md).
> Frühere getrennte Oberflächen (KI-Analyse, Alt-B-Finder, Vergleich) sind entfernt; ältere Doku-Stellen,
> die sie/den Clamp beschreiben, sind historischer Kontext.

## 30-Sekunden-Überblick

```
Browser (Vue 3 SPA)  ──HTTP/SSE──►  FastAPI Backend  ──►  PostgreSQL (Daten + Cache)
   localhost:5173                     localhost:8000        localhost:5432
                                          │
                                          ├──►  Ollama (Qwen 3 14B)     localhost:11434   (lokales LLM)
                                          ├──►  yfinance                (Kurse, Fundamentaldaten)
                                          └──►  Finnhub                 (Quotes, News)
```

**Wichtigstes Konzept:** Die Kauf-/Verkaufs-**Entscheidung ist deterministisch** und stammt aus einer
Data-Science-Pipeline (gewichtetes Ensemble). Das LLM **trifft die Entscheidung nicht**, sondern
*begründet* sie nachvollziehbar. Details in [03-agent-design.md](03-agent-design.md).

## Projektstand (Stand v2.0-baseline)

- ✅ Backend (FastAPI) inkl. Portfolio-CRUD, Marktdaten-Services, Agent
- ✅ Hybrid-Agent: deterministisches Ensemble + **Evidence-gesicherte** LLM-Erklärung
- ✅ Frontend (Vue 3 + TypeScript), 7 Views (inkl. Chat + Eval), SSE-Anbindung
- ✅ Eval: Metriken (`AnalysisMetric`), Ensemble-Backtest, Faithfulness-Rate
- ✅ Anti-Halluzination: Evidence-Katalog + Satz-Gate ([09-release-v2.0-baseline.md](09-release-v2.0-baseline.md))
- ✅ Git: `main` + `develop` + `feature/strategy-alt-a` / `alt-b`
- ✅ Docker-Compose (PostgreSQL + optionales Backend; Ollama läuft nativ auf dem Host)
- ⏳ Strategie-Screener (Biotech/Bollinger vs. News-Narrativ) — in Feature-Branches
- ⏳ Evidence-Gate für Chat/Portfolio/Rebalance — geplant

**Neu in dieser Version?** → [09-release-v2.0-baseline.md](09-release-v2.0-baseline.md)

## Für KI-Agenten / Claude Code

Die Datei [`../CLAUDE.md`](../CLAUDE.md) im Repo-Root ist der maschinenlesbare Einstieg
(Start-Befehle, Struktur, Datenmodell). Diese `docs/` liefern die *Begründungen* und das *Warum*.
