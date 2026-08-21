"""Typed errors for loading and validating annotation datasets."""
from __future__ import annotations

from eaa.ambiguity_resolution.errors import AmbiguityResolutionError


class AnnotationLoadError(AmbiguityResolutionError):
    """An annotation source could not be read or parsed.

    Raised when a path does not exist, a file is not valid JSON, or a JSON
    value is not an annotation object or array of annotation objects.
    """


class AnnotationPrepError(AmbiguityResolutionError):
    """An annotation-preparation step cannot be executed as specified.

    Raised when a preparation precondition is violated and the step refuses to
    guess: a selection that is not a subset of the pool, a missing frozen seed
    for the third-label sample, an enrichment snapshot that cannot be verified,
    or an incomplete batch that must not be frozen.
    """


class AnnotationValidationError(AmbiguityResolutionError):
    """An annotation record violates the ``annotation-schema-v1`` contract.

    Carries ``question_id`` (and ``field`` where applicable) in ``context`` so
    failures are traceable to the offending labeled question.
    """

    def __init__(
        self,
        message: str,
        *,
        question_id: str = "<unknown>",
        field: str | None = None,
    ) -> None:
        context: dict[str, object] = {"question_id": question_id}
        if field is not None:
            context["field"] = field
        super().__init__(message, context=context)


__all__ = ["AnnotationLoadError", "AnnotationPrepError", "AnnotationValidationError"]
