# ruff: noqa: E402
"""Paper 1 — NL2SQL Ambiguity Detection: Interactive Research Demo.

Launch with:
    streamlit run ui/app.py --server.port 8501

Or from the project root:
    python -m streamlit run ui/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

import streamlit as st

st.set_page_config(
    page_title="Paper 1 — NL2SQL Ambiguity Detection",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

from eaa.ambiguity_resolution.demo import (
    DEMO_VERSION,
    DemoAnalysis,
    analyze_demo,
)
from eaa.core.configuration import resolve_config
from eaa.core.registry import plugin_registry

CONFIG_PATH = str(_ROOT / "configs" / "experiments" / "phase1_beaver_eval.yaml")
EVAL_RUN_DIR = _ROOT / "experiments" / "runs" / "surface_b_human_gold_eval"

FAMILY_DISPLAY = {
    "S": {
        "name": "Structural",
        "icon": "\U0001f3d7",
        "desc": "Scope and attachment ambiguities",
    },
    "R": {
        "name": "Schema Reference",
        "icon": "\U0001f517",
        "desc": "Shared terms across tables",
    },
    "C": {
        "name": "Computational",
        "icon": "\u26a1",
        "desc": "Implicit comparisons and aggregation",
    },
    "T": {
        "name": "Temporal",
        "icon": "\U0001f550",
        "desc": "Calendar vs fiscal time references",
    },
    "K": {
        "name": "Knowledge",
        "icon": "\U0001f4da",
        "desc": "Business rules and domain knowledge",
    },
    "I": {
        "name": "Intent",
        "icon": "\U0001f3af",
        "desc": "User intent mismatch",
    },
    "V": {
        "name": "Semantic Value",
        "icon": "\U0001f3f7",
        "desc": "Value-literal and entity reference",
    },
    "L": {
        "name": "Lexical",
        "icon": "\U0001f4dd",
        "desc": "Word-level ambiguity",
    },
}

EXAMPLES = [
    (
        "List all courses with more than 5 students",
        "Quantifier scope — 'all' admits multiple readings",
    ),
    ("Show students with high grades", "Vague threshold — 'high' is subjective"),
    (
        "Find employees who joined recently",
        "Temporal ambiguity — 'recently' has no fixed window",
    ),
    (
        "Show departments with no students enrolled this year",
        "Negation scope + temporal reference",
    ),
]

EXAMPLE_QUESTIONS = [e[0] for e in EXAMPLES]


@st.cache_resource
def _load_schema():
    try:
        config = resolve_config(CONFIG_PATH)
        name = config.root.dataset.name
        factory = plugin_registry.discover().get(name)
        data_root = config.root.dataset.data_root
        if data_root:
            try:
                adapter = cast(Any, factory)(root=data_root)
            except TypeError:
                adapter = factory()
        else:
            adapter = factory()
        return cast(Any, adapter.schema_provider().get_schema("dw"))
    except Exception:
        return None


@st.cache_data
def _load_eval_metrics():
    baseline_path = EVAL_RUN_DIR / "metrics" / "baseline.json"
    run_path = EVAL_RUN_DIR / "run.json"
    if baseline_path.exists() and run_path.exists():
        return json.loads(baseline_path.read_text()), json.loads(run_path.read_text())
    return None, None


def _render_span_highlight(question: str, spans):
    if not spans:
        return question
    parts = []
    last_end = 0
    for span in sorted(spans, key=lambda s: s.start):
        if span.start > last_end:
            parts.append(question[last_end:span.start])
        parts.append(f"**:{span.code}:**{question[span.start:span.end]}**:**")
        last_end = span.end
    if last_end < len(question):
        parts.append(question[last_end:])
    return "".join(parts)


def _render_pipeline():
    stages = [
        ("Question", True, False),
        ("Ambiguity Detection", True, False),
        ("Clarification", True, False),
        ("NL2SQL", False, True),
        ("Visualization", False, True),
    ]
    cols = st.columns(len(stages) * 2 - 1)
    for i, (name, active, future) in enumerate(stages):
        col_idx = i * 2
        with cols[col_idx]:
            if future:
                st.markdown(
                    f'<div style="text-align:center;padding:8px 4px;border-radius:8px;'
                    f'background:rgba(128,128,128,0.1);border:1px dashed rgba(128,128,128,0.3);'
                    f'font-size:0.8rem;color:#888;">{name}<br><small>Next phase</small></div>',
                    unsafe_allow_html=True,
                )
            elif active:
                st.markdown(
                    f'<div style="text-align:center;padding:8px 4px;border-radius:8px;'
                    f'background:rgba(99,102,241,0.15);border:2px solid #6366f1;'
                    f'font-size:0.85rem;font-weight:600;color:#6366f1;">{name}</div>',
                    unsafe_allow_html=True,
                )
        if i < len(stages) - 1 and col_idx + 1 < len(cols):
            with cols[col_idx + 1]:
                arrow = "→" if not stages[i + 1][2] else "⋯"
                st.markdown(
                    f'<div style="text-align:center;padding:12px 0;font-size:1.2rem;'
                    f'color:{"#6366f1" if not stages[i+1][2] else "#ccc"};">{arrow}</div>',
                    unsafe_allow_html=True,
                )


def _render_status_badge(label: str, available: bool, detail: str = ""):
    color = "#22c55e" if available else "#ef4444" if "unavailable" in detail.lower() else "#f59e0b"
    dot = "●"
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0;">'
        f'<span style="color:{color};font-size:1rem;">{dot}</span>'
        f'<span style="font-size:0.85rem;"><strong>{label}</strong>'
        f'{" — " + detail if detail else ""}</span></div>',
        unsafe_allow_html=True,
    )


def main():
    """Render the Streamlit UI for Paper 1 ambiguity detection."""
    schema = _load_schema()
    schema_available = schema is not None

    with st.sidebar:
        st.markdown("### Paper 1 — NL2SQL Ambiguity Detection")
        st.markdown("---")
        page = st.radio(
            "Navigate",
            ["Demo", "Evaluation", "Architecture", "About"],
            label_visibility="collapsed",
        )
        st.markdown("---")
        st.markdown(
            f"<small style='color:#888;'>{DEMO_VERSION}<br>"
            "Human Gold: 45 questions<br>"
            "Frozen & verified</small>",
            unsafe_allow_html=True,
        )

    if page == "Demo":
        _render_demo_page(schema, schema_available)
    elif page == "Evaluation":
        _render_evaluation_page()
    elif page == "Architecture":
        _render_architecture_page()
    elif page == "About":
        _render_about_page()


def _render_demo_page(schema, schema_available):
    st.markdown(
        '<div style="text-align:center;padding:1rem 0 0.5rem 0;">'
        '<h1 style="margin:0;font-size:2rem;font-weight:700;letter-spacing:-0.5px;">'
        "Enterprise AI Analyst</h1>"
        '<p style="margin:0.3rem 0 0 0;font-size:1.05rem;color:#888;">'
        "Paper 1 &mdash; NL2SQL Ambiguity Detection</p>"
        '<p style="margin:0.5rem 0 0 0;font-size:0.9rem;color:#666;font-style:italic;">'
        "Detect ambiguity before it becomes a SQL error.</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown("")

    if not schema_available:
        st.info(
            "📋 **Dataset not loaded.** Live question analysis requires the BEAVER dataset. "
            "The Evaluation, Architecture, and About pages are fully functional."
        )

    col1, col2 = st.columns([3, 1])
    with col1:
        question = st.text_input(
            "Question",
            placeholder="Ask a data question...",
            label_visibility="collapsed",
            key="question_input",
        )
    with col2:
        st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
        analyze_clicked = st.button("Analyze Question", type="primary", use_container_width=True)

    with st.expander("Try an example", expanded=not question):
        for i, (q, _desc) in enumerate(EXAMPLES):
            if st.button(f"{q}", key=f"example_{i}", use_container_width=True):
                st.session_state.question_input = q
                st.rerun()

    if analyze_clicked and question:
        if not schema_available:
            st.error(
                "Live analysis requires the BEAVER dataset. "
                "Set the `EAA_BEAVER_DATA_ROOT` environment variable or "
                "download the dataset into `data/raw/beaver/`. "
                "See the project README for setup instructions."
            )
        else:
            with st.spinner("Analyzing question..."):
                result = analyze_demo(question, schema, mode="baseline")

            _render_result(result)
    elif analyze_clicked and not question:
        st.warning("Please enter a question to analyze.")

    st.markdown("---")
    st.markdown("#### Research Pipeline")
    _render_pipeline()

    st.markdown("---")
    st.markdown(
        "<small style='color:#888;'>Research demonstration only — not a benchmark evaluation. "
        "Demo output is computed by the frozen Paper 1 detectors.</small>",
        unsafe_allow_html=True,
    )


def _render_result(result: DemoAnalysis):
    is_ambiguous = result.ambiguous
    verdict_color = "#ef4444" if is_ambiguous else "#22c55e"
    verdict_text = (
        "AMBIGUITY DETECTED" if is_ambiguous else "NO AMBIGUITY DETECTED"
    )

    st.markdown("---")

    col1, col2 = st.columns([2, 1])

    with col1:
        bg_color = (
            "rgba(239,68,68,0.08)" if is_ambiguous
            else "rgba(34,197,94,0.08)"
        )
        border_color = (
            "rgba(239,68,68,0.2)" if is_ambiguous
            else "rgba(34,197,94,0.2)"
        )
        span_count = len(result.spans)
        st.markdown(
            f'<div style="padding:1rem;border-radius:12px;'
            f"background:{bg_color};border:1px solid {border_color};\">"
            f'<span style="font-size:1.3rem;font-weight:700;'
            f'color:{verdict_color};">{verdict_text}</span>'
            f'<br><span style="font-size:0.85rem;color:#666;">'
            f"Paper 1 detected <strong>{span_count}</strong>"
            f" potential ambiguity span(s).</span></div>",
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown("##### System Status")
        _render_status_badge("Deterministic detector", True, "Available")
        reasoning_ok = (
            "configured" in result.llm_backend_status
            and "unavailable" not in result.llm_backend_status
        )
        reasoning_detail = (
            "Unavailable" if "unavailable" in result.llm_backend_status
            else "Available"
        )
        _render_status_badge(
            "Reasoning detector", reasoning_ok, reasoning_detail
        )
        _render_status_badge(
            "Metadata detector", False, "Deferred (ADR-015)"
        )
        _render_status_badge("Human Gold", True, "Frozen")

    st.markdown("")

    if result.spans:
        st.markdown("#### Ambiguity Spans")

        highlighted = _render_span_highlight(
            result.question, result.spans
        )
        st.markdown(
            '<div style="padding:1rem;border-radius:8px;'
            'background:#f8f9fa;font-size:1.1rem;'
            f'line-height:1.8;font-family:monospace;">{highlighted}</div>',
            unsafe_allow_html=True,
        )

        for span in result.spans:
            fallback = {
                "name": span.family,
                "icon": "?",
                "desc": "",
            }
            family_info = FAMILY_DISPLAY.get(
                span.family, fallback
            )
            label = (
                f"{family_info['icon']} [{span.code}] "
                f"{family_info['name']} — \"{span.text}\""
            )
            with st.expander(label):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Code:** {span.code}")
                    st.markdown(
                        f"**Family:** {family_info['name']}"
                    )
                    st.markdown(f"**Text:** `{span.text}`")
                    st.markdown(
                        f"**Position:** {span.start}–{span.end}"
                    )
                with c2:
                    req = (
                        "Required" if span.clarification_required
                        else "Not required"
                    )
                    st.markdown(
                        f"**Clarification:** {req}"
                    )
                    st.markdown(
                        f"**Assumption risk:** "
                        f"{span.assumption_risk}"
                    )
                    st.markdown(f"**Source:** {span.source}")
                st.markdown(
                    f"**Explanation:** {span.explanation}"
                )
                conf = span.confidence
                st.markdown(
                    f"<small style='color:#888;'>"
                    f"Confidence: {conf:.2f} "
                    f"(uncalibrated heuristic score)</small>",
                    unsafe_allow_html=True,
                )

    if result.clarification_required:
        st.markdown("#### Clarification Recommended")
        st.info(
            "The detected ambiguity requires clarification before SQL generation. "
            "A downstream resolver should ask the user to disambiguate."
        )

    if result.signals:
        st.markdown("#### Screening Signals")
        hint_msg = (
            "<small style='color:#888;'>"
            "Signals are screening hints, not gold labels.</small>"
        )
        st.markdown(hint_msg, unsafe_allow_html=True)
        for sig in result.signals:
            families_str = ", ".join(sig.families)
            evidence_str = ", ".join(repr(e) for e in sig.evidence)
            with st.expander(f"{sig.id} — {sig.name}"):
                st.markdown(f"**Evidence:** {evidence_str}")
                st.markdown(f"**Potential families:** {families_str}")
                st.markdown(f"**Status:** {sig.note}")

    st.markdown("#### Interpretations")
    if result.interpretations:
        for interp in result.interpretations:
            st.markdown(f"- {interp}")
    else:
        st.markdown(
            "*SQL interpretations require reasoning analysis. "
            "The deterministic baseline authors no SQL readings.*"
        )

    if result.warnings:
        st.markdown("#### Warnings")
        for w in result.warnings:
            st.warning(w)


def _render_evaluation_page():
    st.markdown("# Evaluation Results")
    eval_note = (
        "<small style='color:#888;'>"
        "Verified results from the Paper 1 Human Gold evaluation."
        "</small>"
    )
    st.markdown(eval_note, unsafe_allow_html=True)

    metrics, run_data = _load_eval_metrics()
    if metrics is None:
        st.error("Evaluation artifacts not found.")
        return

    st.markdown("---")
    st.markdown("### Human Gold Evaluation")

    gold = run_data.get("gold", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("Questions", gold.get("num_questions", 45))
    c2.metric("Annotator", gold.get("annotator", "samar"))
    c3.metric("Status", "Frozen")

    strata = gold.get("strata", {})
    st.markdown("**Strata:**")
    for k, v in strata.items():
        st.markdown(f"- {k}: {v}")

    st.markdown("---")
    st.markdown("### Baseline Results (SignalAnnotator)")

    e = metrics.get("existence", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("Existence Accuracy", f"{e.get('accuracy', 0):.4f}")
    c2.metric("Macro F1", f"{e.get('macro_f1', 0):.4f}")
    counts = e.get("counts", {})
    tp = counts.get("tp", 0)
    fp = counts.get("fp", 0)
    fn = counts.get("fn", 0)
    tn = counts.get("tn", 0)
    c3.metric("TP/FP/FN/TN", f"{tp}/{fp}/{fn}/{tn}")

    st.markdown("**Ambiguous class:**")
    amb = e.get("ambiguous", {})
    st.markdown(f"- Precision: {amb.get('precision', 0):.4f}")
    st.markdown(f"- Recall: {amb.get('recall', 0):.4f}")
    st.markdown(f"- F1: {amb.get('f1', 0):.4f}")

    st.markdown("**Unambiguous class:**")
    una = e.get("unambiguous", {})
    st.markdown(f"- Precision: {una.get('precision', 0):.4f}")
    st.markdown(f"- Recall: {una.get('recall', 0):.4f}")
    st.markdown(f"- F1: {una.get('f1', 0):.4f}")

    st.markdown("---")
    st.markdown("### Span Metrics")
    span = metrics.get("span", {})
    for threshold_key, data in span.items():
        p = data.get("precision", 0)
        r = data.get("recall", 0)
        f1 = data.get("f1", 0)
        st.markdown(
            f"**{threshold_key}:** P={p:.4f}, R={r:.4f}, F1={f1:.4f}"
        )

    st.markdown("---")
    st.markdown("### Classification")
    cls = metrics.get("classification", {})
    localized = cls.get("localized_spans", 0)
    predicted = cls.get("predicted_spans", 0)
    st.markdown(f"- Localized spans: {localized}/{predicted}")
    st.markdown(f"- Type accuracy: {cls.get('type_accuracy', 0):.4f}")
    st.markdown(f"- Family accuracy: {cls.get('family_accuracy', 0):.4f}")

    st.markdown("---")
    st.markdown("### Band Confusion Matrix")
    bc = metrics.get("band_confusion", {})
    if bc:
        import pandas as pd
        matrix = bc.get("matrix", {})
        bands = bc.get("bands", [])
        df_data = []
        for gold_b in bands:
            row = [matrix.get(gold_b, {}).get(pred_b, 0) for pred_b in bands]
            df_data.append(row)
        df = pd.DataFrame(df_data, index=bands, columns=bands)
        st.dataframe(df, use_container_width=True)

    st.markdown("---")
    st.markdown("### Human Gold vs AI-GOLD Pilot")
    comp = run_data.get("human_gold_vs_ai_gold", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("Common questions", comp.get("common_questions", 0))
    c2.metric("Existence agreement", f"{comp.get('existence_agreement_rate', 0):.1%}")
    c3.metric("Span disagreements", comp.get("span_type_disagreements", 0))

    st.markdown("---")
    disclaimer = (
        "<small style='color:#888;'>"
        "These results reflect the current Paper 1 "
        "experimental configuration and should not be "
        "interpreted as definitive benchmark/SOTA claims."
        "</small>"
    )
    st.markdown(disclaimer, unsafe_allow_html=True)


def _render_architecture_page():
    st.markdown("# Architecture")
    st.markdown("---")

    st.markdown("### Detection Pipeline")
    _render_pipeline()

    st.markdown("---")
    st.markdown("### M1.5 Ambiguity Taxonomy")

    for code, info in FAMILY_DISPLAY.items():
        with st.expander(f"{info['icon']} **{code}** — {info['name']}"):
            st.markdown(info["desc"])
            family_codes = {
                "S": ["S1 — Quantifier-scope", "S2 — Attachment-ambiguity"],
                "R": ["R1 — Shared-term-across-tables", "R2 — Aggregation-order"],
                "C": ["C1 — Implicit-comparison", "C2 — Temporal-ambiguity", "C3 — Negation-scope"],
                "T": ["T1 — Chart-type-mismatch"],
                "K": ["K1 — Business-rule"],
                "I": ["I2 — Implicit-join"],
                "V": ["V1 — Value-literal"],
                "L": [],
            }
            for fc in family_codes.get(code, []):
                st.markdown(f"- {fc}")

    st.markdown("---")
    st.markdown("### Detector Architecture")

    detectors = [
        (
            "SignalAnnotator",
            "Deterministic",
            "Pattern-matching over question text using 16 signal detectors.",
            True,
        ),
        (
            "ReasoningBasedDetector",
            "LLM-based",
            "Sends question + schema to an LLM backend.",
            False,
        ),
        (
            "MetadataGroundedDetector",
            "Enrichment-based",
            "Uses enriched schema metadata (ADR-015).",
            False,
        ),
    ]
    for name, kind, det_desc, available in detectors:
        status = "Available" if available else "Not configured"
        color = "#22c55e" if available else "#f59e0b"
        card = (
            f'<div style="padding:1rem;margin:0.5rem 0;'
            f'border-radius:8px;'
            f'border:1px solid rgba(128,128,128,0.2);">'
            f'<span style="font-weight:600;">{name}</span> '
            f'<span style="color:#888;font-size:0.85rem;">'
            f'({kind})</span> '
            f'<span style="float:right;color:{color};'
            f'font-size:0.85rem;">\u25cf {status}</span>'
            f'<br><span style="font-size:0.85rem;color:#666;">'
            f'{det_desc}</span></div>'
        )
        st.markdown(card, unsafe_allow_html=True)


def _render_about_page():
    st.markdown("# About Paper 1")
    st.markdown("---")

    st.markdown(
        "### NL2SQL Ambiguity Detection\n\n"
        "**Purpose:** Detect ambiguity in natural-language questions before SQL generation.\n\n"
        "**Research problem:** Natural-language questions often contain ambiguity that leads to "
        "multiple valid SQL interpretations. Without detection and clarification, NL2SQL systems "
        "silently produce incorrect queries."
    )

    st.markdown("---")
    st.markdown("### Key Components")

    components = [
        ("M1.5 Taxonomy", "10 ambiguity types across 6 families"),
        ("SignalAnnotator", "Deterministic baseline detector"),
        ("ReasoningBasedDetector", "LLM-based detector (requires backend)"),
        ("MetadataGroundedDetector", "Enrichment-based detector (requires data)"),
        ("Human Gold", "45 annotated questions, frozen and SHA-256 verified"),
        ("Evaluation", "Existence, span, classification, and persistence metrics"),
    ]
    for name, desc in components:
        st.markdown(f"- **{name}:** {desc}")

    st.markdown("---")
    st.markdown("### Dataset")
    st.markdown(
        "This artifact uses the **BEAVER** benchmark (Chen et al., 2024, arXiv:2409.02038). "
        "The raw dataset is NOT included due to redistribution terms."
    )

    st.markdown("---")
    st.markdown("### Limitations")
    limitations = [
        "Single annotator; no inter-annotator agreement measured",
        "No real LLM backend configured; ReasoningBasedDetector not evaluated",
        "No enrichment data; MetadataGroundedDetector is N/A",
        "Span-level metrics not meaningful due to annotation granularity mismatch",
        "Evaluation on 45-question subset, not full BEAVER benchmark",
    ]
    for lim in limitations:
        st.markdown(f"- {lim}")

    st.markdown("---")
    st.markdown(
        "<small style='color:#888;'>Paper 1 research artifact — not a benchmark evaluation. "
        "Independent validation remains necessary for broader benchmark claims.</small>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
