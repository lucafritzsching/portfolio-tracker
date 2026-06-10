"""Tests for market-data normalization before values are persisted."""
from pathlib import Path
import math
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.number_utils import finite_number


def test_finite_number_rejects_infinity_and_nan():
    assert finite_number(float("inf")) is None
    assert finite_number(float("-inf")) is None
    assert finite_number(float("nan")) is None
    assert finite_number("Infinity") is None
    assert finite_number("-Infinity") is None
    assert finite_number("NaN") is None


def test_finite_number_keeps_regular_numbers():
    assert finite_number(12.34) == 12.34
    assert finite_number("56.78") == 56.78
    assert finite_number(None) is None
