"""Dataset manifest contract: what a dataset adapter declares about itself.

Adapters publish a ``DatasetManifest`` so the core and evaluation harness can
validate that a package is complete and self-describing without importing the
dataset itself.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel


class DatasetManifest(ContractModel):
    """Self-description of a dataset/benchmark adapter."""

    name: str
    version: str
    license: str | None = None
    description: str | None = None
    type_keys: list[str] = Field(default_factory=list)
    source: str | None = None
    splits: list[str] = Field(default_factory=list)
    citation: str | None = None
    homepage: str | None = None
    entry_points: dict[str, str] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)
