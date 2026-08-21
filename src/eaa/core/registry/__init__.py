"""Component registries: types, payloads, plugins, metrics.

The registry package is the mechanism that makes the contract-first core
dataset-independent (ADR-002). Dataset adapters and future modules register
their concrete types here; core control flow never switches on concrete types.
"""
from __future__ import annotations

from ..contracts.errors import RegistryError
from .payload_registry import (
    PayloadRegistry,
    envelope_for,
    get_payload_model,
    payload,
    register_payload,
    registry,
)
from .plugin_manager import PluginManager, discover_entry_points, plugin_registry, register_plugin
from .type_registry import TypeRegistry, type_registry

__all__ = [
    "PluginManager",
    "PayloadRegistry",
    "RegistryError",
    "TypeRegistry",
    "discover_entry_points",
    "envelope_for",
    "get_payload_model",
    "payload",
    "plugin_registry",
    "register_payload",
    "register_plugin",
    "registry",
    "type_registry",
]
