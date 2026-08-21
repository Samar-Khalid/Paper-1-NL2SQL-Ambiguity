"""Tests for the reasoning-based ambiguity detector (docs/14 §4B)."""
import json

import pytest

from eaa.ambiguity_resolution.detectors.metadata_grounded import (
    METADATA_GROUNDED_TYPES,
)
from eaa.ambiguity_resolution.detectors.reasoning_based import (
    REASONING_TYPES,
    SYSTEM_PROMPT,
    ReasoningBasedDetector,
)
from eaa.ambiguity_resolution.errors import AmbiguityResolutionError
from eaa.core.contracts.ambiguity import AmbiguityType, AmbiguityVerdict
from eaa.core.contracts.base import Payload
from eaa.core.contracts.errors import PipelineError
from eaa.core.contracts.llm import Completion, Message, Usage
from eaa.core.contracts.runtime import Budget, RuntimeContext, SessionState
from eaa.core.contracts.task import TaskEnvelope, TaskHeader
from eaa.core.interfaces.ambiguity import AmbiguityResolver
from eaa.core.pipeline import BUDGET_LEDGER_KEY, BudgetLedger
from eaa.core.registry import envelope_for

pytestmark = pytest.mark.unit


class _FixedBackend:
    """Deterministic backend returning a fixed assistant message."""

    model_id = "fixed-reasoning-test"

    def __init__(
        self,
        content: str,
        *,
        usage: Usage | None = None,
        record_prompts: bool = False,
    ) -> None:
        self._content = content
        self._usage = usage or Usage()
        self._record_prompts = record_prompts
        self.prompts: list[list[Message]] = []

    def complete(
        self, messages: list[Message], params=None
    ) -> Completion:
        if self._record_prompts:
            self.prompts.append(messages)
        return Completion(
            message=Message(role="assistant", content=self._content),
            usage=self._usage,
            model_id=self.model_id,
            finish_reason="stop",
        )

    def complete_async(
        self, messages: list[Message], params=None
    ) -> Completion:
        return self.complete(messages, params)


def _response(verdict: str, spans: list[dict], confidence: float = 0.8) -> str:
    return json.dumps(
        {"verdict": verdict, "confidence": confidence, "spans": spans}
    )


def _span(
    type_: str,
    start: int,
    end: int,
    reasoning: str = "why",
    confidence: float | None = None,
) -> dict:
    span = {"type": type_, "start": start, "end": end, "reasoning": reasoning}
    if confidence is not None:
        span["confidence"] = confidence
    return span


def _task(question: str) -> TaskEnvelope:
    return envelope_for(
        TaskEnvelope,
        "nl2sql",
        {
            "header": {
                "task_id": "t1",
                "question": question,
                "dataset_id": "dw",
                "dialect": "mysql",
            },
            "payload": {
                "question": question,
                "database_id": "dw",
                "schema_id": None,
                "allowed_tables": None,
            },
        },
    )


def _context() -> RuntimeContext:
    context = RuntimeContext(session=SessionState(session_id="s1"), budget=Budget())
    ledger = BudgetLedger(context.budget)
    return context.model_copy(update={"state": {BUDGET_LEDGER_KEY: ledger}})


def _spans_consistent(question: str, analysis) -> None:
    """Every span must index the question and carry a legal confidence."""
    for span in analysis.ambiguous_spans:
        assert span.start >= 0 and span.end > span.start
        assert 0.0 <= span.confidence <= 1.0
        assert question[span.start : span.end] == span.snippet


POSITIVE_CASES = [
    (AmbiguityType.QUANTIFIER_SCOPE, "S1",
     "Customers who did not order product A and product B.",
     "did not order product A and product B"),
    (AmbiguityType.ATTACHMENT, "S2",
     "Orders for customers in Germany by sales manager.",
     "by sales manager"),
    (AmbiguityType.JOIN_PATH, "R2",
     "Orders shipped by the supplier's own warehouse.",
     "by the supplier's own warehouse"),
    (AmbiguityType.AGGREGATION_METRIC, "C1",
     "What is the average order value?",
     "average order value"),
    (AmbiguityType.TOP_N_RANKING, "C2",
     "Top 5 products by revenue.",
     "Top 5 products"),
    (AmbiguityType.EXISTENCE_NEGATION, "C3",
     "Show customers with no returns and no complaints.",
     "no returns and no complaints"),
    (AmbiguityType.RELATIVE_TEMPORAL, "T1",
     "How many orders this week?",
     "this week"),
    (AmbiguityType.EXTERNAL_KNOWLEDGE, "K1",
     "What is the market capitalization of our top customers?",
     "market capitalization"),
    (AmbiguityType.CHANNEL_ENCODING, "I2",
     "Give me the revenue as a table.",
     "as a table"),
    (AmbiguityType.CHART_TYPE, "I3",
     "Chart revenue by month.",
     "Chart"),
]


def test_reasoning_types_are_the_ten_persistent_types() -> None:
    """Only S1/S2/R2/C1/C2/C3/T1/K1/I2/I3 belong to the reasoning family."""
    assert set(REASONING_TYPES) == {
        AmbiguityType.QUANTIFIER_SCOPE,
        AmbiguityType.ATTACHMENT,
        AmbiguityType.JOIN_PATH,
        AmbiguityType.AGGREGATION_METRIC,
        AmbiguityType.TOP_N_RANKING,
        AmbiguityType.EXISTENCE_NEGATION,
        AmbiguityType.RELATIVE_TEMPORAL,
        AmbiguityType.EXTERNAL_KNOWLEDGE,
        AmbiguityType.CHANNEL_ENCODING,
        AmbiguityType.CHART_TYPE,
    }


def test_reasoning_types_disjoint_from_metadata_grounded_types() -> None:
    """The two evidence families never overlap (docs/14 §4, docs/15 §3.4)."""
    assert set(REASONING_TYPES).isdisjoint(METADATA_GROUNDED_TYPES)


def test_detector_satisfies_resolver_protocol(dw_schema) -> None:
    """The detector is structurally an ``AmbiguityResolver`` (analyze + resolve)."""
    backend = _FixedBackend(_response("unambiguous", []))
    assert isinstance(ReasoningBasedDetector(dw_schema, backend), AmbiguityResolver)


@pytest.mark.parametrize(
    "expected, code, question, snippet",
    POSITIVE_CASES,
    ids=[case[1] for case in POSITIVE_CASES],
)
def test_positive_single_type(dw_schema, expected, code, question, snippet) -> None:
    """Each in-scope type is surfaced with a valid span (docs/13 §2)."""
    start = question.index(snippet)
    end = start + len(snippet)
    backend = _FixedBackend(
        _response("ambiguous", [_span(code, start, end, "two readings")], 0.8)
    )
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task(question), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.AMBIGUOUS
    assert analysis.detected_types == [expected]
    assert len(analysis.ambiguous_spans) == 1
    span = analysis.ambiguous_spans[0]
    assert span.type == expected
    assert span.snippet == snippet
    assert span.confidence == 0.8
    _spans_consistent(question, analysis)


def test_positive_multiple_simultaneous_types(dw_schema) -> None:
    """Compounded persistent ambiguity is multi-label (docs/13 §6.4)."""
    question = "How many orders did our top customers place last quarter?"
    start = question.index("top customers")
    c2 = _span("C2", start, start + len("top customers"), "ranking undefined")
    start = question.index("last quarter")
    t1 = _span("T1", start, start + len("last quarter"), "relative period")
    backend = _FixedBackend(_response("ambiguous", [c2, t1], 0.9))
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task(question), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.AMBIGUOUS
    assert analysis.detected_types == [
        AmbiguityType.TOP_N_RANKING,
        AmbiguityType.RELATIVE_TEMPORAL,
    ]
    assert {
        (span.type, span.snippet) for span in analysis.ambiguous_spans
    } == {
        (AmbiguityType.TOP_N_RANKING, "top customers"),
        (AmbiguityType.RELATIVE_TEMPORAL, "last quarter"),
    }
    assert analysis.confidence == 0.9
    _spans_consistent(question, analysis)


def test_negative_unambiguous(dw_schema) -> None:
    """A judgment of no persistent ambiguity yields an unambiguous analysis."""
    backend = _FixedBackend(_response("unambiguous", [], 0.95))
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task("How many customers exist?"), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.UNAMBIGUOUS
    assert analysis.detected_types == []
    assert analysis.ambiguous_spans == []
    assert analysis.confidence == 0.0


def test_out_of_scope_type_dropped_conservatively(dw_schema) -> None:
    """A metadata-grounded type is not emitted by the reasoning family."""
    question = "What was revenue in millions?"
    start = question.index("millions")
    backend = _FixedBackend(
        _response("ambiguous", [_span("V2", start, start + len("millions"))], 0.8)
    )
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task(question), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.UNAMBIGUOUS
    assert analysis.ambiguous_spans == []
    assert analysis.confidence == 0.0


def test_unknown_type_dropped_conservatively(dw_schema) -> None:
    """An unknown taxonomy code is dropped rather than guessed at."""
    question = "How many orders this week?"
    start = question.index("this week")
    backend = _FixedBackend(
        _response("ambiguous", [_span("Q9", start, start + len("this week"))], 0.8)
    )
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task(question), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.UNAMBIGUOUS


def test_mixed_in_and_out_of_scope_spans(dw_schema) -> None:
    """In-scope spans survive; out-of-scope ones are dropped (docs/15 §3.4)."""
    question = "Top 5 products by revenue in millions?"
    start = question.index("Top 5 products")
    c2 = _span("C2", start, start + len("Top 5 products"))
    start = question.index("millions")
    v2 = _span("V2", start, start + len("millions"))
    backend = _FixedBackend(_response("ambiguous", [c2, v2], 0.8))
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task(question), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.AMBIGUOUS
    assert analysis.detected_types == [AmbiguityType.TOP_N_RANKING]
    assert len(analysis.ambiguous_spans) == 1
    assert analysis.ambiguous_spans[0].snippet == "Top 5 products"


def test_invalid_span_offsets_dropped(dw_schema) -> None:
    """Spans outside the question or malformed offsets are rejected."""
    question = "How many orders this week?"
    backend = _FixedBackend(
        _response(
            "ambiguous",
            [
                _span("T1", -2, 5, "start below zero"),
                _span("T1", 3, 3, "empty"),
                _span("T1", 4, 999, "beyond end"),
                _span("T1", 10, 4, "reversed"),
            ],
            0.8,
        )
    )
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task(question), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.UNAMBIGUOUS
    assert analysis.ambiguous_spans == []


def test_duplicate_spans_deduplicated(dw_schema) -> None:
    """Identical (type, start, end) spans collapse to one (docs/13 §3)."""
    question = "How many orders this week?"
    start = question.index("this week")
    end = start + len("this week")
    backend = _FixedBackend(
        _response(
            "ambiguous",
            [_span("T1", start, end), _span("T1", start, end)],
            0.8,
        )
    )
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task(question), _context()
    )
    assert len(analysis.ambiguous_spans) == 1
    assert analysis.detected_types == [AmbiguityType.RELATIVE_TEMPORAL]


def test_span_confidence_defaults_to_overall(dw_schema) -> None:
    """A span without its own confidence inherits the overall signal."""
    question = "Top 5 products by revenue."
    start = question.index("Top 5 products")
    backend = _FixedBackend(
        _response(
            "ambiguous",
            [_span("C2", start, start + len("Top 5 products"))],
            0.7,
        )
    )
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task(question), _context()
    )
    assert analysis.ambiguous_spans[0].confidence == 0.7
    assert analysis.confidence == 0.7


def test_confidence_clamped_to_unit_interval(dw_schema) -> None:
    """Confidence is clamped into [0, 1] before entering the contract."""
    question = "Top 5 products by revenue."
    start = question.index("Top 5 products")
    backend = _FixedBackend(
        _response(
            "ambiguous",
            [_span("C2", start, start + len("Top 5 products"), confidence=2.0)],
            1.5,
        )
    )
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task(question), _context()
    )
    assert analysis.confidence == 1.0
    assert analysis.ambiguous_spans[0].confidence == 1.0


def test_confidence_zero_when_missing(dw_schema) -> None:
    """A judgment without a confidence signal records no claim (0.0)."""
    content = json.dumps(
        {
            "verdict": "ambiguous",
            "spans": [{"type": "T1", "start": 0, "end": 1}],
        }
    )
    analysis = ReasoningBasedDetector(dw_schema, _FixedBackend(content)).analyze(
        _task("How many orders this week?"), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.AMBIGUOUS
    assert analysis.confidence == 0.0


def test_prompt_contains_question_and_schema(dw_schema) -> None:
    """The judgment context carries the question and a compact schema."""
    backend = _FixedBackend(_response("unambiguous", []), record_prompts=True)
    detector = ReasoningBasedDetector(dw_schema, backend)
    question = "How many active customers last quarter?"
    detector.analyze(_task(question), _context())
    user_message = backend.prompts[0][-1].content
    assert question in user_message
    assert "TABLE orders" in user_message
    assert "customer_id FK->customers.customer_id" in user_message


def test_prompt_includes_enrichment_when_present(dw_schema) -> None:
    """Metadata context is given to the judgment when available (docs/14 §4B)."""
    backend = _FixedBackend(_response("unambiguous", []), record_prompts=True)
    detector = ReasoningBasedDetector(dw_schema, backend)
    detector.analyze(_task("How many active customers last quarter?"), _context())
    user_message = backend.prompts[0][-1].content
    assert "Enterprise metadata:" in user_message
    assert 'business term "revenue"' in user_message
    assert "customer profile records" in user_message


def test_prompt_omits_enrichment_when_absent(dw_base_schema) -> None:
    """Without enrichment the judgment context carries only the schema."""
    backend = _FixedBackend(_response("unambiguous", []), record_prompts=True)
    detector = ReasoningBasedDetector(dw_base_schema, backend)
    detector.analyze(_task("How many active customers last quarter?"), _context())
    user_message = backend.prompts[0][-1].content
    assert "Enterprise metadata:" not in user_message
    assert "TABLE orders" in user_message


def test_system_prompt_prescribes_persistence_and_conservatism() -> None:
    """The instructions enforce the metadata-persistence and two-reading rule."""
    assert "metadata" in SYSTEM_PROMPT
    assert "conservative" in SYSTEM_PROMPT
    for code in ("S1", "S2", "R2", "C1", "C2", "C3", "T1", "K1", "I2", "I3"):
        assert code in SYSTEM_PROMPT


def test_budget_accounting(dw_schema) -> None:
    """One call and its tokens are charged to the run ledger."""
    backend = _FixedBackend(
        _response("ambiguous", [_span("C2", 0, 3)], 0.8),
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    detector = ReasoningBasedDetector(dw_schema, backend)
    context = _context()
    detector.analyze(_task("Top 5 products by revenue."), context)
    ledger = context.state[BUDGET_LEDGER_KEY]
    assert ledger.llm_calls == 1
    assert ledger.llm_tokens == 15


def test_no_ledger_raises(dw_schema) -> None:
    """Outside a pipeline there is no run ledger to charge (stage.py)."""
    backend = _FixedBackend(_response("unambiguous", []))
    detector = ReasoningBasedDetector(dw_schema, backend)
    context = RuntimeContext(session=SessionState(session_id="s1"))
    with pytest.raises(PipelineError):
        detector.analyze(_task("How many customers exist?"), context)


def test_missing_question_raises(dw_schema) -> None:
    """A payload without a question is rejected."""

    class _NoQuestion(Payload):
        pass

    task = TaskEnvelope(
        type_key="test.no_question",
        header=TaskHeader(task_id="t0", question="q"),
        payload=_NoQuestion(),
    )
    backend = _FixedBackend(_response("unambiguous", []))
    with pytest.raises(AmbiguityResolutionError):
        ReasoningBasedDetector(dw_schema, backend).analyze(task, _context())


def test_malformed_json_raises(dw_schema) -> None:
    """A non-JSON response is a failed judgment, not an unambiguous one."""
    detector = ReasoningBasedDetector(
        dw_schema, _FixedBackend("not json at all")
    )
    with pytest.raises(AmbiguityResolutionError):
        detector.analyze(_task("How many customers exist?"), _context())


def test_non_object_response_raises(dw_schema) -> None:
    """A JSON array is not a valid judgment."""
    detector = ReasoningBasedDetector(dw_schema, _FixedBackend("[1, 2, 3]"))
    with pytest.raises(AmbiguityResolutionError):
        detector.analyze(_task("How many customers exist?"), _context())


def test_unknown_verdict_raises(dw_schema) -> None:
    """An unlisted verdict is malformed."""
    detector = ReasoningBasedDetector(
        dw_schema, _FixedBackend('{"verdict": "maybe", "spans": []}')
    )
    with pytest.raises(AmbiguityResolutionError):
        detector.analyze(_task("How many customers exist?"), _context())


def test_ambiguous_without_spans_raises(dw_schema) -> None:
    """An ambiguous verdict must localize its evidence."""
    detector = ReasoningBasedDetector(
        dw_schema, _FixedBackend('{"verdict": "ambiguous", "spans": []}')
    )
    with pytest.raises(AmbiguityResolutionError):
        detector.analyze(_task("How many customers exist?"), _context())


def test_unambiguous_with_spans_raises(dw_schema) -> None:
    """An unambiguous verdict must carry no spans."""
    content = json.dumps(
        {
            "verdict": "unambiguous",
            "spans": [{"type": "T1", "start": 0, "end": 4}],
        }
    )
    detector = ReasoningBasedDetector(dw_schema, _FixedBackend(content))
    with pytest.raises(AmbiguityResolutionError):
        detector.analyze(_task("How many customers exist?"), _context())


def test_code_fence_is_stripped(dw_schema) -> None:
    """A markdown-fenced JSON response parses cleanly."""
    content = "```json\n" + _response("unambiguous", []) + "\n```"
    analysis = ReasoningBasedDetector(dw_schema, _FixedBackend(content)).analyze(
        _task("How many customers exist?"), _context()
    )
    assert analysis.verdict == AmbiguityVerdict.UNAMBIGUOUS


def test_deterministic_output(dw_schema) -> None:
    """The same backend and question always produce the same analysis."""
    question = "How many orders this week?"
    start = question.index("this week")
    backend = _FixedBackend(
        _response("ambiguous", [_span("T1", start, start + len("this week"))], 0.8)
    )
    detector = ReasoningBasedDetector(dw_schema, backend)
    first = detector.analyze(_task(question), _context())
    second = detector.analyze(_task(question), _context())
    assert first.model_dump() == second.model_dump()


def test_resolve_is_out_of_scope(dw_schema) -> None:
    """Resolution is not part of the detection slice."""
    backend = _FixedBackend(_response("unambiguous", []))
    detector = ReasoningBasedDetector(dw_schema, backend)
    with pytest.raises(NotImplementedError):
        detector.resolve(
            detector.analyze(_task("How many orders this week?"), _context()),
            _task("How many orders this week?"),
            _context(),
        )


def test_database_id_ties_analysis_to_schema(dw_schema) -> None:
    """The analysis records the schema it consulted."""
    backend = _FixedBackend(_response("unambiguous", []))
    analysis = ReasoningBasedDetector(dw_schema, backend).analyze(
        _task("How many customers exist?"), _context()
    )
    assert analysis.database_id == "dw"
