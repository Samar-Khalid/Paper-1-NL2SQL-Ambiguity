"""BEAVER adapter: implements the core dataset interfaces (ADR-002/006).

``BeaverAdapter`` implements ``DatasetAdapter`` + ``BenchmarkAdapter`` from
``eaa.core.interfaces.dataset`` and additionally exposes:

- ``schema_provider()`` — per-warehouse schemas (design doc §3.3, Decision D2);
- ``samples(split)`` — the raw sample-loading interface yielding the
  (task, gold, runtime-context) trio used by the pipeline/evaluation harness.

Data access is lazy and verified: constructing the adapter never fails, but any
data-access method verifies the adapter-local manifest (version + checksum) and
raises ``AdapterError`` with setup guidance when the raw data is missing or
tampered with.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from pathlib import Path
from typing import Any

from eaa.core.contracts.errors import AdapterError
from eaa.core.contracts.gold import GoldReferenceEnvelope
from eaa.core.contracts.manifest import DatasetManifest
from eaa.core.contracts.runtime import RuntimeContext
from eaa.core.contracts.schema import DatabaseSchema, EnrichedSchema, EnrichmentData, TableSchema
from eaa.core.contracts.task import TaskEnvelope
from eaa.core.interfaces.schema import SchemaProvider

from . import loader
from . import manifest as beaver_manifest
from .format import RawQuestion
from .metadata import BeaverMetadataProvider, load_enrichment


class _LoadedDataset:
    """Cached, verified view of the on-disk raw data."""

    def __init__(
        self,
        raw_manifest: dict[str, Any],
        schemas: dict[str, DatabaseSchema],
        questions: dict[str, list[RawQuestion]],
        enrichment: dict[str, EnrichmentData],
        databases: list[str],
    ) -> None:
        self.raw_manifest = raw_manifest
        self.schemas = schemas
        self.questions = questions
        self.enrichment = enrichment
        self.databases = databases
        self.gold: dict[str, RawQuestion] = {}
        for db_id in databases:
            for question in questions[db_id]:
                self.gold[question.question_id] = question


class BeaverSchemaProvider:
    """Per-warehouse ``SchemaProvider`` backed by loaded BEAVER schemas."""

    def __init__(self, schemas: Mapping[str, DatabaseSchema]) -> None:
        self._schemas = dict(schemas)

    def get_schema(self, database_id: str) -> DatabaseSchema:
        """Return the schema for one warehouse, raising on unknown ids."""
        try:
            return self._schemas[database_id]
        except KeyError:
            raise AdapterError(
                f"no BEAVER schema for database '{database_id}'; "
                f"available: {sorted(self._schemas)}"
            ) from None

    def get_enriched_schema(self, database_id: str) -> EnrichedSchema | None:
        """Report no enrichment for the base provider; the wrapper resolves it.

        ``BeaverSchemaProvider`` implements ``SchemaProvider`` only; the
        experiment driver composes it with a ``BeaverMetadataProvider`` through
        ``eaa.metadata.EnrichedSchemaProvider`` when ``schema.enriched`` is set.
        """
        self.get_schema(database_id)  # validate the id
        return None


class BeaverAdapter:
    """Dataset + benchmark adapter for the BEAVER NL2SQL benchmark."""

    name = "beaver"

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        version: str | None = None,
        dialect: str | None = None,
        dataset_id: str = "beaver",
        verify: bool = True,
    ) -> None:
        self._root = Path(root) if root is not None else beaver_manifest.default_data_root()
        self._version = version or beaver_manifest.BEAVER_DATA_VERSION
        self._dialect = dialect or beaver_manifest.BEAVER_DIALECT
        self._dataset_id = dataset_id
        self._verify = verify
        self._loaded: _LoadedDataset | None = None

    # -- verification ---------------------------------------------------------

    def _ensure_loaded(self) -> _LoadedDataset:
        if self._loaded is not None:
            return self._loaded
        if not self._root.is_dir():
            raise AdapterError(
                f"BEAVER data root '{self._root}' does not exist. The raw data is not "
                "shipped with the framework; download it into a gitignored data root and "
                "record manifest.json there (see src/eaa/datasets/adapters/beaver/README.md), "
                f"or set EAA_BEAVER_DATA_ROOT."
            )
        raw = beaver_manifest.load_raw_manifest(self._root)
        beaver_manifest.verify_version(raw, self._version)

        databases = beaver_manifest.discover_databases(self._root, raw)
        if not databases:
            raise AdapterError(
                f"no BEAVER databases found under '{self._root}'; expected a subdirectory "
                "per warehouse containing tables and questions files"
            )

        if self._verify:
            recorded = raw.get("checksum")
            beaver_manifest.verify_checksum(
                self._root, databases, recorded if isinstance(recorded, str) else None
            )

        schemas: dict[str, DatabaseSchema] = {}
        questions: dict[str, list[RawQuestion]] = {}
        enrichment: dict[str, EnrichmentData] = {}
        all_questions: list[RawQuestion] = []
        for db_id in databases:
            schema = loader.load_schema(self._root, db_id, self._dialect)
            loader.check_fk_integrity(schema)
            schemas[db_id] = schema
            questions[db_id] = loader.load_questions(self._root, db_id)
            all_questions.extend(questions[db_id])
            sidecar = load_enrichment(self._root, db_id)
            if sidecar is not None:
                enrichment[db_id] = sidecar

        missing_gold = [q.question_id for q in all_questions if not q.gold_sql]
        if missing_gold:
            raise AdapterError(
                f"{len(missing_gold)} BEAVER questions have no gold SQL (e.g. "
                f"'{missing_gold[0]}')"
            )
        all_ids = [q.question_id for q in all_questions]
        if len(all_ids) != len(set(all_ids)):
            raise AdapterError("duplicate BEAVER task ids across databases")

        self._loaded = _LoadedDataset(raw, schemas, questions, enrichment, databases)
        return self._loaded

    def validate(self) -> None:
        """Validate manifest version/checksum, data files, and referential integrity."""
        self._ensure_loaded()

    # -- DatasetAdapter -------------------------------------------------------

    def manifest(self) -> DatasetManifest:
        """Return the self-description manifest for the BEAVER dataset."""
        loaded = self._ensure_loaded()
        stats = loader.compute_stats(
            [q for db in loaded.databases for q in loaded.questions[db]], loaded.schemas
        )
        return beaver_manifest.build_dataset_manifest(
            self._root,
            loaded.raw_manifest,
            databases=loaded.databases,
            dialect=self._dialect,
            checksum=beaver_manifest.compute_checksum(self._root, loaded.databases),
            stats=stats,
        )

    def schema(self) -> DatabaseSchema:
        """Return the aggregate BEAVER schema (all warehouses merged).

        The aggregate is well-defined only when table names are unique across
        warehouses; the per-warehouse schemas (``schema_provider()``) are the
        faithful view.
        """
        loaded = self._ensure_loaded()
        tables: list[TableSchema] = []
        seen: set[str] = set()
        for db_id in loaded.databases:
            for table in loaded.schemas[db_id].tables:
                if table.name in seen:
                    raise AdapterError(
                        f"cannot build an aggregate BEAVER schema: table '{table.name}' "
                        f"appears in multiple warehouses; use schema_provider() instead"
                    )
                seen.add(table.name)
                tables.append(table)
        return DatabaseSchema(
            database_id=self._dataset_id,
            dialect=self._dialect,
            tables=tables,
            description="Aggregate BEAVER schema (all warehouses merged).",
        )

    def schema_provider(self) -> SchemaProvider:
        """Return a per-warehouse ``SchemaProvider`` (Decision D2)."""
        loaded = self._ensure_loaded()
        return BeaverSchemaProvider(loaded.schemas)

    def metadata(self) -> BeaverMetadataProvider:
        """Return a per-warehouse ``MetadataProvider`` from the sidecar data.

        Adapters publish enrichment as *data* (ADR-015); the experiment driver
        composes this with ``schema_provider()`` via ``eaa.metadata`` when the
        ``schema.enriched`` toggle is on.
        """
        loaded = self._ensure_loaded()
        return BeaverMetadataProvider(loaded.enrichment)

    # -- BenchmarkAdapter -----------------------------------------------------

    def splits(self) -> list[str]:
        """Return the splits recorded as downloaded locally."""
        loaded = self._ensure_loaded()
        declared = loaded.raw_manifest.get("splits")
        return list(declared) if isinstance(declared, list) else list(beaver_manifest.BEAVER_SPLITS)

    def default_split(self) -> str:
        """Return the default split for questions without an explicit split."""
        loaded = self._ensure_loaded()
        declared = loaded.raw_manifest.get("default_split")
        return declared if isinstance(declared, str) else "dev"

    async def task_stream(self, split: str | None = None) -> AsyncIterator[TaskEnvelope]:
        """Yield task envelopes, optionally filtered to one split."""
        for task in self._iter_tasks(split):
            yield task

    def gold_for(self, task_id: str) -> GoldReferenceEnvelope:
        """Return the gold reference for a task id (evaluation-only, ADR-009)."""
        loaded = self._ensure_loaded()
        question = loaded.gold.get(task_id)
        if question is None:
            raise AdapterError(f"no BEAVER gold reference for task id '{task_id}'")
        return loader.gold_envelope(
            question,
            dataset_id=self._dataset_id,
            source_split=question.split or self.default_split(),
        )

    # -- sample-loading interface ---------------------------------------------

    def samples(
        self, split: str | None = None
    ) -> Iterator[tuple[TaskEnvelope, GoldReferenceEnvelope, RuntimeContext]]:
        """Yield the (task, gold, runtime-context) trio for every sample."""
        for task in self._iter_tasks(split):
            yield task, self.gold_for(task.header.task_id), self.context_for(task)

    def context_for(self, task: TaskEnvelope) -> RuntimeContext:
        """Build the per-sample runtime context for a task envelope."""
        return loader.context_for(task)

    # -- internals --------------------------------------------------------------

    def _iter_tasks(self, split: str | None) -> Iterator[TaskEnvelope]:
        loaded = self._ensure_loaded()
        default = self.default_split()
        for db_id in loaded.databases:
            for question in loaded.questions[db_id]:
                if split is not None and (question.split or default) != split:
                    continue
                yield loader.task_envelope(
                    question, dialect=self._dialect, dataset_id=self._dataset_id
                )
