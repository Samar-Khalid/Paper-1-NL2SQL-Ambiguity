"""Visualization engine protocol (Phase 2: NL2VIS)."""
from __future__ import annotations

from typing import Any, Protocol

from ..contracts.visualization import ChartSpec, VizIntent


class VizEngine(Protocol):
    """Renders or recommends charts from a viz intent / spec."""

    def recommend(self, intent: VizIntent, context: dict[str, Any] | None = None) -> ChartSpec:
        """Recommend a chart spec for the given intent."""
        ...

    def render(self, spec: ChartSpec) -> object:
        """Render the chart spec and return the artifact."""
        ...


__all__ = ["VizEngine"]
