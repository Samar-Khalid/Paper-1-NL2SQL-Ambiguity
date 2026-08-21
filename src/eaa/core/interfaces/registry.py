"""Component registry protocol: how implementations are looked up.

The registry package provides concrete implementations
(``core.registry.payload_registry``, ``type_registry``); this protocol is the
boundary that consuming modules depend on.
"""
from __future__ import annotations

from typing import Protocol, TypeVar

T = TypeVar("T")


class ComponentRegistry(Protocol[T]):
    """Namespaced lookup of registered components."""

    @property
    def name(self) -> str:
        """Return the registry name."""
        ...

    def register(self, key: str, item: T, *, replace: bool = False) -> None:
        """Register an item under a namespaced key."""
        ...

    def get(self, key: str) -> T:
        """Return the item for a key or raise ``RegistryError``."""
        ...

    def lookup(self, key: str) -> T | None:
        """Return the item for a key, or None."""
        ...

    def keys(self) -> list[str]:
        """Return the sorted registered keys."""
        ...

    def __contains__(self, key: str) -> bool:
        """Return whether a key is registered."""
        ...


__all__ = ["ComponentRegistry"]
