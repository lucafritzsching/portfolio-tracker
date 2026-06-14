# 6. Setup & Betrieb

## Voraussetzungen

- **Docker** (für PostgreSQL + Backend)
- **Ollama nativ installiert** (läuft auf dem Host, nicht im Container – nur so nutzt es
  die Metal-GPU; der Backend-Container erreicht es über `host.docker.internal`)
- **Node.js ≥ 20** (für das Frontend / Vite)
- **Apple Silicon, ≥ 16 GB RAM** empfohlen (für Qwen3 14B)
- Ein **Finnhub-API-Key** (kostenlos auf finnhub.io)

## Umgebungsvariablen & Secrets

Alle Secrets liegen in **`backend/.env`** (gitignored – nicht committen!). Vorlage:
`backend/.env.example`.

```env
DATABASE_URL=postgresql+asyncpg://portfaio:portfaio@localhost:5432/portfaio
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:14b
FINNHUB_API_KEY=<dein-key>
NEWS_API_KEY=
```

- Der **Finnhub-Key ist bereits in `backend/.env` gesetzt** (vom Team eingetragen).
- `docker-compose.yml` lädt `backend/.env` als `env_file` und überschreibt nur `DATABASE_URL`
  (Service-Name `postgres` im Compose-Netz) und `OLLAMA_BASE_URL`
  (`host.docker.internal` → natives Ollama auf dem Host).

## Start (PostgreSQL + Backend in Docker, Ollama nativ, Frontend lokal)

```bash
# 1) PostgreSQL + Backend starten
docker compose up -d
docker logs -f portfaio-backend   # Backend-Logs (uvicorn --reload, Python 3.12)

# 2) Modell einmalig ziehen (~9 GB) – nativ auf dem Host
ollama pull qwen3:14b
#   Low-RAM-Alternative: ollama pull qwen2.5:7b  und in backend/.env OLLAMA_MODEL=qwen2.5:7b

# 3) Frontend – aus frontend/
npm install
npm run dev                       # http://localhost:5173
```

> Das Backend läuft im Container `portfaio-backend` (Python 3.12). `./backend` ist nach `/app`
> gemountet und uvicorn läuft mit `--reload` – Codeänderungen greifen sofort, kein Rebuild nötig.
> Backend unter http://localhost:8000 (Swagger: /docs).

## Tests (lokales venv)

`backend/.venv` ist **Python 3.9** und dient ausschließlich den Unit-Tests – die App selbst
kann es nicht laden (PEP-604-Annotations wie `float | None` in `models.py` brauchen ≥ 3.10).

```bash
cd backend
source .venv/bin/activate
pytest tests/
```

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
| `GET /api/agent/status` | `ollama_reachable: true`, `model_available: true` für `qwen3:14b` |
| Position anlegen | erscheint in DB-Tabelle `positions` |
| „Daten vorbereiten" | `price_history`, `fundamentals_cache`, `news_cache` gefüllt |
| Analyse starten | Stream: deterministischer Block, Tool-Calls (Backend-Logs), gestreamte Begründung |
| **Determinismus** | dieselbe Analyse 2× → identisches Signal/Score (LLM-Text darf variieren) |
| **Konsistenz** | Begründungstext widerspricht dem Signal nicht |
| Build | Backend `py_compile` ok, Frontend `npm run build` ok |

## Häufige Probleme

| Symptom | Ursache / Lösung |
|---|---|
| „Ollama nicht erreichbar" | Natives Ollama läuft nicht (Ollama-App/`ollama serve` starten), oder falscher `OLLAMA_BASE_URL` |
| „Modell fehlt" | `ollama pull qwen3:14b` (nativ auf dem Host) oder Button „Modell laden" |
| Analyse bricht sofort ab | Agent-Endpunkte müssen **GET** sein (EventSource); CORS-Origin in `main.py` prüfen |
| Keine News | `FINNHUB_API_KEY` fehlt/ungültig in `backend/.env` |
| Kurse fehlen | yfinance temporär down → „Daten vorbereiten" nutzt Cache; später erneut versuchen |
| DB-Fehler nach Modelländerung | `init_db()` macht nur `create_all` und ändert bestehende Tabellen nie. Betroffene Tabelle droppen: `docker exec -it portfaio-postgres psql -U portfaio -d portfaio -c 'DROP TABLE …;'` – Backend-Neustart legt sie neu an |

## Datenmigration aus dem Legacy-Prototyp (optional)

Der alte `index.html`-Prototyp speicherte in `localStorage`. Ein einmaliger Export kann via
`POST /api/portfolio/import` (JSON mit `positions`/`transactions`) importiert werden – nur in eine
leere Datenbank.
