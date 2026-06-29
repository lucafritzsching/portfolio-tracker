"""Shared, dependency-light helpers used across routers/services."""
import re

from fastapi import HTTPException

# Tickers: letters/digits plus the few symbols Yahoo/Finnhub use (., ^, =, -). 1–20 chars.
# One central rule so every endpoint enforces the same shape (previously only /quotes did).
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\^=\-]{1,20}$")


def normalize_ticker(raw: str) -> str:
    """Upper-case, trim and validate a ticker symbol.

    Returns the normalized symbol or raises HTTP 400 on an invalid one. Use at the entry of any
    endpoint that accepts a ticker, so malformed input is rejected consistently and early.
    """
    ticker = (raw or "").strip().upper()
    if not _SYMBOL_RE.match(ticker):
        raise HTTPException(400, "Ungültiges Ticker-Symbol")
    return ticker
