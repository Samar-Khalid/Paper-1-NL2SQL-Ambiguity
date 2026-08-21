"""Tests for the Paper 1 live demo (docs/22, demo.py).

The demo is research tooling over the frozen detectors: deterministic under
repeated calls, structurally valid, honest about unavailable legs, and free of
any gold-field coupling.
"""
import inspect
import json

import pytest

from eaa.ambiguity_resolution.demo import (
    BASELINE_DISPLAY_CONFIDENCE,
    BASELINE_SOURCE,
    DEMO_DISCLAIMER,
    DemoAnalysis,
    analyze_demo,
    analyze_question,
    render_analysis,
)
from eaa.core.contracts.ambiguity import AmbiguityAnalysis, AmbiguityVerdict
from eaa.core.contracts.llm import Completion, Message, Usage
from eaa.core.contracts.schema import (
    ColumnSchema,
    DatabaseSchema,
    ForeignKeySpec,
    TableSchema,
)
from eaa.experiments.ambiguity_demo import example_questions

pytestmark = pytest.mark.unit


def _schema() -> DatabaseSchema:
    """Provide a minimal two-table schema with one foreign key."""
    return DatabaseSchema(
        database_id="dw",
        dialect="mysql",
        tables=[
            TableSchema(
                name="departments",
                columns=[
                    ColumnSchema(name="id", data_type="int", primary_key=True),
                    ColumnSchema(name="name", data_type="varchar"),
                ],
            ),
            TableSchema(
                name="courses",
                columns=[
                    ColumnSchema(name="id", data_type="int", primary_key=True),
                    ColumnSchema(name="name", data_type="varchar"),
                    ColumnSchema(
                        name="department_id",
                        data_type="int",
                        foreign_key=ForeignKeySpec(
                            column="department_id",
                            references_table="departments",
                            references_column="id",
                        ),
                    ),
                    ColumnSchema(name="year", data_type="int"),
                ],
            ),
        ],
    )


class _FixedBackend:
    """Deterministic LLM backend for reasoning-leg tests."""

    model_id = "fixed-demo-test"

    def __init__(self, content: str) -> None:
        self._content = content

    def complete(self, messages, params=None) -> Completion:
        return Completion(
            message=Message(role="assistant", content=self._content),
            usage=Usage(),
            model_id=self.model_id,
            finish_reason="stop",
        )

    def complete_async(self, messages, params=None) -> Completion:
        return self.complete(messages, params)


def _reasoning_response(spans: list[dict], confidence: float = 0.6) -> str:
    return json.dumps({"verdict": "ambiguous", "confidence": confidence, "spans": spans})


# -- analyze_question (the pipeline-facing interface) -----------------------


def test_analyze_question_returns_valid_contract() -> None:
    """Return a structurally valid AmbiguityAnalysis contract."""
    analysis = analyze_question("List all courses.", _schema())
    assert isinstance(analysis, AmbiguityAnalysis)
    assert analysis.database_id == "dw"
    assert analysis.verdict == AmbiguityVerdict.AMBIGUOUS
    for span in analysis.ambiguous_spans:
        assert span.start >= 0
        assert span.end > span.start
        assert span.end <= len("List all courses.")
        assert span.snippet == "List all courses."[span.start : span.end]
        assert span.confidence == 0.0


def test_analyze_question_unambiguous_when_no_signals() -> None:
    """Report UNAMBIGUOUS when no screening signals fire."""
    analysis = analyze_question("Show me the names.", _schema())
    assert analysis.verdict == AmbiguityVerdict.UNAMBIGUOUS
    assert analysis.ambiguous_spans == []
    assert analysis.detected_types == []


def test_analyze_question_is_deterministic() -> None:
    """Produce identical output on repeated calls."""
    question = "List all courses from last year."
    assert analyze_question(question, _schema()) == analyze_question(question, _schema())


def test_analyze_question_emits_scope_and_temporal_spans() -> None:
    """Emit S1 and T1 spans for a scope-plus-temporal question."""
    analysis = analyze_question("List all courses from last year.", _schema())
    codes = {span.type.value for span in analysis.ambiguous_spans}
    assert {"S1", "T1"} <= codes


def test_analyze_question_rejects_empty_question() -> None:
    """Reject a blank question with ValueError."""
    with pytest.raises(ValueError):
        analyze_question("   ", _schema())


# -- analyze_demo (the human-readable view) ---------------------------------


def test_analyze_demo_baseline_report() -> None:
    """Build a baseline DemoAnalysis with honest status fields."""
    question = "List all departments that have no students enrolled this year."
    result = analyze_demo(question, _schema())
    assert isinstance(result, DemoAnalysis)
    assert result.ambiguous is True
    assert result.verdict == AmbiguityVerdict.AMBIGUOUS
    assert result.detector_mode == "baseline"
    assert BASELINE_SOURCE in result.detector_source
    assert result.clarification_required is True
    assert result.interpretations == ()
    assert result.confidence == BASELINE_DISPLAY_CONFIDENCE
    assert "no real LLM backend" in result.llm_backend_status
    assert "ADR-015" in result.metadata_status
    for span in result.spans:
        assert span.start >= 0 and span.end <= len(question)
        assert span.text == question[span.start : span.end]
        assert span.source == BASELINE_SOURCE
        assert span.confidence == BASELINE_DISPLAY_CONFIDENCE


def test_analyze_demo_is_deterministic() -> None:
    """Produce identical DemoAnalysis on repeated calls."""
    question = "List all departments that have no students enrolled this year."
    assert analyze_demo(question, _schema()) == analyze_demo(question, _schema())


def test_analyze_demo_reasoning_unavailable_is_reported() -> None:
    """Report the reasoning leg as unavailable when no backend is given."""
    result = analyze_demo("List all courses.", _schema(), mode="reasoning")
    assert result.llm_backend_status.startswith("unavailable")
    assert any("no real LLM backend" in warning for warning in result.warnings)
    assert result.detector_mode == "baseline (reasoning requested but unavailable)"
    assert BASELINE_SOURCE in result.detector_source


def test_analyze_demo_combined_merges_baseline_and_reasoning() -> None:
    """Merge baseline and reasoning spans, deduplicating by (code, start, end)."""
    backend = _FixedBackend(
        _reasoning_response([{"type": "T1", "start": 9, "end": 16, "reasoning": "relative time"}])
    )
    result = analyze_demo(
        "List all courses.", _schema(), mode="combined", llm_backend=backend
    )
    assert result.verdict == AmbiguityVerdict.AMBIGUOUS
    sources = {span.source for span in result.spans}
    assert BASELINE_SOURCE in sources
    assert "ReasoningBasedDetector" in sources
    assert "configured" in result.llm_backend_status
    temporal = [span for span in result.spans if span.code == "T1"]
    assert len(temporal) == 1
    assert temporal[0].text == "courses"
    assert temporal[0].start == 9 and temporal[0].end == 16
    assert temporal[0].source == "ReasoningBasedDetector"
    assert temporal[0].confidence == 0.6


def test_analyze_demo_reasoning_mode_uses_reasoning_only() -> None:
    """Report only reasoning-leg spans in reasoning mode."""
    backend = _FixedBackend(
        _reasoning_response([{"type": "T1", "start": 9, "end": 16, "reasoning": "relative time"}])
    )
    result = analyze_demo(
        "List all courses.", _schema(), mode="reasoning", llm_backend=backend
    )
    assert result.detector_mode == "reasoning"
    assert {span.source for span in result.spans} == {"ReasoningBasedDetector"}
    assert {span.code for span in result.spans} == {"T1"}


def test_analyze_demo_reasoning_failure_is_reported_not_silent() -> None:
    """Surface a reasoning-leg failure as a warning, not silent fallback."""
    backend = _FixedBackend("this is not json")
    result = analyze_demo(
        "List all courses.", _schema(), mode="combined", llm_backend=backend
    )
    assert result.llm_backend_status.startswith("failed")
    assert any("reasoning leg failed" in warning for warning in result.warnings)
    assert result.ambiguous
    assert BASELINE_SOURCE in result.detector_source


def test_analyze_demo_metadata_mode_is_rejected() -> None:
    """Reject the metadata mode until real enrichment exists (ADR-015)."""
    with pytest.raises(ValueError, match="metadata"):
        analyze_demo("List all courses.", _schema(), mode="metadata")


def test_analyze_demo_rejects_empty_question() -> None:
    """Reject a blank question with ValueError."""
    with pytest.raises(ValueError):
        analyze_demo("  ", _schema())


def test_analyze_demo_does_not_fabricate_interpretations() -> None:
    """Report no SQL interpretations in baseline mode."""
    result = analyze_demo("List all courses.", _schema())
    assert result.interpretations == ()
    rendered = render_analysis(result)
    assert "authors no SQL readings" in rendered


# -- rendering --------------------------------------------------------------


def test_render_analysis_contains_expected_sections() -> None:
    """Render all report sections with ASCII-only text."""
    result = analyze_demo("List all courses.", _schema())
    text = render_analysis(result)
    assert "PAPER 1 DEMO" in text
    assert "question :" in text
    assert "verdict  :" in text
    assert "SCREENING SIGNALS" in text
    assert "STATUS" in text
    assert "DISCLAIMER" in text
    assert DEMO_DISCLAIMER in text
    assert "not a benchmark evaluation" in text
    assert "\u2014" not in text


# -- example curation -------------------------------------------------------


def _candidate(question_id: str, question: str, signal: str) -> dict[str, object]:
    return {
        "question_id": question_id,
        "database_id": "dw",
        "question": question,
        "selection_signals": [
            {"signal": signal, "name": signal, "evidence": [question.split()[-1]]}
        ],
    }


def test_example_questions_curates_targets_and_control(tmp_path) -> None:
    """Curate one example per target signal plus the labelled control."""
    payload = {
        "schema_version": "surface-b-candidate-v1",
        "candidates": [
            _candidate("q1", "List all courses", "s1"),
            _candidate("q2", "Show departments", "r1"),
            _candidate("q3", "Courses and departments", "r2"),
            _candidate("q4", "How many courses", "c1"),
            _candidate("q5", "Courses last year", "t1"),
            _candidate("q6", "Cost 100 dollars", "v1"),
        ],
    }
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    examples = example_questions(path)
    assert len(examples) == 7
    labels = [label for _, _, _, label in examples]
    assert any("scope/constraint" in label for label in labels)
    assert any("table-selection" in label for label in labels)
    assert any("control" in label for label in labels)
    assert all(question_id != "dw_real" for _, question_id, _, _ in examples)


# -- gold-freedom guard -----------------------------------------------------


def test_demo_source_never_references_gold_fields() -> None:
    """Keep the demo source structurally free of any gold-field coupling."""
    from eaa.ambiguity_resolution import demo

    source = inspect.getsource(demo)
    for field in ("gold_sql", "oracle_sql", "gold_tables", "join_keys", "sub_sqls"):
        assert field not in source
