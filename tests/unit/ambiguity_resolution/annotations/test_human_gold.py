"""Tests for the Human Gold annotation tooling (docs/23).

Covers the recomputed task list (usable vs deferred), the gold-free UI
payload, record generation and per-record semantic rules, the meta-derived
regeneration, the separate Human Gold freeze (with the frozen AI pilot left
byte-identical), and the app routes behind the local annotation UI.
"""
import json

import pytest

from eaa.ambiguity_resolution.annotations import (
    AnnotationDatasetLoader,
    AnnotationPrepError,
    build_human_provenance,
    build_human_record,
    build_human_task_list,
    freeze_human_gold,
    human_task_payload,
    regenerate_human_records,
    validate_human_record,
)
from eaa.ambiguity_resolution.candidates import GOLD_FIELDS, build_candidate_pool, write_candidates
from eaa.experiments.surface_b_human_annotation import HumanGoldApp, _verify_ai_pilot_lock

pytestmark = pytest.mark.unit

PERSISTENT = {
    "pers-000": "Show the top 5 rooms by area.",
    "pers-001": "List customers with their total revenue.",
}
UNAMBIGUOUS = {
    "unamb-000": "List all buildings.",
    "unamb-001": "Show department names.",
}
DEFERRED = {
    "defer-000": "Show the area for room 25.",
    "defer-001": "Show the room name for room 10.",
}
UNANSWERABLE = {"unans-000": "What was the profit of the merged company?"}

ALL_QUESTIONS = {**PERSISTENT, **UNAMBIGUOUS, **DEFERRED, **UNANSWERABLE}


def _span(
    span_id, text, question_text, code, *, metadata_resolution, channel,
    clarification_required=None,
):
    start = question_text.index(text)
    return {
        "span_id": span_id,
        "text": text,
        "start": start,
        "end": start + len(text),
        "ambiguity_type": code,
        "metadata_resolution": metadata_resolution,
        "clarification_required": (
            not metadata_resolution
            if clarification_required is None
            else clarification_required
        ),
        "assumption_risk": "low",
        "resolution_channel": channel,
    }


def _interpretations():
    return {
        "sql_reading_A": {
            "sql": "SELECT area FROM room ORDER BY area DESC LIMIT 5",
            "note": "largest rooms",
        },
        "sql_reading_B": {
            "sql": "SELECT area FROM room ORDER BY area ASC LIMIT 5",
            "note": "smallest rooms",
        },
    }


def _label(question_id, question_text, *, spans, interpretations=None, unanswerable=False):
    return {
        "schema_version": "annotation-schema-v1",
        "question_id": question_id,
        "question_text": question_text,
        "database_id": "dw",
        "answerability": {
            "label": "unanswerable" if unanswerable else "answerable",
            "confidence": 1.0,
        },
        "spans": spans,
        "interpretations": interpretations,
        "notes": "frozen AI pilot label",
    }


def _write_labels(batch_root):
    labels = batch_root / "dw"
    labels.mkdir(parents=True, exist_ok=True)
    for qid, text in PERSISTENT.items():
        _write_json(
            labels / f"{qid}.json",
            _label(
                qid,
                text,
                spans=[
                    _span(
                        "sp1",
                        "top 5" if qid == "pers-000" else "total revenue",
                        text,
                        "S1" if qid == "pers-000" else "C1",
                        metadata_resolution=False,
                        channel="clarification",
                    )
                ],
                interpretations=_interpretations(),
            ),
        )
    for qid, text in UNAMBIGUOUS.items():
        _write_json(labels / f"{qid}.json", _label(qid, text, spans=[]))
    for qid, text in DEFERRED.items():
        _write_json(
            labels / f"{qid}.json",
            _label(
                qid,
                text,
                spans=[
                    _span(
                        "sp1",
                        "area" if qid == "defer-000" else "room name",
                        text,
                        "L2",
                        metadata_resolution=False,
                        channel="metadata",
                        clarification_required=False,
                    )
                ],
            ),
        )
    _write_json(
        labels / "unans-000.json",
        _label("unans-000", UNANSWERABLE["unans-000"], spans=[], unanswerable=True),
    )
    return labels


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_candidates(tmp_path, make_task, warehouse_schema):
    tasks = [
        make_task(qid, text, "dw") for qid, text in sorted(ALL_QUESTIONS.items())
    ]
    pool = build_candidate_pool(tasks, {"dw": warehouse_schema})
    out = tmp_path / "candidates.json"
    write_candidates(pool, out)
    return out


def _task_list(tmp_path, make_task, warehouse_schema):
    candidates = _write_candidates(tmp_path, make_task, warehouse_schema)
    batch_root = tmp_path / "batch-1"
    _write_labels(batch_root)
    return build_human_task_list(candidates, batch_root)


def _walk_keys(payload, prefix=()):
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = prefix + (str(key),)
            yield path
            yield from _walk_keys(value, path)
    elif isinstance(payload, list):
        for item in payload:
            yield from _walk_keys(item, prefix)


# ---------------------------------------------------------------------------
# task list construction
# ---------------------------------------------------------------------------


def test_task_list_recomputes_split_and_excludes(
    tmp_path, make_task, warehouse_schema
) -> None:
    """Recompute usable/deferred splits from the frozen AI-pilot labels."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    assert task_list["totals"]["usable"] == 4
    assert task_list["totals"]["persistent_ambiguity"] == 2
    assert task_list["totals"]["unambiguous"] == 2
    assert task_list["totals"]["excluded_metadata_deferred"] == 2
    assert task_list["totals"]["excluded_unanswerable"] == 1

    task_ids = {task["question_id"] for task in task_list["tasks"]}
    assert task_ids == set(PERSISTENT) | set(UNAMBIGUOUS)
    assert not task_ids & set(DEFERRED)
    assert not task_ids & set(UNANSWERABLE)

    excluded = {item["question_id"]: item for item in task_list["excluded"]}
    assert excluded["defer-000"]["stratum"] == "metadata_deferred"
    assert "no legitimate enrichment" in excluded["defer-000"]["reason"]
    assert excluded["unans-000"]["stratum"] == "unanswerable"

    rows = {task["question_id"]: task for task in task_list["tasks"]}
    assert rows["pers-000"]["database_id"] == "dw"
    assert rows["pers-000"]["question"] == PERSISTENT["pers-000"]
    assert rows["pers-000"]["frozen_stratum"] == "persistent_ambiguity"
    assert rows["unamb-000"]["frozen_stratum"] == "unambiguous"
    assert [task["question_id"] for task in task_list["tasks"]] == sorted(rows)


def test_task_list_is_deterministic(tmp_path, make_task, warehouse_schema) -> None:
    """Two builds of the same batch produce identical task lists."""
    first = _task_list(tmp_path, make_task, warehouse_schema)
    second = _task_list(tmp_path, make_task, warehouse_schema)
    assert first == second


def test_task_list_requires_candidate_question(
    tmp_path, make_task, warehouse_schema
) -> None:
    """Refuse a label id that is not in the candidate pool."""
    candidates = _write_candidates(tmp_path, make_task, warehouse_schema)
    batch_root = tmp_path / "batch-1"
    labels = _write_labels(batch_root)
    # a usable label id absent from the pool must be refused, not guessed
    _write_json(
        labels / "pers-999.json",
        _label(
            "pers-999",
            "Show the top 5 rooms by area.",
            spans=[
                _span(
                    "sp1",
                    "top 5",
                    "Show the top 5 rooms by area.",
                    "S1",
                    metadata_resolution=False,
                    channel="clarification",
                )
            ],
            interpretations=_interpretations(),
        ),
    )
    with pytest.raises(AnnotationPrepError, match="absent from the candidate pool"):
        build_human_task_list(candidates, batch_root)


def test_task_list_payload_is_gold_free_and_unanchored(
    tmp_path, make_task, warehouse_schema
) -> None:
    """UI payload leaks no gold field and no pilot stratum hint."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    payload = human_task_payload(task_list)
    serialized = json.dumps(payload)
    for path in _walk_keys(payload):
        assert path[-1] not in GOLD_FIELDS, f"gold field leaked at {path}"
    assert "frozen_stratum" not in serialized
    assert "batch-1" not in serialized
    assert len(payload["tasks"]) == 4
    assert payload["tasks"][0]["question"] in ALL_QUESTIONS.values()


# ---------------------------------------------------------------------------
# record generation and per-record semantics
# ---------------------------------------------------------------------------


def test_build_human_record_roundtrips_through_loader(tmp_path) -> None:
    """A built human record validates and reloads through the frozen loader."""
    question = PERSISTENT["pers-000"]
    record = build_human_record(
        question_id="pers-000",
        question_text=question,
        database_id="dw",
        spans=[
            {
                "type": "S1",
                "phrase": "top 5",
                "assumption_risk": "medium",
                "resolution_channel": "clarification",
                "clarification_required": True,
                "metadata_resolution": False,
            }
        ],
        readings=_interpretations(),
        notes="researcher note",
    )
    assert record.question.spans[0].start == question.index("top 5")
    assert record.question.spans[0].text == "top 5"
    assert validate_human_record(record) == []

    # the flat serialization loads cleanly through the frozen loader
    from eaa.ambiguity_resolution.annotations import record_to_flat_dict

    out = tmp_path / "labels" / "pers-000.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record_to_flat_dict(record)), encoding="utf-8")
    dataset = AnnotationDatasetLoader().load(out.parent)
    assert [r.question.question_id for r in dataset.records] == ["pers-000"]


def test_human_validator_rejects_metadata_grounded_without_enrichment() -> None:
    """Metadata-grounded spans require a real enrichment snapshot token."""
    record = build_human_record(
        question_id="q1",
        question_text=PERSISTENT["pers-000"],
        database_id="dw",
        spans=[
            {
                "type": "S1",
                "phrase": "top 5",
                "assumption_risk": "low",
                "resolution_channel": "metadata",
                "clarification_required": False,
                "metadata_resolution": True,
            }
        ],
        readings=_interpretations(),
    )
    problems = validate_human_record(record, enrichment_token=None)
    assert any("metadata_resolution" in problem for problem in problems)
    # a real enrichment token satisfies the rule (no enrichment exists in the repo)
    token = "e" + "a" * 63  # noqa: S106 - arbitrary 64-hex token for the rule check
    assert validate_human_record(record, enrichment_token=token) == []


def test_human_validator_rejects_non_evaluable_span_code() -> None:
    """Span codes outside the evaluable set are refused."""
    record = build_human_record(
        question_id="q1",
        question_text=PERSISTENT["pers-000"],
        database_id="dw",
        spans=[
            {
                "type": "C4",
                "phrase": "top 5",
                "assumption_risk": "low",
                "resolution_channel": "clarification",
                "clarification_required": True,
                "metadata_resolution": False,
            }
        ],
        readings=_interpretations(),
    )
    assert any("non-evaluable code C4" in problem for problem in validate_human_record(record))


def test_human_validator_interpretation_rules() -> None:
    """Enforce the interpretation pairing rules on strict-ambiguity spans."""
    strict = [
        {
            "type": "S1",
            "phrase": "top 5",
            "assumption_risk": "low",
            "resolution_channel": "clarification",
            "clarification_required": True,
            "metadata_resolution": False,
        }
    ]
    missing = build_human_record(
        question_id="q1", question_text=PERSISTENT["pers-000"], database_id="dw", spans=strict
    )
    assert any("interpretations" in problem for problem in validate_human_record(missing))

    unsupported = build_human_record(
        question_id="q2",
        question_text=UNAMBIGUOUS["unamb-000"],
        database_id="dw",
        spans=[],
        readings=_interpretations(),
    )
    assert any(
        "without a strict-ambiguity span" in problem
        for problem in validate_human_record(unsupported)
    )

    identical = build_human_record(
        question_id="q3",
        question_text=PERSISTENT["pers-000"],
        database_id="dw",
        spans=strict,
        readings={
            "sql_reading_A": {"sql": "SELECT 1"},
            "sql_reading_B": {"sql": "SELECT 1"},
        },
    )
    assert any("identical" in problem for problem in validate_human_record(identical))


def test_human_validator_unanswerable_rules() -> None:
    """Unanswerable records must not carry spans or interpretations."""
    with_spans = build_human_record(
        question_id="q1",
        question_text=UNAMBIGUOUS["unamb-000"],
        database_id="dw",
        answerability="unanswerable",
        spans=[
            {
                "type": "S1",
                "phrase": "all buildings",
                "assumption_risk": "low",
                "resolution_channel": "clarification",
                "clarification_required": True,
                "metadata_resolution": False,
            }
        ],
    )
    assert any("unanswerable" in problem for problem in validate_human_record(with_spans))

    clean = build_human_record(
        question_id="q2",
        question_text=UNAMBIGUOUS["unamb-000"],
        database_id="dw",
        answerability="unanswerable",
        spans=[],
    )
    assert validate_human_record(clean) == []


# ---------------------------------------------------------------------------
# meta -> annotations regeneration
# ---------------------------------------------------------------------------


def _meta_decision(question_id, *, spans=None, interpretations=None, notes=None):
    return {
        "question_id": question_id,
        "answerability": {"label": "answerable", "confidence": 1.0},
        "spans": spans or [],
        "interpretations": interpretations,
        "notes": notes,
    }


def _write_human_workspace(tmp_path, task_list):
    root = tmp_path / "human-gold"
    meta = root / "meta"
    for qid, _text in PERSISTENT.items():
        _write_json(
            meta / f"{qid}.json",
            _meta_decision(
                qid,
                spans=[
                    {
                        "type": "S1" if qid == "pers-000" else "C1",
                        "phrase": "top 5" if qid == "pers-000" else "total revenue",
                        "assumption_risk": "medium",
                        "resolution_channel": "clarification",
                        "clarification_required": True,
                        "metadata_resolution": False,
                    }
                ],
                interpretations=_interpretations(),
            ),
        )
    for qid, _text in UNAMBIGUOUS.items():
        _write_json(meta / f"{qid}.json", _meta_decision(qid))
    sidecar = build_human_provenance(
        [t["question_id"] for t in task_list["tasks"]],
        database_id="dw",
        annotator_id="researcher",
    )
    _write_json(root / "provenance-v1.json", sidecar)
    return root


def test_regenerate_records_from_meta(tmp_path, make_task, warehouse_schema) -> None:
    """Regenerate derived annotation records from the raw meta decisions."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    root = _write_human_workspace(tmp_path, task_list)
    written = regenerate_human_records(
        task_list, root / "meta", root / "annotations"
    )
    assert len(written) == 4
    assert sorted(p.name for p in written) == sorted(
        f"{qid}.json" for qid in set(PERSISTENT) | set(UNAMBIGUOUS)
    )
    dataset = AnnotationDatasetLoader().load(root / "annotations")
    assert len(dataset.records) == 4
    by_id = {r.question.question_id: r for r in dataset.records}
    assert by_id["pers-000"].interpretations is not None
    assert by_id["unamb-000"].interpretations is None
    assert by_id["pers-000"].question.question_text == PERSISTENT["pers-000"]


def test_regenerate_rejects_unknown_task(tmp_path, make_task, warehouse_schema) -> None:
    """Refuse regeneration for a meta id absent from the task list."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    root = tmp_path / "human-gold"
    _write_json(root / "meta" / "ghost-000.json", _meta_decision("ghost-000"))
    with pytest.raises(AnnotationPrepError, match="unknown task"):
        regenerate_human_records(task_list, root / "meta", root / "annotations")


# ---------------------------------------------------------------------------
# freeze separation
# ---------------------------------------------------------------------------


def test_freeze_human_gold_separate_lock(tmp_path, make_task, warehouse_schema) -> None:
    """Human Gold freezes to its own lock and leaves the AI pilot intact."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    root = _write_human_workspace(tmp_path, task_list)
    regenerate_human_records(task_list, root / "meta", root / "annotations")

    ai_lock = tmp_path / "surface_b.v1.lock"
    ai_lock.write_text("AI_PILOT_SENTINEL", encoding="utf-8")
    ai_lock_bytes = ai_lock.read_bytes()

    lock = tmp_path / "human-gold.v1.lock"
    record = freeze_human_gold(
        root=root,
        annotator_id="researcher",
        lock_path=lock,
        task_list=task_list,
    )
    assert record["human_gold"] is True
    assert record["annotation_source"] == "human"
    assert record["annotator_id"] == "researcher"
    assert record["separate_from_ai_pilot"] is True
    assert record["num_questions"] == 4
    assert len(record["sha256"]) == 64
    assert lock.is_file()
    assert "human-gold.v1.lock" not in [str(p) for p in record["files"]]

    # the AI-pilot lock file is byte-identical after the Human Gold freeze
    assert ai_lock.read_bytes() == ai_lock_bytes
    # the AI-pilot label directory was never written to by the freeze
    assert sorted(p.name for p in (tmp_path / "batch-1" / "dw").iterdir()) == sorted(
        f"{qid}.json" for qid in ALL_QUESTIONS
    )

    # deterministic: a second freeze reproduces the same digest
    second = freeze_human_gold(
        root=root,
        annotator_id="researcher",
        lock_path=lock,
        task_list=task_list,
    )
    assert second["sha256"] == record["sha256"]


def test_freeze_human_rejects_incomplete_tasks(tmp_path, make_task, warehouse_schema) -> None:
    """Refuse the freeze while any task has no meta decision."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    root = _write_human_workspace(tmp_path, task_list)
    # drop one meta decision so only 3 of 4 tasks are annotated
    (root / "meta" / "unamb-001.json").unlink()
    regenerate_human_records(task_list, root / "meta", root / "annotations")
    with pytest.raises(AnnotationPrepError, match="task set incomplete"):
        freeze_human_gold(
            root=root,
            annotator_id="researcher",
            lock_path=tmp_path / "h.lock",
            task_list=task_list,
        )


def test_freeze_human_rejects_missing_provenance(tmp_path, make_task, warehouse_schema) -> None:
    """Refuse the freeze without the Human Gold provenance sidecar."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    root = _write_human_workspace(tmp_path, task_list)
    regenerate_human_records(task_list, root / "meta", root / "annotations")
    (root / "provenance-v1.json").unlink()
    with pytest.raises(AnnotationPrepError, match="sidecar missing"):
        freeze_human_gold(
            root=root,
            annotator_id="researcher",
            lock_path=tmp_path / "h.lock",
            task_list=task_list,
        )


def test_freeze_human_rejects_wrong_annotator(tmp_path, make_task, warehouse_schema) -> None:
    """The freeze must match the single annotator recorded in the sidecar."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    root = _write_human_workspace(tmp_path, task_list)
    regenerate_human_records(task_list, root / "meta", root / "annotations")
    with pytest.raises(AnnotationPrepError, match="single human annotator"):
        freeze_human_gold(
            root=root,
            annotator_id="someone-else",
            lock_path=tmp_path / "h.lock",
            task_list=task_list,
        )


def test_freeze_human_rejects_metadata_grounded_label(
    tmp_path, make_task, warehouse_schema
) -> None:
    """Refuse a freeze that asserts metadata resolution without enrichment."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    root = _write_human_workspace(tmp_path, task_list)
    # a human asserts metadata resolution although no enrichment snapshot exists
    (root / "meta" / "pers-000.json").write_text(
        json.dumps(
            _meta_decision(
                "pers-000",
                spans=[
                    {
                        "type": "S1",
                        "phrase": "top 5",
                        "assumption_risk": "low",
                        "resolution_channel": "metadata",
                        "clarification_required": False,
                        "metadata_resolution": True,
                    }
                ],
            )
        ),
        encoding="utf-8",
    )
    regenerate_human_records(task_list, root / "meta", root / "annotations")
    with pytest.raises(AnnotationPrepError, match="metadata_resolution"):
        freeze_human_gold(
            root=root,
            annotator_id="researcher",
            lock_path=tmp_path / "h.lock",
            task_list=task_list,
        )


def test_freeze_human_rejects_gold_field_leak(tmp_path, make_task, warehouse_schema) -> None:
    """Refuse a freeze whose root contains any gold-field key."""
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    root = _write_human_workspace(tmp_path, task_list)
    regenerate_human_records(task_list, root / "meta", root / "annotations")
    (root / "stray.json").write_text(
        json.dumps({"question_id": "x", "gold_tables": ["room"]}), encoding="utf-8"
    )
    with pytest.raises(AnnotationPrepError, match="gold field"):
        freeze_human_gold(
            root=root,
            annotator_id="researcher",
            lock_path=tmp_path / "h.lock",
            task_list=task_list,
        )


# ---------------------------------------------------------------------------
# annotation app routes
# ---------------------------------------------------------------------------


def _app(tmp_path, make_task, warehouse_schema):
    task_list = _task_list(tmp_path, make_task, warehouse_schema)
    return HumanGoldApp(
        task_list=task_list,
        schemas={"dw": warehouse_schema},
        human_root=tmp_path / "human-gold",
        annotator_id="researcher",
    )


def test_app_serves_ui_and_gold_free_tasks(tmp_path, make_task, warehouse_schema) -> None:
    """Serve the UI, gold-free task list, status, schema, and per-task routes."""
    app = _app(tmp_path, make_task, warehouse_schema)
    status, _, html = app.route("GET", "/")
    assert status == 200
    assert "Human Gold" in html

    status, payload, _ = app.route("GET", "/api/tasks")
    assert status == 200
    assert len(payload["tasks"]) == 4
    serialized = json.dumps(payload)
    for path in _walk_keys(payload):
        assert path[-1] not in GOLD_FIELDS
    assert "frozen_stratum" not in serialized

    status, status_payload, _ = app.route("GET", "/api/status")
    assert status == 200
    assert status_payload["annotator_id"] == "researcher"
    assert status_payload["annotated"] == 0

    status, schema_payload, _ = app.route("GET", "/api/schemas")
    assert status == 200
    assert schema_payload["dw"]["tables"][0]["name"] == "customers"

    status, task_payload, _ = app.route("GET", "/api/task/pers-000")
    assert status == 200
    assert task_payload["question"] == PERSISTENT["pers-000"]
    assert task_payload["saved"] is False

    status, missing, _ = app.route("GET", "/api/task/ghost-000")
    assert status == 404


def test_app_save_validates_and_persists(tmp_path, make_task, warehouse_schema) -> None:
    """Saving validates, persists meta + derived annotation, and rejects bad input."""
    app = _app(tmp_path, make_task, warehouse_schema)
    status, result, _ = app.route(
        "POST",
        "/api/task/pers-000/annotation",
        {
            "answerability": {"label": "answerable", "confidence": 1.0},
            "spans": [
                {
                    "type": "S1",
                    "phrase": "top 5",
                    "assumption_risk": "medium",
                    "resolution_channel": "clarification",
                    "clarification_required": True,
                    "metadata_resolution": False,
                }
            ],
            "interpretations": _interpretations(),
            "notes": "manual check",
        },
    )
    assert status == 200
    assert result["saved"] is True
    assert (app.root / "meta" / "pers-000.json").is_file()
    assert (app.root / "annotations" / "pers-000.json").is_file()
    status, status_payload, _ = app.route("GET", "/api/status")
    assert status_payload["annotated"] == 1

    # invalid: phrase absent from the question text
    status, bad, _ = app.route(
        "POST",
        "/api/task/pers-000/annotation",
        {
            "spans": [
                {
                    "type": "S1",
                    "phrase": "not in the question",
                    "resolution_channel": "clarification",
                    "clarification_required": True,
                    "metadata_resolution": False,
                }
            ],
            "interpretations": _interpretations(),
        },
    )
    assert status == 400

    # invalid: metadata-grounded span without an enrichment snapshot
    status, bad_meta, _ = app.route(
        "POST",
        "/api/task/pers-000/annotation",
        {
            "spans": [
                {
                    "type": "S1",
                    "phrase": "top 5",
                    "resolution_channel": "metadata",
                    "clarification_required": False,
                    "metadata_resolution": True,
                }
            ],
            "interpretations": _interpretations(),
        },
    )
    assert status == 400
    assert any("metadata_resolution" in p for p in bad_meta["problems"])

    status, unknown, _ = app.route("POST", "/api/task/ghost-000/annotation", {})
    assert status == 404


def test_app_regenerate_route(tmp_path, make_task, warehouse_schema) -> None:
    """The regenerate route re-derives annotations from saved meta decisions."""
    app = _app(tmp_path, make_task, warehouse_schema)
    status, result, _ = app.route(
        "POST",
        "/api/task/unamb-000/annotation",
        {"answerability": {"label": "answerable", "confidence": 1.0}, "spans": []},
    )
    assert status == 200
    status, result, _ = app.route("POST", "/api/regenerate")
    assert status == 200
    assert result["regenerated"] == 1


# ---------------------------------------------------------------------------
# AI-pilot lock integrity check
# ---------------------------------------------------------------------------


def test_verify_ai_pilot_lock_reproduces_digest(tmp_path) -> None:
    """Reproduce the AI-pilot lock digest and detect tampering."""
    from eaa.ambiguity_resolution.annotations.qc import _freeze_digest

    batch = tmp_path / "batch-1"
    (batch / "dw").mkdir(parents=True)
    label = {"schema_version": "annotation-schema-v1", "question_id": "dw_0"}
    (batch / "dw" / "dw_0.json").write_text(json.dumps(label), encoding="utf-8")
    (batch / "provenance-v1.json").write_text('{"dw_0": {}}', encoding="utf-8")
    files = [
        p.relative_to(batch)
        for p in [batch / "dw" / "dw_0.json", batch / "provenance-v1.json"]
    ]
    digest = _freeze_digest(sorted(files), base=batch)

    lock = tmp_path / "surface_b.v1.lock"
    lock.write_text(
        json.dumps({"sha256": digest, "files": [str(f) for f in sorted(files)]}),
        encoding="utf-8",
    )
    ok, expected = _verify_ai_pilot_lock(batch, lock)
    assert ok
    assert expected == digest

    # touching a hashed file invalidates the verification
    (batch / "dw" / "dw_0.json").write_text(
        json.dumps({**label, "notes": "tampered"}), encoding="utf-8"
    )
    ok, _ = _verify_ai_pilot_lock(batch, lock)
    assert ok is False
