"""Base contract types: payloads, provenance, and the generic envelope."""
from __future__ import annotations

import datetime as _dt
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


class ContractModel(BaseModel):
    """Base for all data contracts in the framework.

    Contracts are immutable and strict: unknown fields are rejected so that
    misspelled fields fail loudly instead of silently corrupting research data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Payload(ContractModel):
    """Marker base class for all typed payloads carried by envelopes.

    Concrete payload models are registered per ``type_key`` in the payload
    registry (``core.registry.payload_registry``). Core code never switches on
    concrete payload types; it always operates on envelopes and the registry.
    """


class Provenance(ContractModel):
    """Who produced a contract and from what inputs."""

    run_id: str | None = None
    stage: str | None = None
    stage_version: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    created_at: _dt.datetime = Field(default_factory=lambda: _dt.datetime.now(_dt.UTC))


PayloadT = TypeVar("PayloadT", bound=Payload)

# Optional hook: the payload registry installs a resolver that validates a raw
# dict payload against the model registered for the envelope's ``type_key``.
# Contracts stay dependency-free; without the registry, dict payloads are not
# resolvable (construct envelopes through ``core.registry``).
_PayloadResolver = Any


def _default_payload_resolver(type_key: str, value: Any) -> Any:
    return value


_payload_resolver: _PayloadResolver = _default_payload_resolver


def set_payload_resolver(resolver: _PayloadResolver) -> None:
    """Install the payload resolver (used by ``core.registry``)."""
    global _payload_resolver
    _payload_resolver = resolver


class Envelope(ContractModel, Generic[PayloadT]):
    """Envelope carrying a typed payload — the dataset-independent carrier.

    The ``type_key`` discriminates payload semantics (e.g. ``nl2sql``,
    ``nl2vis``, ``decision``) and must be registered in the payload registry so
    payloads can be validated without the core knowing their concrete type.

    Construct envelopes through the registry helpers
    (``core.registry.payload_registry``), which validate the payload strictly
    against the registered model for ``type_key``.
    """

    envelope_version: int = 1
    type_key: str
    payload: PayloadT
    provenance: Provenance | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form, non-semantic metadata (adapter labels etc.).",
    )

    @model_validator(mode="before")
    @classmethod
    def _resolve_payload(cls, data: Any) -> Any:
        """Resolve a raw dict payload through the registered payload resolver."""
        if (
            isinstance(data, dict)
            and isinstance(data.get("type_key"), str)
            and isinstance(data.get("payload"), dict)
        ):
            data = {
                **data,
                "payload": _payload_resolver(data["type_key"], data["payload"]),
            }
        return data

    @model_serializer(mode="wrap")
    def _serialize_concrete_payload(self, handler: Any) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if isinstance(self.payload, Payload):
            data["payload"] = self.payload.model_dump()
        return data
