"""Surface B AI-annotation driver (M1.5, docs/19 §7; docs/13 §7 analog).

Composes the hand-authored annotation content (``ai_annotation_content.py``)
with the frozen deterministic selection (``selection.py``), the candidate pool
texts, the annotation machinery (``build_record``/``find_phrase_offsets``),
and the QC tooling into a repeatable CLI that emits the batch-1 labels::

    python -m eaa.experiments.surface_b_ai_annotation
    python -m eaa.experiments.surface_b_ai_annotation --out data/annotations/surface_b/batch-1

The run is the AI-annotation judgment pass: there are no human annotators or
external LLM API in this environment, so every label records AI provenance
(``annotation_source=ai_generated``, ``backend=opencode/big-pickle``) and
never claims human authorship, κ, or adjudication. No gold field is read
(ADR-009) and no legitimate ``enrichment.json`` exists, so the 15
metadata-closable questions are recorded with their ambiguity span and
``resolution_channel=metadata`` but resolution is deferred
(``metadata_resolution=false``, notes mark the deferral).

Output layout (``data/annotations/surface_b/batch-1/``, docs/19 §7):

- ``dw/<question_id>.json``: one ``annotation-schema-v1`` label per question.
- ``provenance-v1.json``: the Option B sidecar, one entry per question
  (``annotator_ids=["ai_generated"]``, ``token=null``).
- ``ai-annotation-run.json``: the run record (source, selection, counts,
  validation result). Not a label file; excluded from the freeze hash.

The driver then validates the batch with ``load_batch`` and reports every
docs/19 §9 violation it finds — it never silently repairs or fabricates.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eaa.ambiguity_resolution.annotations import (
    PROTOCOL_VERSION,
    AnnotationPrepError,
    freeze_batch,
    load_batch,
    write_lock,
)
from eaa.ambiguity_resolution.annotations._io import write_json
from eaa.ambiguity_resolution.annotations.ai_annotation import build_record
from eaa.ambiguity_resolution.annotations.ai_annotation_content import (
    AI_ANNOTATION_BACKEND,
    AI_ANNOTATION_SOURCE,
    AI_PROVENANCE_PREFIX,
    content_for,
    selection_order,
)
from eaa.ambiguity_resolution.annotations.models import AnnotationRecord
from eaa.ambiguity_resolution.annotations.provenance import (
    PROVENANCE_VERSION,
    EnrichmentSnapshot,
    ProvenanceSidecar,
    write_sidecar,
)
from eaa.ambiguity_resolution.annotations.selection import select_batch, selection_summary
from eaa.ambiguity_resolution.candidates import load_candidates

DEFAULT_CANDIDATES = Path("data/annotations/surface_b/candidates.json")
DEFAULT_BATCH_ROOT = Path("data/annotations/surface_b/batch-1")
DEFAULT_LOCK = Path("data/annotations/surface_b/surface_b.v1.lock")
DEFAULT_DATA_ROOT = Path("data/annotations/surface_b")

#: Real annotator identity for the AI-annotation run (docs/19 §8 annotator_ids
#: must be non-empty real values; ``ai_generated`` is this run's identity).
AI_ANNOTATOR_ID = "ai_generated"

#: Persistent families this run can establish from reasoning alone (docs/19
#: §4.2 minus the L/V "metadata-present-but-not-decisive" cases, which are
#: deferred because no legitimate ``enrichment.json`` exists).
REASONING_FAMILIES: tuple[str, ...] = ("S", "R", "C", "T", "K", "I")

#: Paper 1 evaluation-mode statement recorded in the run record (docs/19 §11).
EVALUATION_MODE = (
    "Paper 1 current evaluation mode = reasoning-based ambiguity detection "
    "with metadata-aware persistence deferred because no legitimate "
    "enrichment source is available; missing metadata is never converted into "
    "fabricated metadata-grounded evidence."
)

#: Freeze-record annotation/metadata modes (docs/19 §1.5; never human gold).
ANNOTATION_MODE = "AI/model-based"
METADATA_MODE = "deferred"

#: Prompt/guidelines version the labels were produced under (recorded in the
#: freeze lock so the frozen artifact names its generation procedure exactly).
PROMPT_VERSION = (
    "annotation-guidelines-v1 (docs/13 §7 + docs/19 §7; "
    "content=ai_annotation_content.py; schema=annotation-schema-v1)"
)


def _compose_notes(content: dict[str, Any]) -> str:
    """Prepend the AI provenance marker to the authored content notes."""
    note = content.get("notes")
    if note:
        return f"{AI_PROVENANCE_PREFIX}{note}"
    return AI_PROVENANCE_PREFIX.rstrip()


def _serialize(record: AnnotationRecord) -> dict[str, Any]:
    """Serialize a validated record to the flat label-file JSON (loader shape)."""
    question = record.question
    return {
        "schema_version": record.schema_version,
        "question_id": question.question_id,
        "question_text": question.question_text,
        "database_id": question.database_id,
        "answerability": {
            "label": question.answerability.label.value,
            "confidence": question.answerability.confidence,
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
            for span in question.spans
        ],
        "interpretations": (
            {
                key: {"sql": value.sql, "note": value.note}
                for key, value in record.interpretations.items()
            }
            if record.interpretations is not None
            else None
        ),
        "notes": record.notes,
    }


def _build_records(pool: Any) -> list[AnnotationRecord]:
    """Build one validated record per frozen selection id, in selection order."""
    by_id = {record.question_id: record for record in pool.candidates}
    records: list[AnnotationRecord] = []
    for question_id in selection_order():
        candidate = by_id.get(question_id)
        if candidate is None:
            raise AnnotationPrepError(
                f"selected question {question_id!r} absent from the candidate pool"
            )
        content = content_for(question_id)
        record = build_record(
            question_id=question_id,
            question_text=candidate.question,
            database_id=candidate.database_id,
            answerability="answerable",
            confidence=1.0,
            spans=content["spans"],
            readings=content.get("readings"),
            notes=_compose_notes(content),
        )
        records.append(record)
    return records


def _verify_selection(pool: Any) -> dict[str, Any]:
    """Cross-check the frozen order against ``select_batch``; return its summary."""
    selection = select_batch(pool)
    selected_ids = {row["question_id"] for row in selection}
    frozen_ids = set(selection_order())
    if selected_ids != frozen_ids:
        raise AnnotationPrepError(
            "frozen selection order disagrees with select_batch: "
            f"only-in-select_batch={sorted(selected_ids - frozen_ids)[:5]} "
            f"only-in-frozen={sorted(frozen_ids - selected_ids)[:5]}"
        )
    return selection_summary(selection)


def _build_sidecar(records: Sequence[AnnotationRecord]) -> dict[str, dict[str, Any]]:
    """Build the Option B sidecar: AI-annotator identity, no enrichment token."""
    entries: dict[str, dict[str, Any]] = {}
    for record in records:
        question_id = record.question.question_id
        entry = ProvenanceSidecar(
            question_id=question_id,
            annotator_ids=[AI_ANNOTATOR_ID],
            third_annotator_id=None,
            enrichment_snapshot=EnrichmentSnapshot(
                database_id=record.question.database_id, token=None
            ),
        )
        entries[question_id] = entry.model_dump()
    return entries


def _counts(records: Sequence[AnnotationRecord]) -> dict[str, Any]:
    """Aggregate span/code counts for the run record (advisory only)."""
    codes: Counter[str] = Counter()
    spans_with_readings = 0
    for record in records:
        for span in record.question.spans:
            codes[span.ambiguity_type.value] += 1
        if record.interpretations is not None:
            spans_with_readings += 1
    return {
        "num_questions": len(records),
        "num_spans": sum(codes.values()),
        "num_interpretation_records": spans_with_readings,
        "codes": dict(sorted(codes.items())),
    }


def _run(out: Path) -> int:
    pool = load_candidates(DEFAULT_CANDIDATES)
    selection_summary_payload = _verify_selection(pool)

    records = _build_records(pool)
    label_dir = out / "dw"
    for record in records:
        write_json(_serialize(record), label_dir / f"{record.question.question_id}.json")

    sidecar = _build_sidecar(records)
    write_sidecar(sidecar, out / "provenance-v1.json")

    dataset, problems = load_batch(out, required_families=REASONING_FAMILIES)

    run_record: dict[str, Any] = {
        "artifact": "surface-b-ai-annotation-run",
        "artifact_version": "surface-b-ai-annotation-v1",
        "batch_id": "batch-1",
        "protocol_version": PROTOCOL_VERSION,
        "provenance_version": PROVENANCE_VERSION,
        "annotation_source": AI_ANNOTATION_SOURCE,
        "backend": AI_ANNOTATION_BACKEND,
        "human_gold": False,
        "kappa": None,
        "adjudication": "none",
        "evaluation_mode": EVALUATION_MODE,
        "required_persistent_families": list(REASONING_FAMILIES),
        "selection": selection_summary_payload,
        "counts": _counts(records),
        "validation": {
            "ok": not problems,
            "num_questions": len(dataset.records),
            "problems": problems,
        },
        "notes": (
            "AI-generated annotations: no human annotators, no kappa, no "
            "adjudication; metadata-closable stratum deferred (no legitimate "
            "enrichment.json exists)."
        ),
    }
    write_json(run_record, out / "ai-annotation-run.json")

    print(f"wrote {len(records)} label files to {label_dir}")
    print(f"wrote provenance sidecar to {out / 'provenance-v1.json'}")
    print(f"wrote run record to {out / 'ai-annotation-run.json'}")
    if problems:
        print(f"batch INVALID ({len(problems)} problems):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"batch VALID ({len(dataset.records)} questions)")
    return 0


def _run_freeze(out: Path, lock: Path, data_root: Path) -> int:
    """Freeze the emitted batch without regenerating labels (Phase B).

    Verifies every §9/§8 precondition over the existing label files and
    writes the ``surface_b.v1.lock`` freeze record carrying the AI annotation
    mode, the deferred metadata mode, the backend/model/prompt version, and a
    UTC timestamp. The labels themselves are never rewritten here, so the
    frozen artifact stays immutable.
    """
    record = freeze_batch(
        out,
        batch_id="batch-1",
        data_root=data_root,
        required_families=REASONING_FAMILIES,
    )
    lock_record: dict[str, Any] = {
        **record,
        "annotation_mode": ANNOTATION_MODE,
        "metadata_mode": METADATA_MODE,
        "annotation_source": AI_ANNOTATION_SOURCE,
        "backend": AI_ANNOTATION_BACKEND,
        "prompt_version": PROMPT_VERSION,
        "evaluation_mode": EVALUATION_MODE,
        "human_gold": False,
        "created_at": datetime.now(UTC).isoformat(),
    }
    lock_path = write_lock(lock_record, lock)
    print(f"freeze OK: sha256={record['sha256']}")
    print(f"lock written to {lock_path} ({len(record['files'])} files hashed)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Emit and validate the batch-1 AI annotations; or freeze them; exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m eaa.experiments.surface_b_ai_annotation",
        description=(
            "Emit/validate the batch-1 AI-annotation labels, or freeze them "
            "(docs/19 §7–§8)."
        ),
    )
    parser.add_argument(
        "--out",
        default=str(DEFAULT_BATCH_ROOT),
        help="batch root (labels go under <out>/dw/, docs/19 §7)",
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="freeze the existing batch (no regeneration): validate, hash, write lock",
    )
    parser.add_argument(
        "--lock",
        default=str(DEFAULT_LOCK),
        help="freeze lock output path (default: data/annotations/surface_b/surface_b.v1.lock)",
    )
    parser.add_argument(
        "--data-root",
        default=str(DEFAULT_DATA_ROOT),
        help="surface B data root (for provenance enrichment-token derivation)",
    )
    args = parser.parse_args(argv)
    try:
        if args.freeze:
            return _run_freeze(Path(args.out), Path(args.lock), Path(args.data_root))
        return _run(Path(args.out))
    except (AnnotationPrepError, KeyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


__all__ = [
    "ANNOTATION_MODE",
    "DEFAULT_BATCH_ROOT",
    "DEFAULT_CANDIDATES",
    "DEFAULT_LOCK",
    "EVALUATION_MODE",
    "METADATA_MODE",
    "PROMPT_VERSION",
    "REASONING_FAMILIES",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
