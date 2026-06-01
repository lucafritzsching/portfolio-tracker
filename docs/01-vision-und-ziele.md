# 1. Vision & Ziele

## Worum geht es?

PortfAIo ist ein **persönlicher Portfolio-Tracker**, der reale Marktdaten mit einem **lokal laufenden
KI-Agenten** verbindet. Der Agent analysiert einzelne Aktien und das Gesamtportfolio und leitet
**begründete Kauf-/Halte-/Verkaufsempfehlungen** ab.

Der Tracker selbst (Positionen, Transaktionen, Sparpläne, Kennzahlen, Charts) ist solide, aber
bewusst der *Rahmen*. Das **Herzstück und der Bewertungsfokus** ist der Agent: Er soll einen
nachvollziehbaren, vollständigen **Data-Science-Prozess** durchlaufen – von der Datensammlung über
Feature-Engineering und Modellierung bis zur Empfehlung.

## Warum lokal?

- **Datenschutz & Kosten:** Keine Cloud-LLM-Gebühren, keine Daten verlassen den Rechner.
- **Lehrkontext:** Der Agent soll *zeigbar* und *erklärbar* sein, nicht eine Blackbox-Cloud-API.
- **Ollama** macht es einfach, ein leistungsfähiges Open-Weight-Modell (Qwen 2.5 14B) lokal über
  eine HTTP-API anzusprechen.

## Zielgruppe der Anwendung

Eine einzelne Person (Privatanleger) auf dem eigenen Laptop. Kein Multi-User, keine Authentifizierung,
keine öffentliche Bereitstellung. Das vereinfacht viele Entscheidungen (siehe Trade-offs in
[02-architektur.md](02-architektur.md)).

## Demo-Kontext (wichtig für Designentscheidungen)

- Die Anwendung wird **in Person auf einem Laptop** vorgeführt (Apple Silicon, ≥16 GB RAM).
- Während der Demo ist **Internet vorhanden** – Live-Abruf von Kursen/News ist möglich, aber
  yfinance kann gelegentlich ausfallen, daher gibt es einen **Vorab-Cache** (Warmup).
- Der Professor erwartet einen **„Agenten"** – konkret einen **Hybrid** aus sichtbarer
  Tool-Nutzung *und* einer belastbaren, reproduzierbaren Entscheidung.

## Anforderungen

### Funktional
- Portfolio verwalten: Positionen, Käufe/Verkäufe (Transaktionen mit realisiertem P&L), Sparpläne.
- Kennzahlen & Visualisierung: Portfoliowert, Tages-P&L, Rendite, Allokations- und Sektor-Charts.
- Live-Kurse (Finnhub) und historische Kurse/Fundamentaldaten (yfinance).
- News je Position inkl. Sentiment.
- **KI-Analyse je Aktie und fürs Gesamtportfolio**, im Browser als Live-Stream sichtbar.

### Nicht-funktional / Qualitätsziele
- **Reproduzierbarkeit:** Dieselben Eingaben → dieselbe Empfehlung. (Entscheidend für die
  akademische Verteidigung – eine reine LLM-Empfehlung wäre nicht reproduzierbar.)
- **Nachvollziehbarkeit:** Jede Empfehlung zeigt ihre Komponenten und Begründung.
- **Robustheit in der Demo:** Keine harten Abhängigkeiten, die live brechen (Vorab-Cache, Fallbacks).
- **Verständlicher Code:** Klare Trennung von Datenbeschaffung, Entscheidung und Erklärung.

## Abgrenzung (Was PortfAIo NICHT ist)

- **Keine Anlageberatung** im rechtlichen Sinn. Die Modelle (ARIMA, Random Forest) sind
  **didaktisch/illustrativ**, kein produktives Alpha-Signal.
- Kein Hochfrequenz-/Intraday-Trading – es geht um Tagesdaten und mittelfristige Einschätzungen.
- Kein Multi-User-SaaS.

## Erfolgskriterien für die Demo

1. Der Agent läuft sichtbar: ruft Tools auf, zeigt Zwischenschritte, streamt die Begründung.
2. Die Empfehlung ist **reproduzierbar** (zweimal dieselbe Analyse → identisches Signal/Score).
3. Die Begründung **widerspricht der Empfehlung nicht** (Konsistenz LLM ↔ Pipeline).
4. Der vollständige Data-Science-Prozess ist erkennbar (Daten → Indikatoren → Modelle → Ensemble).
