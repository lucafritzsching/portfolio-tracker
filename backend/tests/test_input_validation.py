"""Tests for the Phase-3 input hardening: central ticker validation + current_prices bounds."""
import pytest
from fastapi import HTTPException

from routers.agent import _parse_prices
from utils import normalize_ticker


# ── normalize_ticker ─────────────────────────────────────────────────────────────

def test_normalize_ticker_uppercases_and_trims():
    assert normalize_ticker("  aapl ") == "AAPL"
    assert normalize_ticker("brk.b") == "BRK.B"


@pytest.mark.parametrize("bad", ["", "   ", "a b", "drop;table", "<script>", "x" * 21])
def test_normalize_ticker_rejects_invalid(bad):
    with pytest.raises(HTTPException) as exc:
        normalize_ticker(bad)
    assert exc.value.status_code == 400


# ── _parse_prices bounds ─────────────────────────────────────────────────────────

def test_parse_prices_happy_path():
    assert _parse_prices('{"AAPL": 185.0, "MSFT": 380}') == {"AAPL": 185.0, "MSFT": 380.0}


def test_parse_prices_invalid_json_or_non_object():
    assert _parse_prices("not json") == {}
    assert _parse_prices("[1, 2, 3]") == {}
    assert _parse_prices("") == {}


def test_parse_prices_drops_non_positive_and_nonfinite():
    out = _parse_prices('{"OK": 10.0, "ZERO": 0, "NEG": -5, "NAN": "abc"}')
    assert out == {"OK": 10.0}


def test_parse_prices_caps_entry_count():
    big = "{" + ",".join(f'"T{i}": 1.0' for i in range(600)) + "}"
    assert len(_parse_prices(big)) == 500
