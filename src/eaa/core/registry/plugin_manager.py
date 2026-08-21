"""Plugin manager: load dataset adapters and modules via entry points.

Dataset independence is enforced by discovery: the core never imports a dataset
package directly (ADR-002). Adapters register themselves through entry points
in ``pyproject.toml`` and the plugin manager instantiates them by interface.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import typing
from typing import Any

from ..contracts.errors import EAAError, RegistryError


class PluginLoadError(EAAError):
    """A plugin could not be imported or instantiated."""


class PluginManager:
    """Discovers and instantiates plugins from importlib entry points.

    Entry-point group convention (in the installing package's
    ``pyproject.toml``)::

        [project.entry-points."eaa.datasets"]
        mydataset = "eaa.datasets.adapters.mydataset:plugin"

    where ``plugin`` is a zero-arg factory returning an adapter instance.
    """

    def __init__(self, group: str = "eaa.datasets") -> None:
        self._group = group
        self._factories: dict[str, typing.Callable[[], Any]] | None = None

    def discover(self) -> dict[str, typing.Callable[[], Any]]:
        """Discover and load all plugin factories in the entry-point group.

        Results are cached for the manager instance. A broken plugin raises
        ``PluginLoadError`` instead of silently vanishing.
        """
        if self._factories is not None:
            return self._factories
        found: dict[str, typing.Callable[[], Any]] = {}
        for ep in importlib.metadata.entry_points().select(group=self._group):
            try:
                found[ep.name] = ep.load()
            except Exception as exc:  # noqa: BLE001 - a broken plugin must not kill the host
                raise PluginLoadError(f"failed to load plugin '{ep.name}': {exc}") from exc
        self._factories = found
        return found

    def load(self, name: str) -> Any:
        """Instantiate the plugin factory registered under ``name``.

        Raises
        ------
            RegistryError: if no plugin with that name is discovered.
        """
        factories = self.discover()
        if name not in factories:
            raise RegistryError(f"plugin '{name}' not found in group '{self._group}'")
        return factories[name]()

    def load_all(self) -> dict[str, Any]:
        """Instantiate every discovered plugin, keyed by name."""
        return {name: factory() for name, factory in self.discover().items()}

    def names(self) -> list[str]:
        """Return the sorted names of discovered plugins."""
        return sorted(self.discover())


plugin_registry = PluginManager()


def discover_entry_points(group: str = "eaa.datasets") -> dict[str, typing.Callable[[], Any]]:
    """Discover plugin factories in the given entry-point group."""
    return PluginManager(group).discover()


def register_plugin(
    factory: typing.Callable[[], Any],
    *,
    name: str | None = None,
    group: str = "eaa.datasets",
) -> typing.Callable[[], Any]:
    """Register a plugin factory at runtime (in-memory; no metadata write-back).

    For persistent discovery use the entry-point mechanism instead.
    """
    key = name or (getattr(factory, "__name__", repr(factory)) or repr(factory))
    manager = plugin_registry if group == "eaa.datasets" else PluginManager(group)
    manager._factories = manager.discover()  # ensure initialized  # noqa: SLF001
    manager._factories[key] = factory  # noqa: SLF001
    return factory


__all__ = [
    "PluginLoadError",
    "PluginManager",
    "discover_entry_points",
    "plugin_registry",
    "register_plugin",
]
