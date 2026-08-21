"""Read-only statistics over an annotation dataset.

These are pure counting functions over the loaded typed representation; they
make no judgment about correctness or quality.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AnnotationDataset

_FAMILY_ORDER: tuple[str, ...] = ("L", "S", "R", "V", "C", "T", "K", "I", "U")


@dataclass(frozen=True)
class AnnotationDatasetStats:
    """Aggregate counts describing an annotation dataset.

    ``family_distribution`` maps each ambiguity-family letter (first character
    of the span's ``AmbiguityType`` code) to its span count.
    """

    num_questions: int
    num_ambiguity_types: int
    family_distribution: Mapping[str, int]
    answerable: int
    unanswerable: int
    num_interpretations: int


def compute_stats(dataset: AnnotationDataset) -> AnnotationDatasetStats:
    """Compute read-only aggregate statistics for ``dataset``."""
    families: dict[str, int] = {}
    distinct_types: set[str] = set()
    answerable = 0
    unanswerable = 0
    interpretations = 0

    for record in dataset.records:
        if record.question.answerability.label.value == "answerable":
            answerable += 1
        else:
            unanswerable += 1
        if record.interpretations is not None:
            interpretations += len(record.interpretations)
        for span in record.question.spans:
            family = span.ambiguity_type.value[0]
            families[family] = families.get(family, 0) + 1
            distinct_types.add(span.ambiguity_type.value)

    family_distribution: dict[str, int] = {
        family: families[family] for family in _FAMILY_ORDER if family in families
    }
    family_distribution.update(
        {family: count for family, count in families.items() if family not in family_distribution}
    )

    return AnnotationDatasetStats(
        num_questions=len(dataset.records),
        num_ambiguity_types=len(distinct_types),
        family_distribution=family_distribution,
        answerable=answerable,
        unanswerable=unanswerable,
        num_interpretations=interpretations,
    )


__all__ = ["AnnotationDatasetStats", "compute_stats"]
