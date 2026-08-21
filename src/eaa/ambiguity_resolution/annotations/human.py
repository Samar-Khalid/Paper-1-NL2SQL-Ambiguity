"""Human Gold annotation machinery for Surface B (M1.5, docs/23).

The batch-1 pilot was AI-generated and frozen (docs/20); a Human Gold reference
set must be produced by a single human annotator (the researcher) and stay
fully separated from that frozen AI pilot. This module provides the
gold-free machinery for that workflow:

- ``build_human_task_list`` recomputes the usable task set from the candidates
  and the frozen batch-1 labels: every batch-1 record that is **not**
  metadata-deferred and **not** unanswerable (i.e. the persistent-ambiguity
  and unambiguous strata). The exact split is derived from the files, never
  hardcoded.
- ``human_task_payload`` strips the operational ``frozen_stratum`` field so
  the UI exposes only question text, database id, schema, and signal hints.
- ``build_human_record`` / ``regenerate_human_records`` turn annotator
  decisions into ``annotation-schema-v1`` records (validated by the frozen
  loader).
- ``validate_human_record`` / ``validate_human_root`` apply the per-record and
  per-root semantic checks, including the hard rule that no metadata-grounded
  label may be recorded without a legitimate enrichment snapshot.
- ``freeze_human_gold`` verifies every precondition and only then writes the
  **separate** ``human-gold.v1.lock``; the frozen AI pilot (``batch-1`` and
  ``surface_b.v1.lock``) is never read for labels, never modified, and never
  hashed together with the Human Gold set.

Honesty rules (docs/23): the sidecar records the researcher as the single
annotator, inter-annotator agreement is documented as unavailable (never a
fabricated second κ), and no adjudication or enrichment is invented.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eaa.ambiguity_resolution.candidates import load_candidates

from ._io import read_json, write_json
from .ai_annotation import build_record
from .batch import EVALUABLE_CODES, PROTOCOL_VERSION
from .errors import AnnotationPrepError
from .loader import AnnotationDatasetLoader
from .models import AnnotationDataset, AnnotationRecord
from .provenance import (
    PLACEHOLDER,
    PROVENANCE_VERSION,
    Adjudication,
    EnrichmentSnapshot,
    derive_enrichment_token,
    load_sidecar,
)
from .qc import (
    HASH_ALGORITHM,
    _collect_annotation_files,
    _collect_gold_field_hits,
    _freeze_digest,
    _is_metadata_deferred,
    _merge_datasets,
    _stratum,
    _stratum_counts,
    write_lock,
)

HUMAN_GOLD_VERSION = "human-gold-v1"

#: The documented, single-annotator provenance note (docs/23 §4). IAA is
#: honestly recorded as not applicable; no second κ is ever fabricated.
IAA_NOTE = (
    "single human annotator (the researcher); a second independent annotator "
    "was not available, so inter-annotator agreement is not applicable"
)

#: Stratum labels whose batch-1 records are usable for Human Gold.
_USABLE_STRATA = frozenset({"persistent_ambiguity", "unambiguous"})


def _candidate_index(candidates_path: str | Path) -> dict[str, Any]:
    """Index candidate records by question id (gold-free fields only)."""
    pool = load_candidates(Path(candidates_path))
    return {record.question_id: record for record in pool.candidates}


def build_human_task_list(
    candidates_path: str | Path,
    batch_root: str | Path,
    *,
    label_root: str | Path | None = None,
) -> dict[str, Any]:
    """Recompute the Human Gold task set from candidates and frozen labels.

    Every batch-1 record is classified by its own frozen labels (docs/23 §1):
    persistent-ambiguity and unambiguous records are usable; metadata-deferred
    and unanswerable records are excluded and listed in ``excluded`` with a
    reason. The split is derived from the label files, not hardcoded.

    Parameters
    ----------
    candidates_path:
        The gold-free candidate pool artifact (question text + signals).
    batch_root:
        The frozen batch-1 root; labels live in ``label_root``.
    label_root:
        Directory whose ``*.json`` files are ``annotation-schema-v1`` labels.
        Defaults to ``batch_root/dw`` (docs/19 §7 nested layout), falling back
        to ``batch_root`` when the ``dw`` subdirectory does not exist.

    Returns
    -------
    dict
        The task list artifact: totals, excluded records, and one row per
        usable task carrying question id, database id, question text, signals,
        and the frozen pilot stratum (operational context only).

    Raises
    ------
    AnnotationPrepError:
        If the label root has no annotation files, or a usable label id is
        absent from the candidate pool (the question could then not be shown).
    """
    root = Path(batch_root)
    labels: Path | None = Path(label_root) if label_root is not None else None
    if labels is None:
        explicit = root / "dw"
        labels = explicit if explicit.is_dir() else root

    loader = AnnotationDatasetLoader()
    try:
        dataset = loader.load(labels)
    except Exception as exc:  # noqa: BLE001 — refuse to guess, report the cause
        raise AnnotationPrepError(
            f"cannot load frozen batch-1 labels from {labels}: {exc}"
        ) from exc
    if not dataset.records:
        raise AnnotationPrepError(f"no annotation records found under {labels}")

    by_id = _candidate_index(candidates_path)
    tasks: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    totals: dict[str, int] = {
        "persistent_ambiguity": 0,
        "unambiguous": 0,
        "metadata_deferred": 0,
        "unanswerable": 0,
    }
    for record in dataset.records:
        question_id = record.question.question_id
        stratum = _stratum(record)
        if stratum == "metadata_closable":
            stratum_label = "metadata_deferred"
            excluded.append(
                {
                    "question_id": question_id,
                    "stratum": stratum_label,
                    "reason": (
                        "resolution deferred in the frozen pilot because no "
                        "legitimate enrichment source exists (docs/19 §11)"
                    ),
                }
            )
            totals["metadata_deferred"] += 1
            continue
        if stratum == "unanswerable":
            excluded.append(
                {
                    "question_id": question_id,
                    "stratum": stratum,
                    "reason": "unanswerable records are outside the batch-1 design",
                }
            )
            totals["unanswerable"] += 1
            continue
        totals[stratum] += 1
        if stratum not in _USABLE_STRATA:
            continue
        candidate = by_id.get(question_id)
        if candidate is None:
            raise AnnotationPrepError(
                f"usable label id {question_id!r} is absent from the candidate pool "
                f"{candidates_path}; the question text cannot be shown"
            )
        tasks.append(
            {
                "question_id": question_id,
                "database_id": record.question.database_id,
                "question": candidate.question,
                "signals": [
                    {"signal": hit.signal, "name": hit.name, "evidence": list(hit.evidence)}
                    for hit in candidate.signals
                ],
                "frozen_stratum": stratum,
            }
        )

    tasks.sort(key=lambda item: item["question_id"])
    excluded.sort(key=lambda item: item["question_id"])
    return {
        "artifact": "surface-b-human-gold-task-list",
        "artifact_version": HUMAN_GOLD_VERSION,
        "source": {
            "batch_id": "batch-1",
            "batch_root": str(root),
            "label_root": str(labels),
            "candidates": str(candidates_path),
        },
        "protocol_version": PROTOCOL_VERSION,
        "gold_excluded": True,
        "annotator_note": IAA_NOTE,
        "selection_rule": (
            "usable = frozen batch-1 records in the persistent-ambiguity or "
            "unambiguous strata; metadata-deferred and unanswerable records "
            "are excluded"
        ),
        "totals": {
            "usable": len(tasks),
            "persistent_ambiguity": totals["persistent_ambiguity"],
            "unambiguous": totals["unambiguous"],
            "excluded_metadata_deferred": totals["metadata_deferred"],
            "excluded_unanswerable": totals["unanswerable"],
        },
        "excluded": excluded,
        "tasks": tasks,
    }


def write_human_task_list(task_list: Mapping[str, Any], path: str | Path) -> Path:
    """Write the task list artifact deterministically."""
    return write_json(dict(task_list), path)


def load_human_task_list(path: str | Path) -> dict[str, Any]:
    """Load a task list artifact."""
    payload = read_json(path)
    if not isinstance(payload, dict) or "tasks" not in payload:
        raise AnnotationPrepError(f"{path} is not a human-gold task list artifact")
    return payload


def human_task_payload(task_list: Mapping[str, Any]) -> dict[str, Any]:
    """Strip every gold and stratum field to produce the UI payload.

    The gold-free payload carries only question, database id, and signals; the
    operational ``frozen_stratum`` field is removed so the annotator is not
    anchored to the AI pilot's stratum judgment (docs/23 §2).
    """
    return {
        "artifact": "surface-b-human-gold-ui-payload",
        "gold_excluded": True,
        "tasks": [
            {
                "question_id": task["question_id"],
                "database_id": task["database_id"],
                "question": task["question"],
                "signals": task["signals"],
            }
            for task in task_list["tasks"]
        ],
    }


def build_human_record(
    *,
    question_id: str,
    question_text: str,
    database_id: str,
    answerability: str = "answerable",
    confidence: float = 1.0,
    spans: Sequence[Mapping[str, object]] = (),
    readings: Mapping[str, Mapping[str, str]] | None = None,
    notes: str | None = None,
) -> AnnotationRecord:
    """Build a validated Human Gold ``AnnotationRecord`` from decisions.

    Delegates to the shared record builder so the frozen loader contract
    (span bounds/text integrity, dual readings) is enforced on every record the
    annotator produces.
    """
    return build_record(
        question_id=question_id,
        question_text=question_text,
        database_id=database_id,
        answerability=answerability,
        confidence=confidence,
        spans=spans,
        readings=readings,
        notes=notes,
    )


def record_to_flat_dict(record: AnnotationRecord) -> dict[str, Any]:
    """Serialize a record in the flat ``annotation-schema-v1`` file shape."""
    return {
        "schema_version": record.schema_version,
        "question_id": record.question.question_id,
        "question_text": record.question.question_text,
        "database_id": record.question.database_id,
        "answerability": {
            "label": record.question.answerability.label.value,
            "confidence": record.question.answerability.confidence,
        },
        "spans": [
            {
                "span_id": span.span_id,
                "text": span.text,
                "start": span.start,
                "end": span.end,
                "ambiguity_type": span.ambiguity_type.value,
                "metadata_resolution": span.metadata_resolution,
                "clarification_required": span.clarification_required,
                "assumption_risk": span.assumption_risk.value,
                "resolution_channel": span.resolution_channel.value,
            }
            for span in record.question.spans
        ],
        "interpretations": (
            {
                "sql_reading_A": {
                    "sql": record.interpretations["sql_reading_A"].sql,
                    "note": record.interpretations["sql_reading_A"].note,
                },
                "sql_reading_B": {
                    "sql": record.interpretations["sql_reading_B"].sql,
                    "note": record.interpretations["sql_reading_B"].note,
                },
            }
            if record.interpretations is not None
            else None
        ),
        "notes": record.notes,
    }


def validate_human_record(
    record: AnnotationRecord,
    *,
    enrichment_token: str | None = None,
) -> list[str]:
    """Semantic checks for one Human Gold record; empty means valid.

    Adds the Human Gold rules on top of the frozen loader contract: evaluable
    span codes only, interpretations matching the strict-ambiguity state,
    distinct SQL readings, and the hard rule that a metadata-grounded label
    (``metadata_resolution`` asserted) requires a legitimate enrichment token.
    """
    question = record.question
    qid = question.question_id
    problems: list[str] = []
    spans = question.spans

    if question.answerability.label.value == "unanswerable":
        if spans:
            problems.append(
                f"{qid}: unanswerable record must carry no ambiguity spans "
                "(U1-U4 are answerability labels, never span codes)"
            )
        if record.interpretations is not None:
            problems.append(
                f"{qid}: unanswerable record must not carry SQL interpretations"
            )
        return problems

    for span in spans:
        code = span.ambiguity_type.value
        if code not in EVALUABLE_CODES:
            problems.append(
                f"{qid}: span {span.span_id!r} uses non-evaluable code {code} "
                "(L1/C4/I1/U1-U4 are not valid Human Gold span codes)"
            )
        if span.metadata_resolution and enrichment_token is None:
            problems.append(
                f"{qid}: span {span.span_id!r} asserts metadata_resolution but "
                "no legitimate enrichment snapshot is available; metadata-"
                "grounded labels require a cited enrichment entry (docs/19 §8, "
                "docs/23 §3)"
            )

    strict = any(not _is_metadata_deferred(span) for span in spans)
    readings = record.interpretations
    if strict and readings is None:
        problems.append(
            f"{qid}: strict-ambiguity span present but interpretations "
            "(sql_reading_A/B) missing"
        )
    if not strict and readings is not None:
        problems.append(
            f"{qid}: interpretations present without a strict-ambiguity span"
        )
    if readings is not None and readings["sql_reading_A"].sql == readings["sql_reading_B"].sql:
        problems.append(f"{qid}: the two SQL readings are identical")
    return problems


def build_human_provenance(
    question_ids: Sequence[str],
    *,
    database_id: str,
    annotator_id: str,
    enrichment_token: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the honest single-annotator sidecar entries (docs/23 §4).

    Every entry identifies the researcher as the only annotator, marks the set
    as ``human_gold``, and records that inter-annotator agreement is not
    applicable. No second annotator, adjudication, or enrichment is invented.
    """
    if not annotator_id or annotator_id == PLACEHOLDER:
        raise AnnotationPrepError("annotator_id must be a real researcher id")
    entries: dict[str, dict[str, Any]] = {}
    for question_id in sorted(set(question_ids)):
        entry = {
            "provenance_version": PROVENANCE_VERSION,
            "question_id": question_id,
            "annotator_ids": [annotator_id],
            "third_annotator_id": None,
            "protocol_version": PROTOCOL_VERSION,
            "enrichment_snapshot": EnrichmentSnapshot(
                database_id=database_id, token=enrichment_token
            ).model_dump(),
            "adjudication": Adjudication().model_dump(),
            "annotation_source": "human",
            "human_gold": True,
            "inter_annotator_agreement": {
                "available": False,
                "reason": IAA_NOTE,
            },
        }
        entries[question_id] = entry
    return entries


def write_human_provenance(
    entries: Mapping[str, Any], path: str | Path
) -> Path:
    """Write the human sidecar deterministically."""
    return write_json(dict(entries), path)


def _enrichment_tokens(
    data_root: str | Path | None, database_ids: Sequence[str]
) -> dict[str, str | None]:
    """Resolve the enrichment snapshot token per database (None when absent)."""
    if data_root is None:
        return {database_id: None for database_id in database_ids}
    tokens: dict[str, str | None] = {}
    for database_id in sorted(set(database_ids)):
        token, _ = derive_enrichment_token(Path(data_root), database_id)
        tokens[database_id] = token
    return tokens


def _sidecar_problems(
    dataset: AnnotationDataset,
    sidecar: Mapping[str, dict[str, Any]],
    *,
    annotator_id: str,
) -> list[str]:
    """Cross-check the human sidecar against the labels (docs/23 §4)."""
    problems: list[str] = []
    label_ids = {record.question.question_id for record in dataset.records}
    sidecar_ids = set(sidecar)
    if label_ids != sidecar_ids:
        only_labels = label_ids - sidecar_ids
        only_sidecar = sidecar_ids - label_ids
        if only_labels:
            problems.append(
                f"labels without sidecar entries: {sorted(only_labels)[:5]}"
            )
        if only_sidecar:
            problems.append(
                f"sidecar entries without labels: {sorted(only_sidecar)[:5]}"
            )

    records_by_id = {
        record.question.question_id: record for record in dataset.records
    }
    for question_id, entry in sorted(sidecar.items()):
        entry_problems: list[str] = []
        if entry.get("provenance_version") != PROVENANCE_VERSION:
            entry_problems.append(
                f"bad provenance_version {entry.get('provenance_version')!r}"
            )
        if entry.get("protocol_version") != PROTOCOL_VERSION:
            entry_problems.append(
                f"bad protocol_version {entry.get('protocol_version')!r}"
            )
        if entry.get("annotation_source") != "human":
            entry_problems.append(
                f"annotation_source {entry.get('annotation_source')!r} != 'human'"
            )
        if entry.get("human_gold") is not True:
            entry_problems.append("human_gold must be true for the Human Gold set")
        if entry.get("annotator_ids") != [annotator_id]:
            entry_problems.append(
                f"annotator_ids {entry.get('annotator_ids')!r} != single human "
                f"annotator {annotator_id!r}"
            )
        iaa = entry.get("inter_annotator_agreement") or {}
        if iaa.get("available") is not False:
            entry_problems.append(
                "inter_annotator_agreement must be documented as unavailable "
                "for a single-annotator set"
            )
        snapshot = entry.get("enrichment_snapshot") or {}
        record = records_by_id.get(question_id)
        if (
            record is not None
            and snapshot.get("database_id") != record.question.database_id
        ):
            entry_problems.append(
                f"enrichment_snapshot.database_id {snapshot.get('database_id')!r} "
                f"!= label database_id {record.question.database_id!r}"
            )
        if entry_problems:
            problems.append(f"{question_id}: " + "; ".join(entry_problems))
    return problems


def validate_human_root(
    root: str | Path,
    *,
    annotator_id: str,
    data_root: str | Path | None = None,
    task_list: Mapping[str, Any] | None = None,
) -> tuple[AnnotationDataset | None, list[str]]:
    """Validate a Human Gold annotation root; return ``(dataset, problems)``.

    Runs the frozen loader per file, the per-record semantic checks, the
    sidecar cross-checks, and (when a task list is supplied) the completeness
    requirement that the annotated set matches the task set exactly. Gold-field
    leakage is scanned on the serialized files (ADR-009).
    """
    root_path = Path(root)
    if not root_path.is_dir():
        return None, [f"human-gold root does not exist: {root_path}"]
    annotation_files = _collect_annotation_files(root_path)
    if not annotation_files:
        return None, [f"no human annotation files found under {root_path}"]

    loader = AnnotationDatasetLoader()
    try:
        dataset = _merge_datasets(
            loader.load(path) for path in annotation_files
        )
    except Exception as exc:  # noqa: BLE001 — report, do not repair
        return None, [f"human annotation validation failed: {exc}"]

    problems: list[str] = []
    tokens = _enrichment_tokens(
        data_root, [record.question.database_id for record in dataset.records]
    )
    for record in dataset.records:
        problems.extend(
            validate_human_record(
                record,
                enrichment_token=tokens.get(record.question.database_id),
            )
        )

    sidecar_path = root_path / "provenance-v1.json"
    if not sidecar_path.is_file():
        problems.append(f"human provenance sidecar missing: {sidecar_path.name}")
    else:
        try:
            sidecar = load_sidecar(sidecar_path)
            problems.extend(
                _sidecar_problems(dataset, sidecar, annotator_id=annotator_id)
            )
        except (OSError, ValueError, TypeError) as exc:
            problems.append(f"human provenance sidecar unreadable: {exc}")

    if task_list is not None:
        task_ids = {task["question_id"] for task in task_list["tasks"]}
        label_ids = {record.question.question_id for record in dataset.records}
        missing = task_ids - label_ids
        extra = label_ids - task_ids
        if missing:
            problems.append(
                f"task set incomplete: {len(missing)} tasks not yet annotated "
                f"({sorted(missing)[:5]})"
            )
        if extra:
            problems.append(
                f"annotations for ids outside the task set: {sorted(extra)[:5]}"
            )

    problems.extend(_collect_gold_field_hits(root_path))
    return dataset, problems


def regenerate_human_records(
    task_list: Mapping[str, Any],
    meta_root: str | Path,
    annotations_root: str | Path,
) -> list[Path]:
    """Regenerate the derived annotation files from the meta source-of-truth.

    The ``meta`` directory holds the raw annotator decisions (the source of
    truth); the ``annotations`` directory holds the derived, validated
    ``annotation-schema-v1`` files the freeze hashes. Regenerating at any time
    keeps both consistent. Annotator identity is stamped in the provenance
    sidecar, never in the derived files.
    """
    meta_path = Path(meta_root)
    annotation_path = Path(annotations_root)
    tasks = {task["question_id"]: task for task in task_list["tasks"]}
    meta_files = sorted(meta_path.glob("*.json"))
    written: list[Path] = []
    for meta_file in meta_files:
        question_id = meta_file.stem
        task = tasks.get(question_id)
        if task is None:
            raise AnnotationPrepError(
                f"meta decision for unknown task {question_id!r}"
            )
        decision = read_json(meta_file)
        if not isinstance(decision, dict):
            raise AnnotationPrepError(
                f"meta decision {meta_file} is not a JSON object"
            )
        answerability = decision.get("answerability") or {}
        record = build_human_record(
            question_id=question_id,
            question_text=task["question"],
            database_id=task["database_id"],
            answerability=str(answerability.get("label", "answerable")),
            confidence=float(answerability.get("confidence", 1.0)),
            spans=decision.get("spans", []),
            readings=decision.get("interpretations"),
            notes=decision.get("notes"),
        )
        target = annotation_path / f"{question_id}.json"
        write_json(record_to_flat_dict(record), target)
        written.append(target)
    return written


def freeze_human_gold(
    *,
    root: str | Path,
    annotator_id: str,
    lock_path: str | Path,
    data_root: str | Path | None = None,
    task_list: Mapping[str, Any] | None = None,
    provenance_filename: str = "provenance-v1.json",
) -> dict[str, Any]:
    """Verify every Human Gold precondition and, if all hold, write the lock.

    The SHA-256 is computed only over the Human Gold label files and its own
    provenance sidecar, in sorted relative path order (same rule as docs/19 §8,
    recorded in ``HASH_ALGORITHM``). The frozen AI pilot (``batch-1`` and
    ``surface_b.v1.lock``) is never hashed here and never modified; the lock is
    written to ``lock_path`` (by default the separate ``human-gold.v1.lock``).

    Raises
    ------
    AnnotationPrepError:
        If any precondition fails, listing every violation.
    """
    dataset, problems = validate_human_root(
        root,
        annotator_id=annotator_id,
        data_root=data_root,
        task_list=task_list,
    )
    if problems:
        raise AnnotationPrepError(
            "human-gold freeze preconditions not met:\n  - "
            + "\n  - ".join(problems)
        )
    if dataset is None:
        raise AnnotationPrepError(
            "human-gold freeze preconditions not met: no validated labels"
        )

    root_path = Path(root)
    sidecar_path = root_path / provenance_filename
    if not sidecar_path.is_file():
        raise AnnotationPrepError(
            "human-gold freeze preconditions not met: provenance sidecar missing"
        )
    files = sorted(_collect_annotation_files(root_path) + [sidecar_path])
    digest = _freeze_digest(
        [path.relative_to(root_path) for path in files], base=root_path
    )
    record = {
        "lock_version": HUMAN_GOLD_VERSION,
        "annotation_mode": "human",
        "annotation_source": "human",
        "human_gold": True,
        "annotator_id": annotator_id,
        "inter_annotator_agreement": {
            "available": False,
            "reason": IAA_NOTE,
        },
        "source_batch": "batch-1",
        "separate_from_ai_pilot": True,
        "protocol_version": PROTOCOL_VERSION,
        "schema_version": PROTOCOL_VERSION,
        "provenance_version": PROVENANCE_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "sha256": digest,
        "num_questions": len(dataset.records),
        "strata": _stratum_counts(dataset),
        "files": [str(path.relative_to(root_path)) for path in files],
    }
    write_lock(record, lock_path)
    return record


__all__ = [
    "HUMAN_GOLD_VERSION",
    "IAA_NOTE",
    "build_human_provenance",
    "build_human_record",
    "build_human_task_list",
    "freeze_human_gold",
    "human_task_payload",
    "load_human_task_list",
    "record_to_flat_dict",
    "regenerate_human_records",
    "validate_human_record",
    "validate_human_root",
    "write_human_provenance",
    "write_human_task_list",
]
