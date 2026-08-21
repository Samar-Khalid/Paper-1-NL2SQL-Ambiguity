"""Tests for the Surface B candidate-selection signals (docs/19 §5.1)."""
import pytest

from eaa.ambiguity_resolution.candidates.signals import (
    SIGNALS,
    SIGNALS_BY_ID,
    SignalScorer,
    evaluate_question,
)

pytestmark = pytest.mark.unit

#: Positive examples: question -> signal ids that must fire.
POSITIVE_CASES: list[tuple[str, set[str]]] = [
    ("Show every department and every building.", {"s1"}),
    ("List customers who have never returned a product and never complained.", {"s1", "c3"}),
    ("Orders for customers in Germany by sales manager.", {"s2"}),
    ("What is the total amount of revenue?", {"c1"}),
    ("List the top 5 products by revenue.", {"c2", "v3", "v1"}),
    ("Show customers with no returns and no complaints.", {"c3", "s1"}),
    ("How many orders were placed this quarter?", {"c1", "t1", "t2"}),
    ("How many orders shipped in fiscal year Q1?", {"c1", "t2"}),
    ("List buildings built before 1950.", {"v1"}),
    ("What was revenue in millions?", {"v2"}),
    ("Revenue by region.", {"v3"}),
    ("The CFO wants the EBITDA margin.", {"k1"}),
    ("How many active customers do we have?", {"k2", "c1"}),
    ("Export the top customers to a CSV file.", {"i2", "c2"}),
    ("Show a pie chart of revenue by region.", {"i3", "v3"}),
]


def test_positive_cases_fire(warehouse_schema) -> None:
    """Every documented positive example fires at least its expected signals."""
    for question, expected in POSITIVE_CASES:
        hits = evaluate_question(question, warehouse_schema)
        fired = {hit.signal for hit in hits}
        assert expected <= fired, f"{question!r}: expected {expected}, fired {fired}"


def test_schema_grounded_shared_term(warehouse_schema) -> None:
    """R1 fires when a term names a column present in two or more tables."""
    hits = evaluate_question("Show all status values.", warehouse_schema)
    r1 = [h for h in hits if h.signal == "r1"]
    assert len(r1) == 1
    assert any("customers" in e and "orders" in e for e in r1[0].evidence)


def test_schema_grounded_multi_entity(warehouse_schema) -> None:
    """R2 fires when the question references entities from two or more tables."""
    hits = evaluate_question("Compare orders and customers.", warehouse_schema)
    r2 = [h for h in hits if h.signal == "r2"]
    assert len(r2) == 1
    assert set(r2[0].evidence) == {"customers", "orders"}


def test_schema_grounded_signals_absent_without_schema() -> None:
    """Without a schema only textual signals can fire; R1/R2 stay silent."""
    hits = evaluate_question("Show all status values.", None)
    fired = {hit.signal for hit in hits}
    assert "r1" not in fired and "r2" not in fired
    assert "s1" in fired  # 'all' is a textual quantifier trigger


def test_clean_question_yields_no_signals() -> None:
    """A plain question with no trigger fires no signal."""
    hits = evaluate_question("What is the campus address?", None)
    assert hits == ()


def test_evaluation_is_deterministic(warehouse_schema) -> None:
    """The same question and schema always produce the same signals."""
    question = "List the top 5 products by revenue and their status."
    first = evaluate_question(question, warehouse_schema)
    second = evaluate_question(question, warehouse_schema)
    assert first == second


def test_evidence_is_sorted_and_nonempty(warehouse_schema) -> None:
    """Every fired signal carries non-empty, sorted, unique evidence."""
    hits = evaluate_question("List the top 5 products by revenue.", warehouse_schema)
    assert hits
    for hit in hits:
        assert hit.evidence
        assert list(hit.evidence) == sorted(hit.evidence)
        assert len(set(hit.evidence)) == len(hit.evidence)


def test_scorer_is_reusable_per_schema(warehouse_schema) -> None:
    """A SignalScorer built once per schema yields identical results per call."""
    scorer = SignalScorer(warehouse_schema)
    question = "Show all status values."
    assert scorer.score(question) == scorer.score(question)


def test_signal_catalog_is_well_formed() -> None:
    """The catalog has unique ids and complete descriptions; ids map back."""
    assert len({signal.id for signal in SIGNALS}) == len(SIGNALS)
    assert set(SIGNALS_BY_ID) == {signal.id for signal in SIGNALS}
    for signal in SIGNALS:
        assert signal.id and signal.name and signal.description
        assert signal.families
        assert callable(signal.match)


def test_signal_families_are_hints_not_labels(warehouse_schema) -> None:
    """A fired signal must not be conflated with an ambiguity label."""
    hits = evaluate_question("Revenue by region.", warehouse_schema)
    for hit in hits:
        signal = SIGNALS_BY_ID[hit.signal]
        assert isinstance(signal.families, tuple)
        assert signal.families  # a hint about the family it may touch
