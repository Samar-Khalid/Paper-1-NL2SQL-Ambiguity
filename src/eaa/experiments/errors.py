"""Errors for the experiment drivers (live outside core).

Drivers compose core, evaluation, llm, and dataset adapters, so their errors
extend the core ``EAAError`` taxonomy without living in ``core``.
"""
from __future__ import annotations

from eaa.core.contracts.errors import EAAError


class ExperimentError(EAAError):
    """A baseline experiment could not be configured or run."""


__all__ = ["ExperimentError"]
