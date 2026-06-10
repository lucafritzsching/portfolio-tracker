# 6. Setup & Betrieb

## Voraussetzungen

- **Docker** (für PostgreSQL; optional auch fürs Backend)
- **Ollama nativ auf dem Host** (NICHT in Docker – ein Container auf macOS ist CPU-only ohne
  Metal/GPU und für ein 14B-Modell zu langsam/ressourcenhungrig). Installation: https://ollama.com/download
- **Python 3.12** (falls das Backend lokal statt im Container läuft)
- **Node.js ≥ 20** (für das Frontend / Vite)
- **Apple Silicon, ≥ 16 GB RAM** empfohlen (für Qwen 2.5 14B)
- Ein **Finnhub-API-Key** (kostenlos auf finnhub.io)

## Umgebungsvariablen & Secrets

Alle Secrets liegen in **`backend/.env`** (gitignored – nicht committen!). Vorlage:
`backend/.env.example`.

```env
DATABASE_URL=postgresql+asyncpg://portfaio:portfaio@localhost:5432/portfaio
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b
FINNHUB_API_KEY=<dein-key>
NEWS_API_KEY=
```

- Der **Finnhub-Key ist bereits in `backend/.env` gesetzt** (vom Team eingetragen).
- `docker-compose.yml` lädt `backend/.env` als `env_file` und überschreibt nur `DATABASE_URL`
  (→ Service-Name `postgres`) und `OLLAMA_BASE_URL` (→ `host.docker.internal:11434`, also das
  host-native Ollama vom Backend-Container aus erreichbar).
- **Lokaler Lauf** (ohne Docker-Backend) nutzt die `localhost`-Werte aus `backend/.env` direkt.

## Start (empfohlen: PostgreSQL in Docker, Ollama nativ, App-Prozesse lokal)

```bash
# 1) PostgreSQL starten (Ollama läuft NATIV, nicht in Docker)
docker compose up -d postgres

# 2) Ollama nativ starten + Modell einmalig ziehen (~9 GB)
ollama serve                      # entfällt, falls Ollama schon als Hintergrund-App läuft
ollama pull qwen2.5:14b
#   Low-RAM-Alternative: ollama pull qwen2.5:7b  und in backend/.env OLLAMA_MODEL=qwen2.5:7b

# 3) Backend (falls nicht im Container) – aus backend/
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload         # http://localhost:8000  (Swagger: /docs)

# 4) Frontend – aus frontend/
npm install
npm run dev                       # http://localhost:5173
```

> `docker compose up` startet auch einen Backend-Container (Port 8000, Hot-Reload via Volume-Mount).
> Wer das Backend lieber lokal per `uvicorn` fährt, kann den `backend`-Service in der Compose-Datei
> weglassen/stoppen – Port 8000 darf nur einmal belegt sein.

## Erststart-Ablauf in der App

1. Browser auf http://localhost:5173 öffnen.
2. View **KI-Analyse** → Status-Banner prüfen: „Ollama-Agent: Bereit"? Falls „Modell fehlt" →
   „Modell laden" klicken (zieht das Modell, zeigt Fortschritt).
3. Eine **Position hinzufügen** (z. B. AAPL) – Ticker-Lookup holt den aktuellen Kurs.
4. **„Daten vorbereiten"** klicken → füllt Kurse/Fundamentaldaten/News-Cache für alle Positionen.
5. **„Analysieren"** → der Agent streamt: deterministische Bewertung → Tool-Aufrufe → Begründung.

## Verifikation (End-to-End-Checkliste)

| Schritt | Erwartung |
|---|---|
| `GET /api/agent/status` | `ollama_reachable: true`, `model_available: true` für `qwen2.5:14b` |
| Position anlegen | erscheint in DB-Tabelle `positions` |
| „Daten vorbereiten" | `price_history`, `fundamentals_cache`, `news_cache` gefüllt |
| Analyse starten | Stream: deterministischer Block, Tool-Calls (Backend-Logs), gestreamte Begründung |
| **Determinismus** | dieselbe Analyse 2× → identisches Signal/Score (LLM-Text darf variieren) |
| **Konsistenz** | Begründungstext widerspricht dem Signal nicht |
| Build | Backend `py_compile` ok, Frontend `npm run build` ok |

## Häufige Probleme

| Symptom | Ursache / Lösung |
|---|---|
| „Ollama nicht erreichbar" | Ollama nativ nicht gestartet (`ollama serve` / App), oder falscher `OLLAMA_BASE_URL` |
| „Modell fehlt" | `ollama pull qwen2.5:14b` ausführen oder Button „Modell laden" |
| Analyse bricht sofort ab | Agent-Endpunkte müssen **GET** sein (EventSource); CORS-Origin in `main.py` prüfen |
| Keine News | `FINNHUB_API_KEY` fehlt/ungültig in `backend/.env` |
| Kurse fehlen | yfinance temporär down → „Daten vorbereiten" nutzt Cache; später erneut versuchen |
| DB-Fehler nach Modelländerung | Es gibt kein Migrationswerkzeug; Docker-Volume `postgres_data` neu anlegen |

## Datenmigration aus dem Legacy-Prototyp (optional)

Der alte `index.html`-Prototyp speicherte in `localStorage`. Ein einmaliger Export kann via
`POST /api/portfolio/import` (JSON mit `positions`/`transactions`) importiert werden – nur in eine
leere Datenbank.
