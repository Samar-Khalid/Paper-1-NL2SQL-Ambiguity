"""Surface B candidate pool construction and artifact I/O (docs/19 §5.1).

The pool is a deterministic, gold-free list of every dev-split question from the
benchmark adapter with the transparent selection signals that fired for it
(``signals.py``). It is the screening surface a human research team uses to
build the first annotation batch; it contains **no labels, no interpretations,
no gold fields, and no annotator output** (docs/13, docs/19).

Gold leakage boundary (hard rule, ADR-009): the pool is built from
``TaskEnvelope`` payloads (question + database_id) and ``DatabaseSchema``
objects only. Gold SQL, gold tables, join keys, column mappings, domain
knowledge, and the official benchmark category labels are never read here. The
``GOLD_FIELDS`` set below exists for the artifact's no-gold-leakage tests.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eaa.core.contracts.schema import DatabaseSchema
from eaa.core.contracts.task import TaskEnvelope

from .errors import CandidateSelectionError
from .signals import CANDIDATE_SCHEMA_VERSION, SIGNALS, SignalHit, SignalScorer

#: Field names that must never appear in a candidate record (gold leakage
#: guard used by the artifact tests; the writer never emits them by
#: construction).
GOLD_FIELDS: frozenset[str] = frozenset(
    {
        "sql",
        "oracle_sql",
        "tables",
        "gold_tables",
        "join_keys",
        "column_mapping",
        "mapping",
        "domain_knowledge",
        "sub_questions",
        "sub_sqls",
    }
)

_METHOD_NAME = "structural-textual-candidate-signals"


@dataclass(frozen=True)
class CandidateRecord:
    """One pool entry: a question plus the signals that fired for it."""

    question_id: str
    database_id: str
    question: str
    signals: tuple[SignalHit, ...]


@dataclass(frozen=True)
class CandidatePool:
    """The whole Surface B candidate pool plus provenance metadata."""

    schema_version: str = CANDIDATE_SCHEMA_VERSION
    method: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    candidates: tuple[CandidateRecord, ...] = ()

    def counts_by_database(self) -> dict[str, int]:
        """Return candidate counts per database id, sorted by id."""
        counter = Counter(record.database_id for record in self.candidates)
        return dict(sorted(counter.items()))

    def counts_by_signal(self) -> dict[str, int]:
        """Return the number of candidates each signal fired on, sorted by id."""
        counter: Counter[str] = Counter()
        for record in self.candidates:
            for hit in record.signals:
                counter[hit.signal] += 1
        return dict(sorted(counter.items()))

    def with_any_signal(self) -> int:
        """Return the number of candidates with at least one fired signal."""
        return sum(1 for record in self.candidates if record.signals)

    def without_signal(self) -> int:
        """Return the number of candidates with no fired signal."""
        return len(self.candidates) - self.with_any_signal()


def build_candidate_pool(
    tasks: Iterable[TaskEnvelope],
    schemas: Mapping[str, DatabaseSchema],
    *,
    source: Mapping[str, Any] | None = None,
) -> CandidatePool:
    """Build the candidate pool from task envelopes and per-database schemas.

    Parameters
    ----------
    tasks:
        Dev-split task envelopes; only ``task_id``, ``question`` and
        ``database_id`` are read (gold is never accessed).
    schemas:
        Resolved ``DatabaseSchema`` per database id. A missing id falls back to
        schema-less scoring (textual signals only), e.g. for warehouses whose
        tables are not available locally.
    source:
        Optional provenance metadata recorded in the artifact (e.g. the
        adapter ``DatasetManifest`` extra: data root, checksum, databases).

    Raises
    ------
    CandidateSelectionError:
        If a task carries no question text or no database id.
    """
    scorers: dict[str, SignalScorer] = {}
    records: list[CandidateRecord] = []
    for task in tasks:
        question = getattr(task.payload, "question", None)
        if not isinstance(question, str) or not question:
            raise CandidateSelectionError(
                f"task '{task.header.task_id}' carries no question text"
            )
        database_id = getattr(task.payload, "database_id", None)
        if not isinstance(database_id, str) or not database_id:
            raise CandidateSelectionError(
                f"task '{task.header.task_id}' carries no database_id"
            )
        scorer = scorers.get(database_id)
        if scorer is None:
            scorer = SignalScorer(schemas.get(database_id))
            scorers[database_id] = scorer
        hits = scorer.score(question)
        records.append(
            CandidateRecord(task.header.task_id, database_id, question, hits)
        )

    method = {
        "name": _METHOD_NAME,
        "version": CANDIDATE_SCHEMA_VERSION,
        "description": (
            "Transparent deterministic structural/textual heuristics over the "
            "question text and schema; signals are discovery hints, not labels."
        ),
        "signals": [
            {
                "id": signal.id,
                "name": signal.name,
                "families": list(signal.families),
                "description": signal.description,
            }
            for signal in SIGNALS
        ],
    }
    return CandidatePool(
        schema_version=CANDIDATE_SCHEMA_VERSION,
        method=method,
        source=dict(source or {}),
        candidates=tuple(records),
    )


def candidate_to_dict(record: CandidateRecord) -> dict[str, Any]:
    """Serialize one candidate record (gold-free by construction)."""
    return {
        "question_id": record.question_id,
        "database_id": record.database_id,
        "question": record.question,
        "selection_signals": [
            {"signal": hit.signal, "name": hit.name, "evidence": list(hit.evidence)}
            for hit in record.signals
        ],
    }


def write_candidates(pool: CandidatePool, out_path: Path) -> Path:
    """Write the pool to ``out_path`` as a deterministic JSON artifact.

    The output is byte-for-byte reproducible for the same pool: keys are sorted,
    indentation is fixed, and no wall-clock timestamp is embedded.
    """
    payload: dict[str, Any] = {
        "schema_version": pool.schema_version,
        "method": pool.method,
        "source": pool.source,
        "counts": {
            "total": len(pool.candidates),
            "by_database": pool.counts_by_database(),
            "by_signal": pool.counts_by_signal(),
            "with_any_signal": pool.with_any_signal(),
            "without_signal": pool.without_signal(),
        },
        "candidates": [candidate_to_dict(record) for record in pool.candidates],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return out_path


def load_candidates(path: Path) -> CandidatePool:
    """Load a candidate artifact back into a ``CandidatePool``.

    Raises
    ------
    CandidateSelectionError:
        If the file is not a valid candidate artifact.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateSelectionError(f"{path} is not readable candidate JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise CandidateSelectionError(f"{path} is not a candidate artifact")
    records: list[CandidateRecord] = []
    for entry in payload["candidates"]:
        if not isinstance(entry, dict):
            raise CandidateSelectionError(f"{path} has a malformed candidate record")
        signals = tuple(
            SignalHit(
                str(hit.get("signal")),
                str(hit.get("name")),
                tuple(hit.get("evidence") or ()),
            )
            for hit in entry.get("selection_signals") or []
            if isinstance(hit, dict)
        )
        records.append(
            CandidateRecord(
                question_id=str(entry.get("question_id")),
                database_id=str(entry.get("database_id")),
                question=str(entry.get("question")),
                signals=signals,
            )
        )
    return CandidatePool(
        schema_version=str(payload.get("schema_version", CANDIDATE_SCHEMA_VERSION)),
        method=dict(payload.get("method") or {}),
        source=dict(payload.get("source") or {}),
        candidates=tuple(records),
    )


__all__ = [
    "CANDIDATE_SCHEMA_VERSION",
    "CandidatePool",
    "CandidateRecord",
    "GOLD_FIELDS",
    "build_candidate_pool",
    "candidate_to_dict",
    "load_candidates",
    "write_candidates",
]
