"""Type registry: namespaced registration of any typed component.

General-purpose registry used for metrics, prompt templates, chart encoders,
and other named components. Keys are namespaced as ``<owner>:<name>`` to avoid
collisions between the core, modules, and dataset adapters.
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from ..contracts.errors import RegistryError

T = TypeVar("T")


def _assert_valid_key(key: str) -> None:
    """Raise if ``key`` is empty or not namespaced with a colon."""
    if not key or ":" not in key:
        raise RegistryError(f"registry keys must be '<owner>:<name>', got {key!r}")


class TypeRegistry(Generic[T]):
    """Namespaced registry for typed components."""

    def __init__(self, *, name: str = "registry") -> None:
        self._name = name
        self._items: dict[str, T] = {}

    @property
    def name(self) -> str:
        """Return the registry name."""
        return self._name

    def register(self, key: str, item: T, *, replace: bool = False) -> None:
        """Register an item under a namespaced key.

        Raises
        ------
            RegistryError: if the key is invalid or already registered and
                ``replace`` is False.
        """
        _assert_valid_key(key)
        if not replace and key in self._items:
            raise RegistryError(f"{self._name}: key '{key}' already registered")
        self._items[key] = item

    def get(self, key: str) -> T:
        """Return the item for ``key`` or raise ``RegistryError``."""
        try:
            return self._items[key]
        except KeyError:
            raise RegistryError(f"{self._name}: key '{key}' is not registered") from None

    def lookup(self, key: str) -> T | None:
        """Return the item for ``key`` or None if not registered."""
        return self._items.get(key)

    def all(self) -> dict[str, T]:
        """Return a copy of all registered items."""
        return dict(self._items)

    def keys(self) -> list[str]:
        """Return the sorted registered keys."""
        return sorted(self._items)

    def __contains__(self, key: str) -> bool:
        """Return whether ``key`` is registered."""
        return key in self._items


type_registry: TypeRegistry[Any] = TypeRegistry(name="eaa-types")


def register(name: str, item: T) -> T:
    """Register an item on the process-wide type registry."""
    type_registry.register(name, item)
    return item


def get(name: str) -> Any:
    """Return an item from the process-wide type registry."""
    return type_registry.get(name)
