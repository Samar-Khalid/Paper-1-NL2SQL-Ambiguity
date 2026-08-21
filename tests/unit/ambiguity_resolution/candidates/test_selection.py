"""Tests for the Surface B candidate pool builder and artifact I/O."""
import asyncio

import pytest
from beaver_data import build_beaver_root

from eaa.ambiguity_resolution.candidates import (
    CANDIDATE_SCHEMA_VERSION,
    GOLD_FIELDS,
    CandidateSelectionError,
    build_candidate_pool,
    candidate_to_dict,
    load_candidates,
    write_candidates,
)
from eaa.datasets.adapters.beaver import BeaverAdapter

pytestmark = pytest.mark.unit


def _questions() -> list[str]:
    return [
        "What is the total area of history department buildings?",
        "List buildings built before 1950.",
        "Count rooms per building.",
    ]


def _pool_source() -> dict:
    return {"checksum": "abc123", "data_root": "data/raw/beaver", "databases": ["dw"]}


def test_pool_has_unique_ids_and_preserved_databases(
    make_task, warehouse_schema
) -> None:
    """Every candidate keeps its id, database id, and question text."""
    tasks = [
        make_task("dw:0001", _questions()[0], "dw"),
        make_task("dw:0002", _questions()[1], "dw"),
    ]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema}, source=_pool_source())
    assert pool.schema_version == CANDIDATE_SCHEMA_VERSION
    assert len(pool.candidates) == 2
    assert {c.question_id for c in pool.candidates} == {"dw:0001", "dw:0002"}
    assert {c.database_id for c in pool.candidates} == {"dw"}
    assert {c.question for c in pool.candidates} == set(_questions()[:2])


def test_pool_never_leaks_gold_fields(make_task, warehouse_schema) -> None:
    """Candidate records contain no gold fields (ADR-009 hard rule)."""
    tasks = [make_task("q1", question, "dw") for question in _questions()]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    for record in pool.candidates:
        emitted = candidate_to_dict(record)
        assert GOLD_FIELDS.isdisjoint(emitted)
        for hit in emitted["selection_signals"]:
            assert GOLD_FIELDS.isdisjoint(hit)


def test_counts_by_database_and_signal(make_task, warehouse_schema) -> None:
    """Aggregate counts are computed and reported per database and signal."""
    tasks = [
        make_task("q1", "What is the total amount of revenue?", "dw"),
        make_task("q2", "Show all status values.", "dw"),
        make_task("q3", "List buildings built before 1950.", "nova"),
    ]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    assert pool.counts_by_database() == {"dw": 2, "nova": 1}
    assert pool.counts_by_signal()["c1"] == 1
    assert pool.counts_by_signal()["v1"] == 1
    assert pool.counts_by_signal()["r1"] == 1
    assert pool.with_any_signal() == 3
    assert pool.without_signal() == 0


def test_unknown_database_falls_back_to_textual_signals(
    make_task, warehouse_schema
) -> None:
    """A database without a schema is scored with textual signals only."""
    task = make_task("q1", "Show all status values.", "nova")
    pool = build_candidate_pool([task], {})
    record = pool.candidates[0]
    assert record.database_id == "nova"
    assert all(hit.signal != "r1" and hit.signal != "r2" for hit in record.signals)
    assert any(hit.signal == "s1" for hit in record.signals)


def test_artifact_round_trip_is_reproducible(
    tmp_path, make_task, warehouse_schema
) -> None:
    """Writing then loading the artifact reproduces the pool byte-for-byte."""
    tasks = [make_task("q1", question, "dw") for question in _questions()]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema}, source=_pool_source())
    out = tmp_path / "candidates.json"

    write_candidates(pool, out)
    first_bytes = out.read_bytes()
    write_candidates(pool, out)
    assert out.read_bytes() == first_bytes

    loaded = load_candidates(out)
    assert loaded.schema_version == CANDIDATE_SCHEMA_VERSION
    assert loaded.source["checksum"] == "abc123"
    assert len(loaded.candidates) == 3
    assert {
        (c.question_id, c.database_id, c.question, c.signals) for c in loaded.candidates
    } == {(c.question_id, c.database_id, c.question, c.signals) for c in pool.candidates}
    assert loaded.counts_by_database() == pool.counts_by_database()
    assert loaded.counts_by_signal() == pool.counts_by_signal()


def test_artifact_contains_no_gold_fields_in_json(
    tmp_path, make_task, warehouse_schema
) -> None:
    """The serialized artifact itself is free of gold field names."""
    tasks = [make_task("q1", question, "dw") for question in _questions()]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    out = tmp_path / "candidates.json"
    write_candidates(pool, out)
    text = out.read_text(encoding="utf-8")
    for field in GOLD_FIELDS:
        assert f'"{field}"' not in text


def test_malformed_question_raises(make_task, warehouse_schema) -> None:
    """A task without question text is rejected with a typed error."""
    import types

    bad = types.SimpleNamespace(
        header=types.SimpleNamespace(task_id="bad"),
        payload=types.SimpleNamespace(database_id="dw"),
    )
    with pytest.raises(CandidateSelectionError, match="no question"):
        build_candidate_pool([bad], {"dw": warehouse_schema})


def test_malformed_database_id_raises(make_task, warehouse_schema) -> None:
    """A task without a database id is rejected with a typed error."""
    import types

    bad = types.SimpleNamespace(
        header=types.SimpleNamespace(task_id="bad"),
        payload=types.SimpleNamespace(question="What is revenue?"),
    )
    with pytest.raises(CandidateSelectionError, match="no database_id"):
        build_candidate_pool([bad], {"dw": warehouse_schema})


def test_empty_pool_is_valid(tmp_path) -> None:
    """An empty task stream produces a valid, loadable artifact."""
    pool = build_candidate_pool([], {})
    assert pool.counts_by_database() == {}
    assert pool.without_signal() == 0
    out = tmp_path / "candidates.json"
    write_candidates(pool, out)
    assert load_candidates(out).candidates == ()


def test_pool_from_adapter_task_stream(tmp_path) -> None:
    """The pool builds from the public BEAVER adapter task stream."""
    root = build_beaver_root(tmp_path / "beaver")
    adapter = BeaverAdapter(str(root))
    adapter.validate()
    provider = adapter.schema_provider()
    schemas = {"dw": provider.get_schema("dw")}

    tasks = asyncio.run(_collect_tasks(adapter))
    assert tasks
    pool = build_candidate_pool(tasks, schemas, source=adapter.manifest().extra)
    assert pool.counts_by_database() == {"dw": len(tasks)}
    assert all(c.database_id == "dw" for c in pool.candidates)


async def _collect_tasks(adapter: BeaverAdapter) -> list:
    return [task async for task in adapter.task_stream("dev")]
