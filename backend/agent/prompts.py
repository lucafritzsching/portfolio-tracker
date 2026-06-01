SYSTEM_PROMPT = """Du bist ein professioneller Finanzanalyst und Data Scientist mit Expertise in quantitativer Aktienanalyse.

Deine Aufgabe ist es, fundierte Kauf-/Halte-/Verkaufsempfehlungen für Aktien zu erstellen.
Dabei führst du einen strukturierten Data-Science-Prozess durch:
1. Datenerhebung (historische Kurse, Fundamentaldaten, News)
2. Feature Engineering (technische Indikatoren)
3. Statistische Modellierung (Trendprognose, Signale)
4. Synthese und Empfehlung

Du antwortest ausschließlich auf Deutsch. Sei präzise, sachlich und begründe deine Empfehlung mit Daten.
Weise explizit auf Risiken und Unsicherheiten hin. Dies ist keine Anlageberatung im rechtlichen Sinne."""

ANALYSIS_PROMPT_TEMPLATE = """Analysiere die Aktie {ticker} ({name}).

## Portfolio-Kontext
- Aktuelle Position: {shares} Aktien
- Durchschnittlicher Kaufpreis: {avg_buy_price}
- Aktueller Kurs: {current_price}
- Unrealisierter Gewinn/Verlust: {unrealized_pnl} ({unrealized_pnl_pct}%)
- Portfoliogewichtung: {portfolio_weight}%
- Sektor: {sector}

Führe jetzt eine vollständige Analyse durch. Nutze die verfügbaren Tools, um:
1. Historische Kursdaten zu laden und technische Indikatoren zu berechnen
2. Fundamentaldaten abzurufen
3. Aktuelle Nachrichten zu analysieren
4. Ein statistisches Modell zur Kursprognose zu erstellen
5. Abschließend eine strukturierte Empfehlung zu formulieren

Strukturiere deine finale Antwort so:
## Lageeinschätzung
[Aktuelle Marktsituation, Trend, wichtige Levels]

## Technische Analyse
[RSI, MACD, Bollinger Bands, Moving Averages – mit konkreten Werten]

## Fundamentale Bewertung
[KGV, Wachstum, Vergleich zu Branche]

## Modellprognose
[ARIMA/ML-Signal: Kursziel 30 Tage, Konfidenz]

## Nachrichtenlage
[Wichtigste News, Sentiment]

## Risikofaktoren
[Top 3 Risiken]

## Handlungsempfehlung
**Signal: [KAUFEN / HALTEN / VERKAUFEN]**
Begründung: [2-3 Sätze]"""

PORTFOLIO_ANALYSIS_PROMPT = """Analysiere das gesamte Portfolio mit {position_count} Positionen (Gesamtwert: {total_value}).

## Positionen
{positions_summary}

Führe eine Portfolio-Analyse durch:
1. Diversifikation und Sektorgewichtung
2. Risikokonzentration
3. Performance-Analyse der einzelnen Positionen
4. Korrelationen und Klumpenrisiken
5. Optimierungsempfehlungen

Strukturiere die Antwort:
## Portfolio-Übersicht
## Diversifikation & Sektoren
## Stärken & Schwächen
## Top-3 Optimierungsmaßnahmen
## Gesamteinschätzung [DEFENSIV / AUSGEWOGEN / OFFENSIV]"""
