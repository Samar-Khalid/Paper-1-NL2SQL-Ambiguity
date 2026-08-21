"""Quality control and freeze tooling for a Surface B annotation batch.

Two entry points, both read-only (they never modify, repair, or fabricate
annotation data):

- ``validate_batch`` applies the docs/19 §9 acceptance criteria to a loaded
  ``AnnotationDataset`` and returns the list of violations (empty == valid).
- ``freeze_batch`` runs every precondition — files exist, batch complete,
  labels valid, provenance 1:1 and real, enrichment verifiable when
  metadata-grounded labels exist, no gold leakage — and only then computes the
  deterministic SHA-256 over the label files and the provenance sidecar
  (docs/19 §8). It refuses to manufacture anything that is missing.

The underlying ``AnnotationDatasetLoader`` (frozen, docs/13 §5) validates the
record/spans/interpretation contract; this module adds the batch-level and
freeze-level checks that the protocol requires on top of it. Loading follows
the frozen loader per annotation file, so the nested ``dw/dev/...`` layout
(docs/19 §7) is handled without any loader change.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from eaa.ambiguity_resolution.candidates import GOLD_FIELDS

from ._io import write_json
from .batch import (
    BATCH1_TARGET,
    BATCH_ID,
    EVALUABLE_CODES,
    MAX_SPANS_PER_FAMILY,
    PERSISTENT_SPAN_TARGETS,
    PROTOCOL_VERSION,
    STRATUM_TARGETS,
)
from .errors import AnnotationPrepError
from .loader import AnnotationDatasetLoader
from .models import AnnotationDataset, AnnotationRecord, AnnotationSpan
from .provenance import (
    PLACEHOLDER,
    PROVENANCE_VERSION,
    derive_enrichment_token,
    load_sidecar,
)

FAMILIES: tuple[str, ...] = ("L", "S", "R", "V", "C", "T", "K", "I")

HASH_ALGORITHM = "sha256(concat(relpath + \\0 + file_bytes) sorted by relpath)"


def _is_metadata_deferred(span: AnnotationSpan) -> bool:
    """Whether a span is a metadata-dependent span whose resolution is deferred.

    The deferred metadata-closable representation (used by the reasoning-only /
    metadata-deferred AI-annotation run, docs/19 §11) records a genuine
    ambiguity span with ``resolution_channel == "metadata"``, resolution **not**
    asserted (``metadata_resolution`` is ``False``), and no clarification
    requested. This is distinct from a genuine reasoning (strict) span, which
    uses ``resolution_channel == "clarification"`` and requests clarification;
    deferred spans must never be counted as successfully metadata-resolved.
    """
    return (
        span.resolution_channel.value == "metadata"
        and not span.metadata_resolution
        and not span.clarification_required
    )


def _stratum(record: AnnotationRecord) -> str:
    """Classify a record into a batch-1 stratum from its labels."""
    if record.question.answerability.label.value == "unanswerable":
        return "unanswerable"
    spans = record.question.spans
    if not spans:
        return "unambiguous"
    if all(_is_metadata_deferred(span) for span in spans):
        return "metadata_closable"
    if any(not span.metadata_resolution for span in spans):
        return "persistent_ambiguity"
    return "metadata_closable"


def validate_batch(
    dataset: AnnotationDataset,
    *,
    batch_target: int = BATCH1_TARGET,
    stratum_targets: Mapping[str, int] = STRATUM_TARGETS,
    max_spans_per_family: int = MAX_SPANS_PER_FAMILY,
    required_families: Sequence[str] | None = None,
) -> list[str]:
    """Apply the docs/19 §9 acceptance criteria; return violations (empty = valid).

    The loader already enforces schema version, span bounds/text integrity,
    unique ``question_id``, and the presence of both readings when
    interpretations exist; this adds the batch-level checks the protocol
    requires on top of it.

    ``required_families`` is the set of families that must appear in the
    persistent (reasoning) stratum. It defaults to all eight families
    (docs/19 §4.2) for the human-annotated workflow; the reasoning-only /
    metadata-deferred run passes the six reasoning families (S, R, C, T, K, I)
    because the L/V "metadata-present-but-not-decisive" cases are deferred when
    no legitimate ``enrichment.json`` exists (docs/19 §4.3, §11). The per-family
    span cap counts only persistent-stratum spans: deferred metadata-closable
    spans are candidates, not resolved reasoning spans, so they must not push a
    family over the allocation cap.
    """
    problems: list[str] = []
    if len(dataset.records) != batch_target:
        problems.append(
            f"batch size {len(dataset.records)} != target {batch_target}"
        )
    required = tuple(required_families) if required_families is not None else FAMILIES

    family_counts: dict[str, int] = {}
    for record in dataset.records:
        stratum = _stratum(record)
        for span in record.question.spans:
            family = span.ambiguity_type.value[0]
            if stratum == "persistent_ambiguity":
                family_counts[family] = family_counts.get(family, 0) + 1
            if span.ambiguity_type.value not in EVALUABLE_CODES:
                problems.append(
                    f"{record.question.question_id}: span {span.span_id!r} uses "
                    f"non-evaluable code {span.ambiguity_type.value} "
                    f"(L1/C4/I1/U1-U4 are not valid batch labels)"
                )

        strict = any(not span.metadata_resolution for span in record.question.spans)
        has_interpretations = record.interpretations is not None
        if strict and not has_interpretations:
            problems.append(
                f"{record.question.question_id}: strict-ambiguity span present but "
                f"interpretations missing"
            )
        if not strict and has_interpretations:
            problems.append(
                f"{record.question.question_id}: interpretations present without a "
                f"strict-ambiguity span"
            )
        if record.interpretations is not None:
            readings = record.interpretations
            if readings["sql_reading_A"].sql == readings["sql_reading_B"].sql:
                problems.append(
                    f"{record.question.question_id}: the two SQL readings are identical"
                )
        if _stratum(record) == "unanswerable":
            problems.append(
                f"{record.question.question_id}: unanswerable records are outside "
                f"the batch-1 design (15/30/15 strata)"
            )

    strata = _stratum_counts(dataset)
    for name, target in sorted(stratum_targets.items()):
        actual = strata.get(name, 0)
        if actual != target:
            problems.append(
                f"stratum {name!r}: {actual} != target {target}"
            )

    persistent_families = {
        span.ambiguity_type.value[0]
        for record in dataset.records
        if _stratum(record) == "persistent_ambiguity"
        for span in record.question.spans
        if not span.metadata_resolution
    }
    missing = set(required) - persistent_families
    if missing:
        problems.append(
            f"persistent-ambiguity stratum misses families: {sorted(missing)}"
        )

    for family, count in sorted(family_counts.items()):
        if count > max_spans_per_family:
            problems.append(
                f"family {family!r} has {count} spans > cap {max_spans_per_family}"
            )
    return problems


def _stratum_counts(dataset: AnnotationDataset) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in dataset.records:
        stratum = _stratum(record)
        counts[stratum] = counts.get(stratum, 0) + 1
    return counts


def batch_report(dataset: AnnotationDataset) -> dict[str, Any]:
    """Advisory construction report (strata + family totals vs §4 targets)."""
    return {
        "num_questions": len(dataset.records),
        "strata": _stratum_counts(dataset),
        "stratum_targets": dict(STRATUM_TARGETS),
        "family_span_targets": dict(PERSISTENT_SPAN_TARGETS),
        "family_span_totals": _family_counts(dataset),
        "family_span_totals_are_targets": False,  # §4.2: starting allocation, not a commitment
        "max_spans_per_family": MAX_SPANS_PER_FAMILY,
    }


def _family_counts(dataset: AnnotationDataset) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in dataset.records:
        for span in record.question.spans:
            family = span.ambiguity_type.value[0]
            counts[family] = counts.get(family, 0) + 1
    return dict(sorted(counts.items()))


def _is_annotation_file(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == PROTOCOL_VERSION
        and "question_id" in payload
    )


def _collect_annotation_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.json")
        if path.is_file() and _is_annotation_file(path)
    )


#: JSON key paths that are legitimate parts of ``annotation-schema-v1`` even
#: though their name matches a gold field: the annotator-written SQL readings.
_ALLOWED_GOLD_NAMED_KEYS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("interpretations", "sql_reading_A", "sql"),
        ("interpretations", "sql_reading_B", "sql"),
    }
)


def _walk_key_paths(payload: Any, prefix: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Yield every dict key path in the JSON tree."""
    paths: list[tuple[str, ...]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = prefix + (str(key),)
            paths.append(path)
            paths.extend(_walk_key_paths(value, path))
    elif isinstance(payload, list):
        for item in payload:
            paths.extend(_walk_key_paths(item, prefix))
    return paths


def _collect_gold_field_hits(root: Path) -> list[str]:
    """Flag any serialized JSON key named like a gold field outside the schema.

    ``interpretations.*.sql`` is the one legitimate gold-named key (the
    annotator's own SQL readings, required by ``annotation-schema-v1``); any
    other occurrence of a ``GOLD_FIELDS`` name is a potential leak.
    """
    hits: list[str] = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for key_path in _walk_key_paths(payload, ()):
            if (
                key_path[-1] in GOLD_FIELDS
                and key_path not in _ALLOWED_GOLD_NAMED_KEYS
            ):
                hits.append(
                    f"{path}: forbidden gold field key {key_path[-1]!r} "
                    f"at .{'.'.join(key_path)}"
                )
    return hits


def _merge_datasets(datasets: Iterable[AnnotationDataset]) -> AnnotationDataset:
    records: list[AnnotationRecord] = []
    for dataset in datasets:
        records.extend(dataset.records)
    return AnnotationDataset(
        schema_version=PROTOCOL_VERSION, records=tuple(records)
    )


def load_batch(
    batch_root: str | Path,
    *,
    required_families: Sequence[str] | None = None,
) -> tuple[AnnotationDataset, list[str]]:
    """Load a (possibly nested) batch root with the frozen loader per file.

    Returns ``(dataset, problems)``. Unlike ``freeze_batch`` this never
    raises for invalid content: validation problems are returned so callers
    can report them without triggering the freeze path. ``required_families``
    is forwarded to :func:`validate_batch` (see there for the reasoning-only
    metadata-deferred mode).
    """
    root = Path(batch_root)
    files = _collect_annotation_files(root)
    if not files:
        return (
            AnnotationDataset(schema_version=PROTOCOL_VERSION, records=()),
            [f"no annotation files found under {root}"],
        )
    loader = AnnotationDatasetLoader()
    try:
        dataset = _merge_datasets(loader.load(path) for path in files)
    except Exception as exc:  # noqa: BLE001 — report, do not fabricate
        return (
            AnnotationDataset(schema_version=PROTOCOL_VERSION, records=()),
            [f"annotation validation failed: {exc}"],
        )
    return dataset, validate_batch(
        dataset, required_families=required_families
    )


def freeze_batch(
    batch_root: str | Path,
    *,
    batch_id: str = BATCH_ID,
    batch_target: int = BATCH1_TARGET,
    provenance_filename: str = "provenance-v1.json",
    data_root: str | Path | None = None,
    required_families: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Verify every freeze precondition and, if all hold, return the freeze record.

    Never manufactures missing information: any unmet precondition raises
    ``AnnotationPrepError`` listing every violation. The SHA-256 is computed
    only over the label files and the provenance sidecar, in sorted relative
    path order (docs/19 §8). ``required_families`` is forwarded to
    :func:`validate_batch` (see there for the reasoning-only metadata-deferred
    mode).
    """
    root = Path(batch_root)
    problems: list[str] = []

    if not root.is_dir():
        raise AnnotationPrepError(f"batch root does not exist: {root}")

    annotation_files = _collect_annotation_files(root)
    if not annotation_files:
        problems.append("no annotation files found in batch root")

    dataset: AnnotationDataset | None = None
    loader = AnnotationDatasetLoader()
    if annotation_files:
        try:
            dataset = _merge_datasets(loader.load(path) for path in annotation_files)
            problems.extend(
                validate_batch(
                    dataset,
                    batch_target=batch_target,
                    required_families=required_families,
                )
            )
        except Exception as exc:
            problems.append(f"annotation validation failed: {exc}")

    sidecar_path = root / provenance_filename
    sidecar: dict[str, dict[str, Any]] = {}
    if not sidecar_path.is_file():
        problems.append(f"provenance sidecar missing: {sidecar_path.name}")
    else:
        try:
            sidecar = load_sidecar(sidecar_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            problems.append(f"provenance sidecar unreadable: {exc}")

    if dataset is not None and sidecar:
        problems.extend(
            _provenance_cross_checks(dataset, sidecar, sidecar_path, data_root)
        )

    gold_hits = _collect_gold_field_hits(root)
    problems.extend(gold_hits)

    if problems:
        raise AnnotationPrepError(
            "freeze preconditions not met:\n  - " + "\n  - ".join(problems)
        )

    if dataset is None:
        raise AnnotationPrepError("freeze preconditions not met: no validated labels")
    if not sidecar_path.is_file():
        raise AnnotationPrepError(
            "freeze preconditions not met: provenance sidecar missing"
        )
    files = sorted(annotation_files + [sidecar_path])
    rel_files = [path.relative_to(root) for path in files]
    digest = _freeze_digest(rel_files, base=root)
    return {
        "batch_id": batch_id,
        "schema_version": PROTOCOL_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "provenance_version": PROVENANCE_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "sha256": digest,
        "num_questions": len(dataset.records),
        "files": [str(path) for path in rel_files],
    }


def _provenance_cross_checks(
    dataset: AnnotationDataset,
    sidecar: Mapping[str, dict[str, Any]],
    sidecar_path: Path,
    data_root: str | Path | None,
) -> list[str]:
    """Cross-check the provenance sidecar against the labels (docs/19 §8)."""
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

    records_by_id = {record.question.question_id: record for record in dataset.records}
    for question_id, entry in sorted(sidecar.items()):
        entry_problems: list[str] = []
        if entry.get("provenance_version") != PROVENANCE_VERSION:
            entry_problems.append(f"bad provenance_version {entry.get('provenance_version')!r}")
        if entry.get("protocol_version") != PROTOCOL_VERSION:
            entry_problems.append(f"bad protocol_version {entry.get('protocol_version')!r}")
        annotators = entry.get("annotator_ids") or []
        if not annotators or any(
            not isinstance(value, str) or not value or value == PLACEHOLDER
            for value in annotators
        ):
            entry_problems.append("annotator_ids missing or not real")
        third = entry.get("third_annotator_id")
        if third is not None and (third == PLACEHOLDER or not third):
            entry_problems.append("third_annotator_id is not a real id")

        adjudication = entry.get("adjudication") or {}
        if adjudication.get("required"):
            senior = adjudication.get("senior_annotator_id")
            if not senior or senior == PLACEHOLDER:
                entry_problems.append("adjudication required but no senior annotator")
            if not adjudication.get("resolved_span_ids"):
                entry_problems.append("adjudication required but no resolved spans")
            if not adjudication.get("outcome") or adjudication.get("outcome") == PLACEHOLDER:
                entry_problems.append("adjudication required but no outcome")

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
        metadata_grounded = bool(
            record is not None
            and any(span.metadata_resolution for span in record.question.spans)
        )
        token = snapshot.get("token")
        if metadata_grounded:
            if not token:
                entry_problems.append(
                    "metadata-grounded labels present but enrichment snapshot token "
                    "is unavailable"
                )
            elif data_root is not None:
                expected, _ = derive_enrichment_token(
                    Path(data_root), snapshot.get("database_id", "")
                )
                if expected is None:
                    entry_problems.append(
                        f"enrichment.json not found for {snapshot.get('database_id')!r} "
                        "under data_root"
                    )
                elif token != expected:
                    entry_problems.append("enrichment token does not match the file")
            else:
                entry_problems.append(
                    "metadata-grounded labels present but enrichment cannot be "
                    "verified without data_root"
                )
        if entry_problems:
            problems.append(f"{question_id}: " + "; ".join(entry_problems))
    return problems


def _freeze_digest(files: Sequence[Path], *, base: Path) -> str:
    r"""SHA-256 over ``relpath + b'\x00' + file_bytes`` in sorted order.

    Relative paths keep the digest reproducible across machine layouts
    (docs/19 §8); the exact rule is recorded in ``HASH_ALGORITHM``.
    """
    hasher = hashlib.sha256()
    for rel in sorted(files):
        hasher.update(str(rel).encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update((base / rel).read_bytes())
    return hasher.hexdigest()


def write_lock(record: Mapping[str, Any], path: str | Path) -> Path:
    """Write the freeze record (``surface_b.v1.lock``) deterministically."""
    return write_json(dict(record), path)


__all__ = [
    "FAMILIES",
    "HASH_ALGORITHM",
    "batch_report",
    "freeze_batch",
    "load_batch",
    "validate_batch",
    "write_lock",
]
