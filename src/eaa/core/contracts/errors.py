"""Typed error taxonomy for the framework."""
from __future__ import annotations

from typing import Any


class EAAError(Exception):
    """Base error for all framework exceptions."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.context = context or {}


class ContractError(EAAError):
    """A contract was malformed or unregistered."""


class RegistryError(EAAError):
    """A type was not registered or was registered twice."""


class PipelineError(EAAError):
    """A pipeline execution error."""


class BudgetExceededError(PipelineError):
    """A runtime budget was exceeded."""


class AdapterError(EAAError):
    """A dataset/benchmark adapter failed."""


class ExecutionError(EAAError):
    """Query execution failed or was denied."""
