"""Typed errors for the Surface B candidate-selection module."""
from __future__ import annotations

from ..errors import AmbiguityResolutionError


class CandidateSelectionError(AmbiguityResolutionError):
    """A Surface B candidate-selection step failed.

    Raised when a question cannot be scored — for example a task envelope
    carries no question text or no database id, so the pool cannot be built
    reproducibly.
    """


__all__ = ["CandidateSelectionError"]
