"""Visualization contracts: chart spec and viz intent (dataset-independent).

NL2VIS tasks and future chart-recommendation work share these types; encoding
details stay out of ``core/contracts`` (implemented in ``visualization/``).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .base import ContractModel, Payload

MarkType = Literal["bar", "line", "area", "point", "pie", "histogram", "scatter", "text"]
ChartFormat = Literal["vega-lite", "matplotlib", "custom"]


class VizIntent(ContractModel):
    """What the user wants to see (semantic, renderer-agnostic)."""

    intent: str | None = None
    aggregates: list[str] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    measures: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    order: list[dict[str, Any]] = Field(default_factory=list)
    limit: int | None = None


class ChartSpec(ContractModel):
    """A concrete, renderer-specific chart specification."""

    spec_type: ChartFormat = "vega-lite"
    mark: MarkType | None = None
    encoding: dict[str, Any] = Field(default_factory=dict)
    data_schema: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None
    description: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class VisualizationPayload(Payload):
    """Envelope payload linking a task question to a chart spec (NL2VIS)."""

    question: str
    dataset_id: str
    intent: VizIntent | None = None
    spec: ChartSpec | None = None
