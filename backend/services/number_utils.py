"""Small numeric normalization helpers shared by data-ingestion services."""
from __future__ import annotations

import math
from typing import Any


def finite_number(value: Any) -> float | None:
    """Return a finite float or None for NaN/Infinity/empty values."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
