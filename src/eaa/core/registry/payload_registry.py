"""Payload registry: the discriminant for the envelope + typed payload design.

Each task/prediction/gold type key (``nl2sql``, ``nl2vis``, ``decision``, ...)
maps to one payload model. Envelopes are built *through* the registry so the
concrete payload is validated as the registered model; core code never needs to
import dataset payload types.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import TypeAdapter

from ..contracts.base import Envelope, Payload, set_payload_resolver
from ..contracts.errors import RegistryError

T = TypeVar("T", bound=Payload)
E = TypeVar("E", bound=Envelope[Any])

_TYPE_KEY_ATTR = "__eaa_type_key__"


def payload(type_key: str) -> Callable[[type[T]], type[T]]:
    """Mark a payload class with its registry type key.

    Registering the model (via ``@payload`` + import) or ``register_payload``
    makes it available under ``type_key``. The decorator itself does not
    auto-register (registration needs a registry instance); adapters call
    ``registry.register`` explicitly during plugin setup.
    """

    def _decorator(cls: type[T]) -> type[T]:
        setattr(cls, _TYPE_KEY_ATTR, type_key)
        return cls

    return _decorator


class PayloadRegistry:
    """Maps ``type_key`` -> payload model and builds typed envelopes."""

    def __init__(self) -> None:
        self._models: dict[str, type[Payload]] = {}

    def register(self, type_key: str, model: type[Payload]) -> None:
        """Register a payload model under a type key.

        Raises
        ------
            RegistryError: if the model is not a ``Payload`` subclass or the
                type key is already bound to a different model.
        """
        if not isinstance(model, type) or not issubclass(model, Payload):
            raise RegistryError(f"model for '{type_key}' must be a Payload subclass")
        if type_key in self._models and self._models[type_key] is not model:
            raise RegistryError(
                f"type_key '{type_key}' already registered to {self._models[type_key]}"
            )
        self._models[type_key] = model

    def get(self, type_key: str) -> type[Payload]:
        """Return the payload model registered for ``type_key``.

        Raises
        ------
            RegistryError: if the type key is not registered.
        """
        try:
            return self._models[type_key]
        except KeyError:
            raise RegistryError(f"type_key '{type_key}' is not registered") from None

    def __contains__(self, type_key: str) -> bool:
        """Return whether ``type_key`` is registered."""
        return type_key in self._models

    def keys(self) -> list[str]:
        """Return the sorted list of registered type keys."""
        return sorted(self._models)

    def validate_payload(self, type_key: str, data: dict[str, Any]) -> Payload:
        """Validate an arbitrary dict against the registered payload model."""
        model = self.get(type_key)
        adapter: TypeAdapter[Payload] = TypeAdapter(model)
        return adapter.validate_python(data)

    def envelope_for(self, envelope_cls: type[E], type_key: str, data: dict[str, Any]) -> E:
        """Build a typed envelope from a plain dict.

        The envelope's ``before``-validator resolves the ``payload`` dict
        against the registered payload model for ``type_key``, so validation is
        strict per type key.
        """
        self.get(type_key)  # fail fast with a RegistryError for unknown keys
        base: dict[str, Any]
        if isinstance(data, dict) and "payload" not in data:
            base = {"type_key": type_key, "payload": data}
        else:
            base = dict(data)
            base["type_key"] = type_key
        try:
            return envelope_cls.model_validate(base)
        except Exception as exc:  # pydantic ValidationError
            raise RegistryError(f"envelope for '{type_key}' failed validation: {exc}") from exc


_registry: PayloadRegistry | None = None


def _default_registry() -> PayloadRegistry:
    global _registry
    if _registry is None:
        _registry = PayloadRegistry()
        from . import builtins  # noqa: PLC0415

        builtins.register_builtins(_registry)
        _install_resolver()
    return _registry


def _install_resolver() -> None:
    def _resolver(type_key: str, value: dict[str, Any]) -> Payload:
        return registry().validate_payload(type_key, value)

    set_payload_resolver(_resolver)


def registry() -> PayloadRegistry:
    """Return the process-wide default payload registry (lazily seeded)."""
    return _default_registry()


# -- convenience public API -------------------------------------------------


def register_payload(type_key: str, model: type[Payload]) -> None:
    """Register a payload model on the default registry."""
    registry().register(type_key, model)


def get_payload_model(type_key: str) -> type[Payload]:
    """Return the payload model for ``type_key`` from the default registry."""
    return registry().get(type_key)


def envelope_for(envelope_cls: type[E], type_key: str, data: dict[str, Any]) -> E:
    """Build a typed envelope via the default registry."""
    return registry().envelope_for(envelope_cls, type_key, data)
