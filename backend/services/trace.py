"""Lightweight decision trace: follow what a strategy did, why, and how long it took.

Makes the Alt-B pipeline legible (presentation/flowcharts) and locates the compute
bottleneck via per-step ``duration_ms``. Plain dataclasses + a tiny collector, no
framework. JSON-serialisable via ``as_dict``.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field


@dataclass
class TraceStep:
    step: str                                  # short stage name, e.g. "gate"
    status: str = "ok"                         # ok | fallback | error | skip
    reason: str = ""                           # human-readable why
    duration_ms: float | None = None           # set when timed; None for instant decisions
    data: dict = field(default_factory=dict)   # small structured payload


@dataclass
class Trace:
    steps: list[TraceStep] = field(default_factory=list)

    def add(self, step: str, status: str = "ok", reason: str = "",
            duration_ms: float | None = None, **data) -> TraceStep:
        rec = TraceStep(step=step, status=status, reason=reason, duration_ms=duration_ms, data=data)
        self.steps.append(rec)
        return rec

    @contextmanager
    def timed(self, step: str, **data):
        """Time a block; records duration_ms and status='error' (then re-raises) on failure."""
        start = time.perf_counter()
        outcome = {"status": "ok", "reason": ""}
        try:
            yield outcome
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
            outcome["status"] = "error"
            outcome["reason"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.add(step, status=outcome["status"], reason=outcome["reason"],
                     duration_ms=round((time.perf_counter() - start) * 1000, 2), **data)

    def as_dict(self) -> list[dict]:
        return [asdict(s) for s in self.steps]
