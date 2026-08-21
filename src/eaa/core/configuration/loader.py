"""Layered configuration loading and resolution.

Layer order (highest priority last): ``default.yaml`` -> ``datasets/<d>.yaml``
-> ``experiments/<e>.yaml`` -> CLI overrides -> env vars (``EAA_*``). Experiment
files may list a ``defaults:`` chain; relative default paths are resolved
against the referencing file's directory and the config root. The fully merged
dict is validated against ``RootConfig`` and snapshotted for artifact recording.
"""
from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from ..contracts.errors import EAAError
from .schemas import RootConfig, RuntimeConfig


class ConfigurationError(EAAError):
    """A config file was missing, malformed, or failed validation."""


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML file as a plain dict.

    Raises
    ------
        ConfigurationError: if the file is missing, malformed, or does not map
            to a dict.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigurationError(f"config file not found: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"config file is not valid YAML: {config_path}: {exc}"
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"config file must map to a dict: {config_path}")
    return data


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge ``overlay`` into ``base`` (dicts merged, other values replaced)."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _resolve_default(referrer: Path, config_root: Path, dep: str) -> Path:
    """Resolve a ``defaults:`` entry.

    Entries may be relative to the config root or to any ancestor of the
    referencing file (templates reference ``configs/`` siblings such as
    ``default.yaml`` and ``datasets/<d>.yaml`` from ``experiments/``).
    """
    candidate = Path(dep)
    if candidate.is_absolute():
        if not candidate.exists():
            raise ConfigurationError(f"config default not found: {dep!r}")
        return candidate
    if (config_root / dep).exists():
        return config_root / dep
    for base in (referrer.parent, *referrer.parent.parents):
        candidate = base / dep
        if candidate.exists():
            return candidate
    raise ConfigurationError(f"config default not found: {dep!r} (from {referrer})")


def load_config_chain(
    path: Path,
    config_root: Path,
    visited: set[Path] | None = None,
) -> dict[str, Any]:
    """Load a config file after its ``defaults:`` chain (cycle-safe)."""
    resolved = path.resolve()
    visited = visited if visited is not None else set()
    if resolved in visited:
        raise ConfigurationError(f"circular config defaults at: {resolved}")
    visited.add(resolved)
    raw = load_yaml(resolved)
    merged: dict[str, Any] = {}
    for dep in raw.get("defaults") or []:
        dep_path = _resolve_default(resolved, config_root, dep)
        merged = deep_merge(merged, load_config_chain(dep_path, config_root, visited))
    body = {key: value for key, value in raw.items() if key != "defaults"}
    return deep_merge(merged, body)


def _coerce_env_value(value: str) -> Any:
    """Coerce a raw env var string to a primitive for config merging."""
    lowered = value.strip().lower()
    if lowered in ("true", "yes", "1", "on"):
        return True
    if lowered in ("false", "no", "0", "off"):
        return False
    if lowered in ("null", "none", ""):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _set_nested(target: dict[str, Any], parts: list[str], value: Any) -> None:
    """Set ``value`` at the nested path ``parts`` in ``target`` (creating dicts)."""
    node = target
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def apply_env_overrides(
    data: dict[str, Any],
    *,
    prefix: str = "EAA_",
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Apply ``EAA_<SECTION>__<FIELD>`` env vars onto a deep copy of ``data``."""
    result = copy.deepcopy(data)
    env = os.environ if env is None else env
    for key, value in env.items():
        if not key.startswith(prefix):
            continue
        parts = [part.lower() for part in key[len(prefix) :].split("__") if part]
        if not parts:
            continue
        _set_nested(result, parts, _coerce_env_value(value))
    return result


def apply_overrides(
    data: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Apply CLI-style overrides (nested dicts and/or dotted keys) onto a copy."""
    result = copy.deepcopy(data)
    for key, value in overrides.items():
        if isinstance(key, str) and "." in key:
            _set_nested(result, key.split("."), value)
        elif isinstance(value, dict):
            existing = result.get(key)
            result[key] = (
                deep_merge(existing, value) if isinstance(existing, dict) else copy.deepcopy(value)
            )
        else:
            result[key] = value
    return result


def resolve_config(
    config_path: str | Path | None = None,
    *,
    config_root: str | Path | None = None,
    dataset_config: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    env_prefix: str = "EAA_",
    env: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Resolve a config from layered sources into a validated ``RuntimeConfig``.

    Parameters
    ----------
    config_path:
        An experiment config file; its ``defaults:`` chain is loaded first.
    config_root:
        Base directory for resolving relative ``defaults:`` entries (defaults to
        the directory containing ``config_path``, else the current directory).
    dataset_config:
        Optional dataset config file merged after ``config_path``.
    overrides:
        CLI-style overrides (nested dicts or dotted keys); applied before env.
    env_prefix:
        Prefix for env-var overrides (default ``EAA_``); nesting uses ``__``.
    env:
        Environment mapping (defaults to ``os.environ``).
    """
    root = (
        Path(config_root).resolve()
        if config_root is not None
        else (
            Path(config_path).resolve().parent
            if config_path is not None
            else Path.cwd().resolve()
        )
    )
    merged: dict[str, Any] = {}
    if config_path is not None:
        merged = load_config_chain(Path(config_path).resolve(), root)
    if dataset_config is not None:
        merged = deep_merge(merged, load_yaml(Path(dataset_config).resolve()))
    if overrides:
        merged = apply_overrides(merged, overrides)
    merged = apply_env_overrides(merged, prefix=env_prefix, env=env)
    try:
        root_config = RootConfig.model_validate(merged)
    except Exception as exc:  # pydantic ValidationError
        raise ConfigurationError(f"config validation failed: {exc}") from exc
    return RuntimeConfig(root=root_config, resolved=merged)


__all__ = [
    "ConfigurationError",
    "apply_env_overrides",
    "apply_overrides",
    "deep_merge",
    "load_config_chain",
    "load_yaml",
    "resolve_config",
]
