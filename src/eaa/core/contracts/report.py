"""AnalysisReport contract: the core report structure.

Placed in ``core.contracts`` (not in ``business_intelligence``) so later phases
(reporting/BI) consume a core contract — the report never imports BI logic
(see the review finding on Phase 4 importing ``business_intelligence``).
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel, Envelope, Payload


class SectionHeader(ContractModel):
    """Header for a report section."""

    section_id: str
    title: str
    kind: str = "text"  # text | table | chart | metric | evidence
    order: int = 0


class ReportSection(ContractModel):
    """One section of an analysis report."""

    header: SectionHeader
    content: dict[str, Any] = Field(default_factory=dict)
    references: list[str] = Field(default_factory=list)


class AnalysisReportPayload(Payload):
    """The report body (dataset-independent)."""

    report_id: str
    session_id: str | None = None
    question: str | None = None
    sections: list[ReportSection] = Field(default_factory=list)
    generated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportHeader(ContractModel):
    """Header shared by all report envelopes."""

    report_id: str
    session_id: str | None = None
    created_at: str | None = None


class AnalysisReportEnvelope(Envelope[Payload]):
    """Envelope for analysis reports (type_key: ``analysis_report``)."""

    header: ReportHeader
