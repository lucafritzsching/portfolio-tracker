"""Tests für die Cache-Härtung in services/market_data.py (kein Netz, keine DB).

1. _download_period: ein Refresh ersetzt die komplette Historie — es darf nie kürzer
   als "2y" heruntergeladen werden, längere Zeiträume bleiben erlaubt.
2. _news_fresh: News-Frische hängt am Fetch-Zeitpunkt (prozess-lokal), nicht am
   published_at des neuesten Artikels.
"""
from datetime import datetime, timedelta

from services import market_data as md


def test_download_period_never_shrinks_below_2y():
    assert md._download_period("1mo") == "2y"
    assert md._download_period("3mo") == "2y"
    assert md._download_period("6mo") == "2y"
    assert md._download_period("1y") == "2y"
    assert md._download_period("2y") == "2y"


def test_download_period_keeps_longer_requests():
    assert md._download_period("5y") == "5y"
    assert md._download_period("max") == "max"


def test_download_period_unknown_value_defaults_to_2y():
    assert md._download_period("kaputt") == "2y"


def test_news_fresh_lifecycle():
    md._news_fetched_at.clear()
    try:
        # Nie gefetcht → nicht frisch.
        assert md._news_fresh("AAPL", force=False) is False
        # Frisch gestempelt → frisch (auch wenn die Artikel selbst alt sind).
        md._news_fetched_at["AAPL"] = datetime.utcnow()
        assert md._news_fresh("AAPL", force=False) is True
        # force=True erzwingt einen Refetch trotz frischem Stempel.
        assert md._news_fresh("AAPL", force=True) is False
        # Stempel älter als NEWS_TTL → nicht mehr frisch.
        md._news_fetched_at["AAPL"] = datetime.utcnow() - md.NEWS_TTL - timedelta(minutes=1)
        assert md._news_fresh("AAPL", force=False) is False
    finally:
        md._news_fetched_at.clear()
