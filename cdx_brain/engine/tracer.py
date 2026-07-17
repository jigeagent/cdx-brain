"""Search tracer."""
from __future__ import annotations
import json, time
from typing import Any


class SearchStep:
    """A single pipeline step trace."""
    def __init__(self, name: str, input: Any = None, output: Any = None, duration_ms: float = 0.0):
        self.name = name
        self.input = input
        self.output = output
        self.duration_ms = duration_ms

    def to_dict(self) -> dict:
        return {"name": self.name, "input": str(self.input), "output": str(self.output), "duration_ms": self.duration_ms}


class SearchTracer:
    """Collects pipeline execution traces."""

    def __init__(self):
        self._steps: list[SearchStep] = []
        self._start = time.monotonic()

    def step(self, name: str, input: Any = None, output: Any = None) -> None:
        duration = (time.monotonic() - self._start) * 1000
        self._steps.append(SearchStep(name, input, output, duration))

    def serialize(self) -> list[dict]:
        return [s.to_dict() for s in self._steps]
