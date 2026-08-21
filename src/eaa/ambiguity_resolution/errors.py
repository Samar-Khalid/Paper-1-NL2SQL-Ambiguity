"""Typed errors for the ambiguity resolution module."""
from __future__ import annotations

from eaa.core.contracts.errors import EAAError


class AmbiguityResolutionError(EAAError):
    """An ambiguity analysis, clarification, or answerability step failed.

    Raised by ``eaa.ambiguity_resolution`` when a step cannot produce a
    well-formed contract — for example the resolved schema for a database is
    unavailable, or a formalized assumption references a span outside the
    question text. It is distinct from ``MetadataError`` (enrichment data
    integrity) and ``PipelineError`` (stage orchestration).
    """


__all__ = ["AmbiguityResolutionError"]
