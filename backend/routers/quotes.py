import re
import httpx
from fastapi import APIRouter, HTTPException, Query
from config import settings
from schemas import QuoteOut

router = APIRouter(prefix="/quotes", tags=["quotes"])

SYMBOL_RE = re.compile(r"^[A-Z0-9.\^=\-]{1,20}$", re.IGNORECASE)


@router.get("/{ticker}", response_model=QuoteOut)
async def get_quote(ticker: str):
    ticker = ticker.upper()
    if not SYMBOL_RE.match(ticker):
        raise HTTPException(400, "Ungültiges Ticker-Symbol")
    if not settings.finnhub_api_key:
        raise HTTPException(500, "FINNHUB_API_KEY nicht konfiguriert")

    url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={settings.finnhub_api_key}"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
            data = resp.json()
        except Exception:
            raise HTTPException(502, "Finnhub-Anfrage fehlgeschlagen")

    if not resp.is_success or data.get("c") == 0:
        raise HTTPException(404, f"Symbol {ticker} nicht gefunden")

    return QuoteOut(
        ticker=ticker,
        current_price=data["c"],
        day_change=data["dp"],
        previous_close=data["pc"],
    )


@router.get("/batch/quotes")
async def get_quotes_batch(tickers: str = Query(..., description="Komma-getrennte Ticker, z.B. AAPL,MSFT,VOO")):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(400, "Keine Ticker angegeben")
    if len(ticker_list) > 50:
        raise HTTPException(400, "Maximal 50 Ticker pro Anfrage")

    results = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for ticker in ticker_list:
            try:
                url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={settings.finnhub_api_key}"
                resp = await client.get(url)
                data = resp.json()
                if resp.is_success and data.get("c", 0) != 0:
                    results[ticker] = {
                        "current_price": data["c"],
                        "day_change": data["dp"],
                        "previous_close": data["pc"],
                    }
            except Exception:
                pass

    return results
