"""Deterministic batch-1 selection for the AI-annotation run (docs/19 §4).

The protocol leaves question selection to screening (docs/13 §4, §8), and the
original plan reserved that screening for human annotators (docs/19 §5.3,
§11). In this environment the executing research assistant performs that
screening on behalf of the annotators, so the selection must still be
**deterministic, gold-free, and recorded**: it reads only the candidate pool
(question id, database id, question text, fired signals) and never any gold
field (ADR-009). Candidate signals are screening hints, not labels; the
stratum/family assignment implied here is a *target* the annotators confirm or
correct at label time (docs/19 §4.2 — never force a code onto a question that
does not exhibit it).

The rule is intentionally transparent:

1. **Persistent-ambiguity stratum** — fill each family's span target from the
   pool questions (in question-id order) that fire at least one signal of that
   family. This run's persistent families are the six the reasoning detector
   can establish without enrichment (S, R, C, T, K, I); the L/V "metadata
   present but not decisive" cases (docs/19 §4.2) are deferred with the
   metadata stratum because no legitimate ``enrichment.json`` exists.
2. **Unambiguous stratum** — the remaining questions with the *fewest* fired
   signals (least ambiguity evidence), in deterministic order.
3. **Metadata-closable stratum** — deferred. 15 questions that fire metadata
   signals (r1/v1/v2/v3/t2/k2) are recorded so the stratum is auditable, but
   they receive no labels in this run and the freeze marks them deferred.

Everything below is pure function of the pool: identical inputs produce
identical selections, so the run is reproducible.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from eaa.ambiguity_resolution.candidates import CandidatePool, CandidateRecord

from .batch import (
    MAX_SPANS_PER_FAMILY,
    METADATA_CLOSABLE_CODES,
)
from .errors import AnnotationPrepError


class SelectionRow(TypedDict):
    """One selected question in the run selection (docs/19 §4).

    ``signals`` are the sorted fired screening-signal ids; ``family`` is the
    persistent family for the persistent stratum and ``None`` otherwise;
    ``stratum`` is ``persistent_ambiguity`` | ``unambiguous`` |
    ``metadata_closable``.
    """

    question_id: str
    database_id: str
    stratum: str
    family: str | None
    signals: list[str]
    selection_reason: str

#: Signal id -> ambiguity family for the persistent families of this run.
PERSISTENT_FAMILY_SIGNALS: dict[str, tuple[str, ...]] = {
    "S": ("s1", "s2"),
    "R": ("r2",),
    "C": ("c1", "c2", "c3"),
    "T": ("t1",),
    "K": ("k1",),
    "I": ("i2", "i3"),
}

#: Persistent families for this run (metadata-independent; docs/19 §4.2 minus
#: the L/V "metadata-present-but-not-decisive" cases, which are deferred).
PERSISTENT_FAMILIES: tuple[str, ...] = ("S", "R", "C", "T", "K", "I")

#: Span targets for this run's persistent stratum (30 questions, one strict
#: span each; docs/19 §4.2 without the 3 L/V spans).
AI_RUN_PERSISTENT_TARGETS: dict[str, int] = {
    "S": 5,
    "R": 4,
    "C": 8,
    "T": 5,
    "K": 4,
    "I": 4,
}

#: Metadata-family signals whose questions are candidates for the deferred
#: metadata-closable stratum (docs/19 §4.3 codes).
METADATA_DEFERRED_SIGNALS: tuple[str, ...] = ("r1", "v1", "v2", "v3", "t2", "k2")

#: Unambiguous-stratum size for this run (docs/19 §4.1, minus the deferred
#: metadata-closable stratum).
AI_RUN_UNAMBIGUOUS_COUNT = 15

#: Deferred metadata-closable stratum size (recorded, not labeled).
AI_RUN_METADATA_DEFERRED_COUNT = 15

#: Database this run selects from (one database per question, docs/19 §5.3).
AI_RUN_DATABASE_ID = "dw"


def select_batch(
    pool: CandidatePool,
    *,
    database_id: str = AI_RUN_DATABASE_ID,
    persistent_targets: dict[str, int] | None = None,
    unambiguous_count: int = AI_RUN_UNAMBIGUOUS_COUNT,
    metadata_deferred_count: int = AI_RUN_METADATA_DEFERRED_COUNT,
) -> tuple[SelectionRow, ...]:
    """Deterministically select the batch-1 questions for the AI-annotation run.

    Parameters
    ----------
    pool:
        The gold-free candidate pool.
    database_id:
        Only candidates of this database are eligible (docs/19 §5.3).
    persistent_targets:
        Per-family span targets for the persistent stratum. Defaults to
        :data:`AI_RUN_PERSISTENT_TARGETS`.
    unambiguous_count:
        Target number of unambiguous-stratum questions.
    metadata_deferred_count:
        Target number of deferred metadata-closable questions recorded.

    Returns
    -------
    tuple
        One dict per selected question: ``question_id``, ``database_id``,
        ``stratum`` (``persistent_ambiguity`` | ``unambiguous`` |
        ``metadata_closable``), ``family`` (persistent only), ``signals``, and
        ``selection_reason``. Ordered deterministically by question id within
        each stratum.

    Raises
    ------
    AnnotationPrepError:
        If a target cannot be met from the eligible pool (the run must not
        silently under-fill a stratum).
    """
    targets = dict(persistent_targets or AI_RUN_PERSISTENT_TARGETS)
    _validate_targets(targets)

    eligible = sorted(
        (
            record
            for record in pool.candidates
            if record.database_id == database_id
        ),
        key=lambda record: record.question_id,
    )
    if not eligible:
        raise AnnotationPrepError(
            f"no candidates for database {database_id!r} in the pool"
        )

    selected: dict[str, SelectionRow] = {}

    # 1. Persistent stratum, family by family.
    for family in PERSISTENT_FAMILIES:
        family_signals = set(PERSISTENT_FAMILY_SIGNALS[family])
        needed = targets.get(family, 0)
        picked = 0
        for record in eligible:
            if picked >= needed:
                break
            if record.question_id in selected:
                continue
            fired = {hit.signal for hit in record.signals}
            hit_signals = sorted(family_signals & fired)
            if not hit_signals:
                continue
            selected[record.question_id] = {
                "question_id": record.question_id,
                "database_id": record.database_id,
                "stratum": "persistent_ambiguity",
                "family": family,
                "signals": _signal_list(record),
                "selection_reason": (
                    f"persistent target {family}; screening signals: "
                    + ", ".join(hit_signals)
                ),
            }
            picked += 1
        if picked < needed:
            raise AnnotationPrepError(
                f"persistent family {family!r}: only {picked}/{needed} eligible "
                f"questions found in the pool"
            )

    # 2. Unambiguous stratum: least fired-signal evidence among the rest.
    remaining = [
        record
        for record in eligible
        if record.question_id not in selected
    ]
    remaining.sort(
        key=lambda record: (len(record.signals), record.question_id)
    )
    for record in remaining[:unambiguous_count]:
        selected[record.question_id] = {
            "question_id": record.question_id,
            "database_id": record.database_id,
            "stratum": "unambiguous",
            "family": None,
            "signals": _signal_list(record),
            "selection_reason": (
                f"unambiguous target; {len(record.signals)} screening signals "
                "(least ambiguity evidence)"
            ),
        }
    if len(
        [row for row in selected.values() if row["stratum"] == "unambiguous"]
    ) < unambiguous_count:
        raise AnnotationPrepError(
            f"unambiguous stratum: fewer than {unambiguous_count} eligible "
            "questions in the pool"
        )

    # 3. Metadata-closable stratum: recorded as deferred, never labeled here.
    remaining = [
        record
        for record in eligible
        if record.question_id not in selected
    ]
    remaining.sort(key=lambda record: record.question_id)
    deferred_signals = set(METADATA_DEFERRED_SIGNALS)
    picked = 0
    for record in remaining:
        if picked >= metadata_deferred_count:
            break
        fired = {hit.signal for hit in record.signals}
        if not (fired & deferred_signals):
            continue
        selected[record.question_id] = {
            "question_id": record.question_id,
            "database_id": record.database_id,
            "stratum": "metadata_closable",
            "family": None,
            "signals": _signal_list(record),
            "selection_reason": (
                "metadata-closable target; DEFERRED this run (no legitimate "
                "enrichment.json exists to pin the reading, docs/19 §4.3)"
            ),
        }
        picked += 1
    if picked < metadata_deferred_count:
        raise AnnotationPrepError(
            f"metadata-closable stratum: only {picked}/{metadata_deferred_count} "
            "eligible questions found in the pool"
        )

    return tuple(
        selected[question_id]
        for question_id in sorted(selected)
    )


def _validate_targets(targets: dict[str, int]) -> None:
    """Reject persistent targets that break the docs/19 family cap or go stale."""
    expected = set(AI_RUN_PERSISTENT_TARGETS)
    if set(targets) != expected:
        raise AnnotationPrepError(
            f"persistent targets must cover exactly {sorted(expected)}; "
            f"got {sorted(targets)}"
        )
    for family, count in targets.items():
        if count < 0 or count > MAX_SPANS_PER_FAMILY:
            raise AnnotationPrepError(
                f"persistent family {family!r} target {count} outside "
                f"[0, {MAX_SPANS_PER_FAMILY}]"
            )


def _signal_list(record: CandidateRecord) -> list[str]:
    """Return the sorted fired signal ids of a candidate record."""
    return sorted({hit.signal for hit in record.signals})


def selection_summary(
    selection: Sequence[SelectionRow],
) -> dict[str, object]:
    """Return the strata/family counts of a selection for the run record."""
    strata: dict[str, int] = {}
    families: dict[str, int] = {}
    for row in selection:
        strata[row["stratum"]] = strata.get(row["stratum"], 0) + 1
        family = row.get("family")
        if family:
            families[family] = families.get(family, 0) + 1
    return {
        "database_id": AI_RUN_DATABASE_ID,
        "strata": dict(sorted(strata.items())),
        "stratum_targets": {
            "persistent_ambiguity": sum(AI_RUN_PERSISTENT_TARGETS.values()),
            "unambiguous": AI_RUN_UNAMBIGUOUS_COUNT,
            "metadata_closable": AI_RUN_METADATA_DEFERRED_COUNT,
        },
        "persistent_family_targets": dict(AI_RUN_PERSISTENT_TARGETS),
        "persistent_family_counts": dict(sorted(families.items())),
        "max_spans_per_family": MAX_SPANS_PER_FAMILY,
        "metadata_closable_codes": list(METADATA_CLOSABLE_CODES),
        "metadata_closable_status": "deferred",
        "rule": (
            "deterministic, gold-free screening over the candidate pool; "
            "strata confirmed or corrected by the annotators at label time "
            "(docs/19 §4.2)"
        ),
    }


__all__ = [
    "AI_RUN_DATABASE_ID",
    "AI_RUN_METADATA_DEFERRED_COUNT",
    "AI_RUN_PERSISTENT_TARGETS",
    "AI_RUN_UNAMBIGUOUS_COUNT",
    "METADATA_DEFERRED_SIGNALS",
    "PERSISTENT_FAMILIES",
    "PERSISTENT_FAMILY_SIGNALS",
    "select_batch",
    "selection_summary",
]
