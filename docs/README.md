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
| 1 | [01-vision-und-ziele.md](01-vision-und-ziele.md) | Use Case, Zielgruppe, Anforderungen, Demo-Kontext |
| 2 | [02-architektur.md](02-architektur.md) | Technologie-Stack, Gesamtbild, Entscheidungen + Trade-offs |
| 3 | [03-agent-design.md](03-agent-design.md) | **Der Hybrid-Agent** (4 Phasen), deterministisches Ensemble, Data Science |
| 4 | [04-backend.md](04-backend.md) | FastAPI-Struktur, Datenmodell, Services, Caching |
| 5 | [05-frontend.md](05-frontend.md) | Vue-3-Struktur, Pinia-Stores, Views, SSE-Streaming |
| 6 | [06-setup-und-betrieb.md](06-setup-und-betrieb.md) | Installation, Start, Umgebungsvariablen, API-Keys, Modell |
| 7 | [07-entscheidungslog.md](07-entscheidungslog.md) | Chronologische Architektur-Entscheidungen (ADRs) |
| 8 | [08-api-referenz.md](08-api-referenz.md) | Alle HTTP-Endpunkte |

## 30-Sekunden-Überblick

```
Browser (Vue 3 SPA)  ──HTTP/SSE──►  FastAPI Backend  ──►  PostgreSQL (Daten + Cache)
   localhost:5173                     localhost:8000        localhost:5432
                                          │
                                          ├──►  Ollama (Qwen 2.5 14B)   localhost:11434   (lokales LLM)
                                          ├──►  yfinance                (Kurse, Fundamentaldaten)
                                          └──►  Finnhub                 (Quotes, News)
```

**Wichtigstes Konzept:** Die Kauf-/Verkaufs-**Entscheidung ist deterministisch** und stammt aus einer
Data-Science-Pipeline (gewichtetes Ensemble). Das LLM **trifft die Entscheidung nicht**, sondern
*begründet* sie nachvollziehbar. Details in [03-agent-design.md](03-agent-design.md).

## Projektstand (Stand dieser Dokumentation)

- ✅ Backend (FastAPI) inkl. Portfolio-CRUD, Marktdaten-Services, Agent
- ✅ Hybrid-Agent: deterministisches Ensemble + LLM-Erklärung mit echtem Token-Streaming
- ✅ Frontend (Vue 3 + TypeScript), 5 Views, SSE-Anbindung
- ✅ Docker-Compose (PostgreSQL + Ollama + Backend)
- ⏳ Offen: End-to-End-Lauf auf dem Demo-Laptop (braucht Docker + Ollama + Modell-Pull),
  optionale Sample-/Demo-Daten beim Erststart

## Für KI-Agenten / Claude Code

Die Datei [`../CLAUDE.md`](../CLAUDE.md) im Repo-Root ist der maschinenlesbare Einstieg
(Start-Befehle, Struktur, Datenmodell). Diese `docs/` liefern die *Begründungen* und das *Warum*.
