"""Tests for the Surface B annotation-preparation tooling (docs/19).

Covers the gold-free candidate → batch boundary, the annotator workspace, the
provenance-v1 skeleton, the third-label sample rule, and the QC/freeze
checkers. Gold leakage is asserted on the *serialized* artifacts, matching the
ADR-009 hard rule.
"""
import hashlib
import json

import pytest
from beaver_data import build_beaver_metadata, build_beaver_root

from eaa.ambiguity_resolution.annotations import (
    BATCH1_TARGET,
    MAX_SPANS_PER_FAMILY,
    PLACEHOLDER,
    STRATUM_TARGETS,
    Adjudication,
    AnnotationDataset,
    AnnotationDatasetLoader,
    AnnotationPrepError,
    EnrichmentSnapshot,
    ProvenanceSidecar,
    build_annotation_workspace,
    build_batch_input,
    build_provenance_skeleton,
    build_screening_manifest,
    derive_enrichment_token,
    freeze_batch,
    load_sidecar,
    schema_to_annotator_view,
    select_third_label_sample,
    validate_batch,
)
from eaa.ambiguity_resolution.candidates import GOLD_FIELDS, build_candidate_pool

pytestmark = pytest.mark.unit

METADATA_QUESTION = "Show the area for room 25."
PERSISTENT_QUESTION = "Show the top 5 rooms by area."
UNAMBIGUOUS_QUESTION = "List all buildings."

#: evaluable codes, one per family, cycled across the persistent stratum so
#: every family (L/S/R/V/C/T/K/I) is represented (docs/19 §4.2).
PERSISTENT_CODES = [
    "L2", "S1", "S2", "R1", "R2", "V1", "V2", "V3",
    "C1", "C2", "C3", "T1", "T2", "K1", "K2", "I2", "I3",
]

#: metadata-closable codes cycled in the synthetic batches; a subset is used so
#: the per-family span totals stay under the cap of 8 (docs/19 §4.2).
_META_CYCLE = ["L2", "R1", "T2", "K2"]


def _questions() -> list[str]:
    return [
        "What is the total amount of revenue?",
        "Show all status values.",
        "List buildings built before 1950.",
    ]


def _gold_named_key_hits(payload, allowed=()) -> list[str]:
    """Flag gold-named JSON keys outside the explicitly allowed paths.

    Mirrors the implementation's schema-aware gold scan: e.g. ``tables`` under
    ``schemas.<db>`` is the DatabaseSchema contract, not the gold table set.
    """

    def walk(node, prefix):
        hits = []
        if isinstance(node, dict):
            for key, value in node.items():
                path = prefix + (str(key),)
                if key in GOLD_FIELDS and path not in allowed:
                    hits.append(".".join(path))
                hits.extend(walk(value, path))
        elif isinstance(node, list):
            for item in node:
                hits.extend(walk(item, prefix))
        return hits

    return walk(payload, ())


def _batch_input_allowed_schema_tables(batch: dict) -> set:
    return {
        ("schemas", database_id, "tables")
        for database_id in batch.get("schemas", {})
    }


def _record(
    question_id: str,
    question_text: str,
    *,
    spans: list[dict],
    database_id: str = "dw",
    answerability: dict | None = None,
    interpretations: dict | None = None,
    notes: str | None = None,
) -> dict:
    return {
        "schema_version": "annotation-schema-v1",
        "question_id": question_id,
        "question_text": question_text,
        "database_id": database_id,
        "answerability": answerability or {
            "label": "answerable",
            "confidence": 0.95,
        },
        "spans": spans,
        "interpretations": interpretations,
        "notes": notes,
    }


def _span(
    span_id: str,
    text: str,
    question_text: str,
    code: str,
    *,
    metadata_resolution: bool,
    channel: str,
) -> dict:
    start = question_text.index(text)
    return {
        "span_id": span_id,
        "text": text,
        "start": start,
        "end": start + len(text),
        "ambiguity_type": code,
        "metadata_resolution": metadata_resolution,
        "clarification_required": not metadata_resolution,
        "assumption_risk": "low",
        "resolution_channel": channel,
    }


def _interpretations() -> dict:
    return {
        "sql_reading_A": {
            "sql": "SELECT area FROM room ORDER BY area DESC LIMIT 5",
            "note": "top 5 largest",
        },
        "sql_reading_B": {
            "sql": "SELECT area FROM room ORDER BY area ASC LIMIT 5",
            "note": "top 5 smallest",
        },
    }


def _sidecar_entry(question_id: str, *, token: str | None, annotators=None) -> dict:
    return ProvenanceSidecar(
        question_id=question_id,
        annotator_ids=annotators or ["annotator-a", "annotator-b"],
        third_annotator_id=None,
        enrichment_snapshot=EnrichmentSnapshot(database_id="dw", token=token),
        adjudication=Adjudication(),
    ).model_dump()


def _write_valid_batch(
    root,
    *,
    n_metadata: int = 15,
    n_persistent: int = 30,
    n_unambiguous: int = 15,
    token: str | None = None,
    sidecar_annotators=None,
    provenance_filename: str = "provenance-v1.json",
) -> None:
    """Write a complete, well-formed 60-question batch into ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    question_ids: list[str] = []

    for i in range(n_metadata):
        code = _META_CYCLE[i % len(_META_CYCLE)]
        question_id = f"meta-{i:03d}"
        question_ids.append(question_id)
        records.append(
            _record(
                question_id,
                METADATA_QUESTION,
                spans=[
                    _span(
                        "sp1",
                        "area",
                        METADATA_QUESTION,
                        code,
                        metadata_resolution=True,
                        channel="metadata",
                    )
                ],
            )
        )

    for i in range(n_persistent):
        code = PERSISTENT_CODES[i % len(PERSISTENT_CODES)]
        question_id = f"pers-{i:03d}"
        question_ids.append(question_id)
        records.append(
            _record(
                question_id,
                PERSISTENT_QUESTION,
                spans=[
                    _span(
                        "sp1",
                        "top 5",
                        PERSISTENT_QUESTION,
                        code,
                        metadata_resolution=False,
                        channel="clarification",
                    )
                ],
                interpretations=_interpretations(),
            )
        )

    for i in range(n_unambiguous):
        question_id = f"unamb-{i:03d}"
        question_ids.append(question_id)
        records.append(
            _record(question_id, UNAMBIGUOUS_QUESTION, spans=[])
        )

    for record in records:
        (root / f"{record['question_id']}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )

    sidecar = {
        question_id: _sidecar_entry(
            question_id, token=token, annotators=sidecar_annotators
        )
        for question_id in question_ids
    }
    (root / provenance_filename).write_text(
        json.dumps(sidecar), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# candidate -> batch conversion, determinism, preservation, schema grounding
# ---------------------------------------------------------------------------


def test_manifest_preserves_identity(make_task, warehouse_schema) -> None:
    """The screening manifest keeps ids, text, database ids, and signals."""
    tasks = [
        make_task(f"dw:000{i + 1}", question, "dw")
        for i, question in enumerate(_questions())
    ]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    manifest = build_screening_manifest(pool, {"dw": warehouse_schema})
    rows = {row["question_id"]: row for row in manifest["candidates"]}
    assert set(rows) == {"dw:0001", "dw:0002", "dw:0003"}
    assert rows["dw:0001"]["question"] == _questions()[0]
    assert rows["dw:0001"]["database_id"] == "dw"
    assert rows["dw:0001"]["schema_available"] is True
    assert rows["dw:0001"]["selection_status"] == "unselected"
    assert manifest["stratum_targets"] == dict(STRATUM_TARGETS)
    assert manifest["gold_inference"] == "never"


def test_manifest_is_deterministic(make_task, warehouse_schema) -> None:
    """Two manifest builds from the same pool are identical."""
    tasks = [make_task("q1", question, "dw") for question in _questions()]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    first = build_screening_manifest(pool, {"dw": warehouse_schema})
    second = build_screening_manifest(pool, {"dw": warehouse_schema})
    assert first == second


def test_manifest_contains_no_gold_fields(make_task, warehouse_schema) -> None:
    """The serialized manifest never mentions a gold field name."""
    tasks = [make_task("q1", question, "dw") for question in _questions()]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    text = json.dumps(build_screening_manifest(pool, {"dw": warehouse_schema}))
    for field in GOLD_FIELDS:
        assert f'"{field}"' not in text


def test_batch_input_preserves_exact_question_text(make_task, warehouse_schema) -> None:
    """Selected questions keep their exact text, ids, and database ids."""
    tasks = [
        make_task(f"q{i + 1}", question, "dw")
        for i, question in enumerate(_questions())
    ]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    batch = build_batch_input(pool, {"dw": warehouse_schema}, ["q1", "q2"])
    questions = {q["question_id"]: q for q in batch["questions"]}
    assert questions["q1"]["question"] == _questions()[0]
    assert questions["q1"]["database_id"] == "dw"
    assert questions["q2"]["question"] == _questions()[1]
    assert batch["gold_excluded"] is True
    assert batch["protocol_version"] == "annotation-schema-v1"


def test_batch_input_schema_grounding(make_task, warehouse_schema) -> None:
    """The annotator schema view exposes tables, columns, types, and PK/FK."""
    view = schema_to_annotator_view(warehouse_schema)
    tables = {table["name"]: table for table in view["tables"]}
    assert set(tables) == {"customers", "orders"}
    columns = {col["name"]: col for col in tables["orders"]["columns"]}
    assert columns["order_id"]["data_type"] == "int"
    assert columns["order_id"]["primary_key"] is True
    assert columns["customer_id"]["foreign_key"] == {
        "column": "customer_id",
        "references_table": "customers",
        "references_column": "customer_id",
    }


def test_batch_input_gold_excluded_in_json(make_task, warehouse_schema) -> None:
    """The serialized batch input artifact leaks no gold field names."""
    tasks = [make_task("q1", question, "dw") for question in _questions()]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    batch = build_batch_input(pool, {"dw": warehouse_schema}, ["q1"])
    hits = _gold_named_key_hits(batch, _batch_input_allowed_schema_tables(batch))
    assert hits == []


def test_workspace_layout_and_gold_free_templates(tmp_path, make_task, warehouse_schema) -> None:
    """The workspace writes batch.json, templates, and a provenance skeleton."""
    tasks = [
        make_task(f"q{i + 1}", question, "dw")
        for i, question in enumerate(_questions())
    ]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    root = build_annotation_workspace(
        pool,
        {"dw": warehouse_schema},
        ["q1", "q2"],
        out_root=tmp_path / "batch-1",
    )
    assert (root / "batch.json").is_file()
    assert (root / "provenance-v1.json").is_file()
    for annotator in ("annotator-a", "annotator-b"):
        for question_id in ("q1", "q2"):
            template = (root / annotator / f"{question_id}.json")
            assert template.is_file()
            payload = json.loads(template.read_text(encoding="utf-8"))
            assert payload["question_text"] == _questions()[0 if question_id == "q1" else 1]
            assert payload["question_id"] == question_id
            assert payload["database_id"] == "dw"
            assert payload["answerability"]["label"] is None
            assert payload["spans"] == []
            assert payload["interpretations"] is None
    for json_file in root.rglob("*.json"):
        payload = json.loads(json_file.read_text(encoding="utf-8"))
        if json_file.name == "batch.json":
            allowed = _batch_input_allowed_schema_tables(payload)
        else:
            allowed = ()
        assert _gold_named_key_hits(payload, allowed) == [], json_file


def test_workspace_rejects_selection_outside_pool(tmp_path, make_task, warehouse_schema) -> None:
    """A selection that is not a subset of the pool is refused, never guessed."""
    tasks = [make_task("q1", _questions()[0], "dw")]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    with pytest.raises(AnnotationPrepError, match="absent from the candidate pool"):
        build_batch_input(pool, {"dw": warehouse_schema}, ["nope"])


def test_pool_from_adapter_is_gold_free(tmp_path) -> None:
    """A batch built from the adapter task stream cannot leak raw gold."""
    import asyncio

    root = build_beaver_root(tmp_path / "beaver")
    from eaa.datasets.adapters.beaver import BeaverAdapter

    adapter = BeaverAdapter(str(root))
    adapter.validate()
    provider = adapter.schema_provider()
    schemas = {"dw": provider.get_schema("dw")}

    tasks = asyncio.run(_collect_tasks(adapter))
    pool = build_candidate_pool(tasks, schemas)
    batch = build_batch_input(pool, schemas, [pool.candidates[0].question_id])
    hits = _gold_named_key_hits(batch, _batch_input_allowed_schema_tables(batch))
    assert hits == []
    assert pool.candidates[0].question == "What is the total area of history department buildings?"


async def _collect_tasks(adapter) -> list:
    return [task async for task in adapter.task_stream("dev")]


# ---------------------------------------------------------------------------
# batch QC: spans, codes, interpretations, strata, families
# ---------------------------------------------------------------------------


def _dataset(records: list[dict]) -> AnnotationDataset:
    """Build a validated dataset directly from annotation record dicts."""
    parsed = []
    for raw in records:
        parsed.append(
            {
                "schema_version": raw["schema_version"],
                "question": {
                    "question_id": raw["question_id"],
                    "question_text": raw["question_text"],
                    "database_id": raw["database_id"],
                    "answerability": raw["answerability"],
                    "spans": raw["spans"],
                },
                "interpretations": raw["interpretations"],
                "notes": raw["notes"],
            }
        )
    from eaa.ambiguity_resolution.annotations import AnnotationRecord

    return AnnotationDataset(
        schema_version="annotation-schema-v1",
        records=tuple(AnnotationRecord.model_validate(entry) for entry in parsed),
    )


def test_validate_rejects_non_evaluable_codes() -> None:
    """L1, C4, I1, and U codes are never valid batch span labels."""
    for code in ("L1", "C4", "I1", "U1"):
        records = [
            _record(
                f"q-{code}",
                PERSISTENT_QUESTION,
                spans=[
                    _span(
                        "sp1", "top 5", PERSISTENT_QUESTION, code,
                        metadata_resolution=False, channel="clarification",
                    )
                ],
                interpretations=_interpretations(),
            )
        ]
        problems = validate_batch(_dataset(records))
        assert any("non-evaluable code" in problem for problem in problems), code


def test_validate_rejects_missing_interpretations_for_strict_span() -> None:
    """A strict-ambiguity span without interpretations is a violation."""
    records = [
        _record(
            "q1",
            PERSISTENT_QUESTION,
            spans=[
                _span(
                    "sp1", "top 5", PERSISTENT_QUESTION, "C2",
                    metadata_resolution=False, channel="clarification",
                )
            ],
        )
    ]
    assert any("interpretations missing" in p for p in validate_batch(_dataset(records)))


def test_validate_rejects_interpretations_without_strict_span() -> None:
    """Interpretations present without a strict-ambiguity span is a violation."""
    records = [
        _record(
            "q1",
            METADATA_QUESTION,
            spans=[
                _span(
                    "sp1", "area", METADATA_QUESTION, "V1",
                    metadata_resolution=True, channel="metadata",
                )
            ],
            interpretations=_interpretations(),
        )
    ]
    assert any("without a strict-ambiguity span" in p for p in validate_batch(_dataset(records)))


def test_validate_rejects_identical_readings() -> None:
    """The two readings must be distinct SQL statements."""
    records = [
        _record(
            "q1",
            PERSISTENT_QUESTION,
            spans=[
                _span(
                    "sp1", "top 5", PERSISTENT_QUESTION, "C2",
                    metadata_resolution=False, channel="clarification",
                )
            ],
            interpretations={
                "sql_reading_A": {"sql": "SELECT area FROM room LIMIT 5"},
                "sql_reading_B": {"sql": "SELECT area FROM room LIMIT 5"},
            },
        )
    ]
    assert any("identical" in p for p in validate_batch(_dataset(records)))


def test_validate_rejects_wrong_batch_size(make_task, warehouse_schema) -> None:
    """A batch that is not the target size is rejected."""
    tasks = [make_task("q1", _questions()[0], "dw")]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    records = [
        _record(record.question_id, record.question, spans=[])
        for record in pool.candidates
    ]
    dataset = _dataset(records)
    assert len(dataset.records) != BATCH1_TARGET
    assert any("batch size" in p for p in validate_batch(dataset))


def test_validate_full_synthetic_batch_passes() -> None:
    """The 15/30/15 synthetic batch satisfies all acceptance criteria."""
    dataset = _dataset(
        _synthetic_records(n_metadata=15, n_persistent=30, n_unambiguous=15)
    )
    assert validate_batch(dataset) == []


def test_validate_rejects_missing_family_coverage() -> None:
    """The persistent stratum must represent every family."""
    records = []
    for i in range(30):
        code = PERSISTENT_CODES[i % len(PERSISTENT_CODES)]
        if code[0] not in {"S", "T"}:
            continue
        records.append(
            _record(
                f"pers-{i:03d}",
                PERSISTENT_QUESTION,
                spans=[
                    _span(
                        "sp1", "top 5", PERSISTENT_QUESTION, code,
                        metadata_resolution=False, channel="clarification",
                    )
                ],
                interpretations=_interpretations(),
            )
        )
    problems = validate_batch(_dataset(records))
    assert any("misses families" in p for p in problems)


def test_validate_rejects_family_cap_exceeded() -> None:
    """No family may exceed the per-family span cap (docs/19 §4.2)."""
    records = [
        _record(
            f"q-{i}",
            PERSISTENT_QUESTION,
            spans=[
                _span(
                    "sp1", "top 5", PERSISTENT_QUESTION, "C2",
                    metadata_resolution=False, channel="clarification",
                )
            ],
            interpretations=_interpretations(),
        )
        for i in range(MAX_SPANS_PER_FAMILY + 1)
    ]
    assert any("> cap" in p for p in validate_batch(_dataset(records)))


def test_loader_rejects_duplicate_question_ids(tmp_path) -> None:
    """Duplicate question ids across files fail at load time."""
    (tmp_path / "a.json").write_text(
        json.dumps(_record("dup", UNAMBIGUOUS_QUESTION, spans=[])), encoding="utf-8"
    )
    (tmp_path / "b.json").write_text(
        json.dumps(_record("dup", UNAMBIGUOUS_QUESTION, spans=[])), encoding="utf-8"
    )

    with pytest.raises(Exception, match="duplicate question_id"):
        AnnotationDatasetLoader().load(tmp_path)


# ---------------------------------------------------------------------------
# provenance-v1 and enrichment
# ---------------------------------------------------------------------------


def test_provenance_skeleton_is_unpopulated() -> None:
    """The skeleton carries structure only — never fabricated identities."""
    sidecar = build_provenance_skeleton(["q1", "q2"], database_id="dw")
    entry = sidecar["q1"]
    assert entry["annotator_ids"] == []
    assert entry["third_annotator_id"] is None
    assert entry["enrichment_snapshot"]["token"] is None
    assert entry["adjudication"]["required"] is False
    assert entry["protocol_version"] == "annotation-schema-v1"
    assert entry["provenance_version"] == "provenance-v1"


def test_enrichment_token_unavailable_when_no_file(tmp_path) -> None:
    """No legitimate enrichment.json -> token is None, never invented."""
    token, path = derive_enrichment_token(tmp_path, "dw")
    assert token is None
    assert path is None


def test_enrichment_token_derived_from_exact_bytes(tmp_path) -> None:
    """The token is sha256 of the exact enrichment.json bytes (docs/19 §8)."""
    root = build_beaver_root(tmp_path / "raw")
    build_beaver_metadata(root)
    token, path = derive_enrichment_token(root, "dw")
    assert path == root / "dw" / "enrichment.json"
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert token == expected


def test_third_label_sample_is_deterministic() -> None:
    """A fixed seed yields a fixed sample; changing the seed changes it."""
    ids = [f"q-{i:03d}" for i in range(60)]
    first = select_third_label_sample(ids, seed=42)
    second = select_third_label_sample(ids, seed=42)
    assert first == second
    assert len(first) == 6  # 10% of 60
    assert set(first) <= set(ids)
    different = select_third_label_sample(ids, seed=7)
    assert different != first


def test_third_label_sample_refuses_bad_fraction() -> None:
    """Fractions outside (0, 1) are rejected rather than silently rounded."""
    with pytest.raises(ValueError, match="fraction"):
        select_third_label_sample(["a"], seed=1, fraction=0.0)


# ---------------------------------------------------------------------------
# freeze checker
# ---------------------------------------------------------------------------


def _synthetic_records(*, n_metadata, n_persistent, n_unambiguous) -> list[dict]:
    records: list[dict] = []
    for i in range(n_metadata):
        code = _META_CYCLE[i % len(_META_CYCLE)]
        records.append(
            _record(
                f"meta-{i:03d}",
                METADATA_QUESTION,
                spans=[
                    _span(
                        "sp1", "area", METADATA_QUESTION, code,
                        metadata_resolution=True, channel="metadata",
                    )
                ],
            )
        )
    for i in range(n_persistent):
        code = PERSISTENT_CODES[i % len(PERSISTENT_CODES)]
        records.append(
            _record(
                f"pers-{i:03d}",
                PERSISTENT_QUESTION,
                spans=[
                    _span(
                        "sp1", "top 5", PERSISTENT_QUESTION, code,
                        metadata_resolution=False, channel="clarification",
                    )
                ],
                interpretations=_interpretations(),
            )
        )
    for i in range(n_unambiguous):
        records.append(_record(f"unamb-{i:03d}", UNAMBIGUOUS_QUESTION, spans=[]))
    return records


def test_freeze_fails_on_incomplete_batch(tmp_path) -> None:
    """Freeze refuses an empty or annotation-in-progress batch root."""
    with pytest.raises(AnnotationPrepError, match="no annotation files"):
        freeze_batch(tmp_path)
    _write_valid_batch(tmp_path / "incomplete", token=None)
    (tmp_path / "incomplete" / "meta-000.json").unlink()
    with pytest.raises(AnnotationPrepError, match="batch size"):
        freeze_batch(tmp_path / "incomplete", data_root=tmp_path)


def test_freeze_fails_on_provenance_mismatch(tmp_path) -> None:
    """Every label must have exactly one sidecar entry and vice versa."""
    _write_valid_batch(tmp_path / "batch", token="a" * 64)
    sidecar_path = tmp_path / "batch" / "provenance-v1.json"
    sidecar = load_sidecar(sidecar_path)
    del sidecar["unamb-000"]
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    with pytest.raises(AnnotationPrepError, match="labels without sidecar entries"):
        freeze_batch(tmp_path / "batch", data_root=tmp_path)


def test_freeze_fails_on_placeholder_annotators(tmp_path) -> None:
    """Sidecar annotator ids must be real, not scaffolding."""
    _write_valid_batch(
        tmp_path / "batch",
        token="a" * 64,
        sidecar_annotators=[PLACEHOLDER],
    )
    with pytest.raises(AnnotationPrepError, match="annotator_ids"):
        freeze_batch(tmp_path / "batch", data_root=tmp_path)


def test_freeze_fails_when_enrichment_unavailable_for_metadata_labels(tmp_path) -> None:
    """Metadata-grounded labels cannot freeze without a verifiable snapshot."""
    _write_valid_batch(tmp_path / "batch", token=None)
    with pytest.raises(AnnotationPrepError, match="enrichment snapshot token is unavailable"):
        freeze_batch(tmp_path / "batch", data_root=tmp_path)


def test_freeze_fails_on_gold_field_hit(tmp_path) -> None:
    """Any serialized artifact containing a gold field blocks the freeze."""
    _write_valid_batch(tmp_path / "batch", token=None)
    root = tmp_path / "batch"
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes.json").write_text(
        json.dumps({"sql": "hint"}), encoding="utf-8"
    )
    with pytest.raises(AnnotationPrepError, match="forbidden gold field"):
        freeze_batch(root)


def test_freeze_succeeds_and_is_deterministic(tmp_path) -> None:
    """A complete, provenance-consistent batch freezes with a stable hash."""
    raw = build_beaver_root(tmp_path / "raw")
    build_beaver_metadata(raw)
    token, _ = derive_enrichment_token(raw, "dw")
    _write_valid_batch(tmp_path / "batch", token=token)

    first = freeze_batch(tmp_path / "batch", data_root=raw)
    assert first["sha256"] == first["sha256"]
    assert first["num_questions"] == BATCH1_TARGET == 60
    assert len(first["files"]) == 60 + 1  # labels + provenance sidecar
    assert all("/" not in f and "\\" not in f for f in first["files"])

    second = freeze_batch(tmp_path / "batch", data_root=raw)
    assert second == first


def test_freezer_never_modifies_annotation_files(tmp_path) -> None:
    """freeze_batch is read-only over the label data."""
    raw = build_beaver_root(tmp_path / "raw")
    build_beaver_metadata(raw)
    token, _ = derive_enrichment_token(raw, "dw")
    _write_valid_batch(tmp_path / "batch", token=token)
    before = {
        path.relative_to(tmp_path / "batch"): path.read_bytes()
        for path in (tmp_path / "batch").rglob("*.json")
    }
    freeze_batch(tmp_path / "batch", data_root=raw)
    after = {
        path.relative_to(tmp_path / "batch"): path.read_bytes()
        for path in (tmp_path / "batch").rglob("*.json")
    }
    assert after == before
