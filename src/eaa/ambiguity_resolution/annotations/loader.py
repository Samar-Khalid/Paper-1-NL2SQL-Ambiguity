"""Loader for ``annotation-schema-v1`` annotation files."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from pydantic import ValidationError

from .errors import AnnotationLoadError, AnnotationValidationError
from .models import AnnotationDataset, AnnotationRecord


class AnnotationDatasetLoader:
    """Loads labeled-question JSON into typed, validated annotation datasets.

    Accepts a single annotation object, an array of annotation objects, or a
    directory of ``.json`` files (each an object or an array). Validates the
    schema version, required fields, ambiguity codes, span bounds and text
    integrity, interpretations, and dataset-wide uniqueness of ``question_id``.
    """

    supported_schema_version: ClassVar[str] = "annotation-schema-v1"

    def load(self, source: str | Path) -> AnnotationDataset:
        """Load and validate the annotation dataset at ``source``."""
        path = Path(source)
        if not path.exists():
            raise AnnotationLoadError(
                f"annotation source does not exist: {path}",
                context={"source": str(path)},
            )
        raw_records: list[tuple[Any, Path]] = []
        if path.is_dir():
            files = sorted(
                p for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".json"
            )
            if not files:
                raise AnnotationLoadError(
                    f"no .json annotation files in directory: {path}",
                    context={"source": str(path)},
                )
            for file in files:
                raw_records.extend(self._iter_records(self._read_json(file), file))
        else:
            raw_records.extend(self._iter_records(self._read_json(path), path))

        records = [self._parse_record(raw, file) for raw, file in raw_records]
        return self._build_dataset(records)

    def _iter_records(self, data: Any, source: Path) -> list[tuple[Any, Path]]:
        if isinstance(data, dict):
            return [(data, source)]
        if isinstance(data, list):
            return [(item, source) for item in data]
        raise AnnotationLoadError(
            f"{source.name}: expected a JSON object or array of objects",
            context={"source": str(source)},
        )

    def _read_json(self, path: Path) -> Any:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AnnotationLoadError(
                f"cannot read annotation file {path.name}: {exc}",
                context={"source": str(path)},
            ) from exc
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AnnotationLoadError(
                f"{path.name}: invalid JSON: {exc}",
                context={"source": str(path)},
            ) from exc

    def _parse_record(self, raw: Any, source: Path) -> AnnotationRecord:
        if not isinstance(raw, dict):
            raise AnnotationLoadError(
                f"{source.name}: annotation record must be a JSON object",
                context={"source": str(source)},
            )
        question_id = str(raw.get("question_id", "<missing>"))
        self._check_schema_version(raw, question_id)
        try:
            return AnnotationRecord.model_validate(
                {
                    "schema_version": raw["schema_version"],
                    "question": {
                        "question_id": raw.get("question_id"),
                        "question_text": raw.get("question_text"),
                        "database_id": raw.get("database_id"),
                        "answerability": raw.get("answerability"),
                        "spans": raw.get("spans", []),
                    },
                    "interpretations": raw.get("interpretations"),
                    "notes": raw.get("notes"),
                }
            )
        except ValidationError as exc:
            raise self._validation_error(exc, question_id) from exc

    def _check_schema_version(self, raw: dict[Any, Any], question_id: str) -> None:
        version = raw.get("schema_version")
        if version is None:
            raise AnnotationValidationError(
                "missing required field 'schema_version'", question_id=question_id
            )
        if not isinstance(version, str) or version != self.supported_schema_version:
            raise AnnotationValidationError(
                f"unsupported annotation schema version {version!r}; "
                f"supported: {self.supported_schema_version!r}",
                question_id=question_id,
                field="schema_version",
            )

    def _build_dataset(self, records: list[AnnotationRecord]) -> AnnotationDataset:
        seen: set[str] = set()
        for record in records:
            question_id = record.question.question_id
            if question_id in seen:
                raise AnnotationValidationError(
                    f"duplicate question_id {question_id!r} in annotation dataset",
                    question_id=question_id,
                )
            seen.add(question_id)
        return AnnotationDataset(
            schema_version=self.supported_schema_version,
            records=tuple(records),
        )

    @staticmethod
    def _validation_error(
        exc: ValidationError, question_id: str
    ) -> AnnotationValidationError:
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first["loc"])
        return AnnotationValidationError(
            f"{first['msg']} (field: {loc})",
            question_id=question_id,
            field=loc,
        )


__all__ = ["AnnotationDatasetLoader"]
