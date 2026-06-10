"""Tests für die reinen Universum-Filter (NASDAQ Stock Screener, Alt-B Stufe 1)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.universe import (
    is_biotech_industry,
    is_common_symbol,
    passes_universe_filters,
    parse_screener_market_cap,
)


# ── Sektor + Industrie: Biotech/Pharma-Bezug ────────────────────────────────────
def test_pharma_preparations_passes():
    assert is_biotech_industry("Health Care", "Biotechnology: Pharmaceutical Preparations")


def test_biological_products_passes():
    assert is_biotech_industry("Health Care", "Biotechnology: Biological Products (No Diagnostic Substances)")


def test_biological_research_passes():
    # NASDAQ-Tippfehler "Resarch" ist real — Präfix-Match fängt ihn ab.
    assert is_biotech_industry("Health Care", "Biotechnology: Commercial Physical & Biological Resarch")


def test_medicinal_chemicals_passes_with_padding():
    # Der Screener liefert diesen Wert mit führenden/abschließenden Leerzeichen.
    assert is_biotech_industry("Health Care", "  Medicinal Chemicals and Botanical Products  ")


def test_devices_and_diagnostics_excluded():
    assert not is_biotech_industry("Health Care", "Biotechnology: Electromedical & Electrotherapeutic Apparatus")
    assert not is_biotech_industry("Health Care", "Biotechnology: In Vitro & In Vivo Diagnostic Substances")
    assert not is_biotech_industry("Health Care", "Medical/Dental Instruments")


def test_wrong_sector_excluded():
    assert not is_biotech_industry("Technology", "Biotechnology: Pharmaceutical Preparations")
    assert not is_biotech_industry(None, "Biotechnology: Pharmaceutical Preparations")
    assert not is_biotech_industry("Health Care", None)


# ── Market-Cap-Parsing (Screener liefert formatierte Strings) ──────────────────
def test_market_cap_string_parsed():
    assert parse_screener_market_cap("6,082,900,000.00") == 6_082_900_000.0
    assert parse_screener_market_cap("$5,000,000") == 5_000_000.0
    assert parse_screener_market_cap(1.5e9) == 1.5e9


def test_market_cap_empty_or_zero_is_none():
    assert parse_screener_market_cap("") is None
    assert parse_screener_market_cap(None) is None
    assert parse_screener_market_cap("0.00") is None
    assert parse_screener_market_cap("n/a") is None


# ── Symbol-Hygiene ──────────────────────────────────────────────────────────────
def test_common_symbol():
    assert is_common_symbol("KYMR")
    assert not is_common_symbol("ABC^A")    # Preferred
    assert not is_common_symbol("ABC/WS")   # Warrant
    assert not is_common_symbol("")
    assert not is_common_symbol(None)


def test_units_warrants_and_rights_are_excluded_by_name_and_symbol():
    assert not passes_universe_filters({
        "symbol": "BIOW",
        "name": "Example Bio Warrants",
        "sector": "Health Care",
        "industry": "Biotechnology: Pharmaceutical Preparations",
        "marketCap": "500,000,000",
    })
    assert not passes_universe_filters({
        "symbol": "BIOU",
        "name": "Example Bio Units",
        "sector": "Health Care",
        "industry": "Biotechnology: Pharmaceutical Preparations",
        "marketCap": "500,000,000",
    })
    assert not passes_universe_filters({
        "symbol": "BIOR",
        "name": "Example Bio Rights",
        "sector": "Health Care",
        "industry": "Biotechnology: Pharmaceutical Preparations",
        "marketCap": "500,000,000",
    })


def test_universe_filter_requires_realistic_minimum_market_cap():
    assert passes_universe_filters({
        "symbol": "GOOD",
        "name": "Good Bio Inc.",
        "sector": "Health Care",
        "industry": "Biotechnology: Pharmaceutical Preparations",
        "marketCap": "150,000,000",
    })
    assert not passes_universe_filters({
        "symbol": "TINY",
        "name": "Tiny Bio Inc.",
        "sector": "Health Care",
        "industry": "Biotechnology: Pharmaceutical Preparations",
        "marketCap": "149,999,999",
    })
