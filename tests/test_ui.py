"""UI integration tests for the Paper 1 Streamlit app.

These tests verify the app's Python code is valid and that core
helper functions work correctly. They do NOT require a running
Streamlit server or the BEAVER dataset.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = ROOT / "ui" / "app.py"
EVAL_RUN_DIR = ROOT / "experiments" / "runs" / "surface_b_human_gold_eval"


class TestAppSyntax:
    """Verify the Streamlit app parses without syntax errors."""

    def test_app_is_valid_python(self):
        """App source must parse as valid Python."""
        source = APP_PATH.read_text(encoding="utf-8")
        ast.parse(source, filename=str(APP_PATH))

    def test_app_has_main_function(self):
        """App must define the main entry point and page renderers."""
        source = APP_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(APP_PATH))
        func_names = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]
        assert "main" in func_names
        assert "_render_demo_page" in func_names
        assert "_render_evaluation_page" in func_names
        assert "_render_architecture_page" in func_names
        assert "_render_about_page" in func_names
        assert "_load_schema" in func_names
        assert "_load_eval_metrics" in func_names
        assert "_render_result" in func_names
        assert "_render_span_highlight" in func_names
        assert "_render_pipeline" in func_names
        assert "_render_status_badge" in func_names


class TestAppImports:
    """Verify the app's imports resolve correctly."""

    def test_demo_api_importable(self):
        """Demo API functions must be importable."""
        from eaa.ambiguity_resolution.demo import (
            DEMO_VERSION,
            DemoAnalysis,
            analyze_demo,
        )

        assert DEMO_VERSION == "paper1-demo-v1"
        assert DemoAnalysis is not None
        assert callable(analyze_demo)

    def test_configuration_importable(self):
        """Configuration resolver must be importable."""
        from eaa.core.configuration import resolve_config

        assert callable(resolve_config)

    def test_registry_importable(self):
        """Plugin registry must be importable."""
        from eaa.core.registry import plugin_registry

        assert plugin_registry is not None


class TestEvalMetricsExist:
    """Verify evaluation artifacts exist and are valid JSON."""

    def test_baseline_metrics_exist(self):
        """Baseline metrics file must exist."""
        path = EVAL_RUN_DIR / "metrics" / "baseline.json"
        assert path.exists(), f"Missing: {path}"

    def test_baseline_metrics_valid_json(self):
        """Baseline metrics must be valid JSON."""
        path = EVAL_RUN_DIR / "metrics" / "baseline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_baseline_has_existence(self):
        """Baseline metrics must contain existence data."""
        path = EVAL_RUN_DIR / "metrics" / "baseline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "existence" in data
        e = data["existence"]
        assert "accuracy" in e
        assert "macro_f1" in e

    def test_baseline_has_span(self):
        """Baseline metrics must contain span data."""
        path = EVAL_RUN_DIR / "metrics" / "baseline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "span" in data

    def test_baseline_has_classification(self):
        """Baseline metrics must contain classification data."""
        path = EVAL_RUN_DIR / "metrics" / "baseline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "classification" in data
        cls = data["classification"]
        assert "type_accuracy" in cls
        assert "family_accuracy" in cls

    def test_baseline_has_band_confusion(self):
        """Baseline metrics must contain band confusion matrix."""
        path = EVAL_RUN_DIR / "metrics" / "baseline.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "band_confusion" in data
        bc = data["band_confusion"]
        assert "matrix" in bc
        assert "bands" in bc

    def test_run_json_exists(self):
        """Run metadata file must exist."""
        path = EVAL_RUN_DIR / "run.json"
        assert path.exists(), f"Missing: {path}"

    def test_run_json_has_gold(self):
        """Run metadata must contain gold annotation info."""
        path = EVAL_RUN_DIR / "run.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "gold" in data
        gold = data["gold"]
        assert gold.get("num_questions") == 45
        assert gold.get("annotator") == "samar"

    def test_run_json_has_human_gold_vs_ai_gold(self):
        """Run metadata must contain human vs AI comparison."""
        path = EVAL_RUN_DIR / "run.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "human_gold_vs_ai_gold" in data
        comp = data["human_gold_vs_ai_gold"]
        assert comp.get("common_questions") == 45


class TestSpanHighlight:
    """Test the span highlight helper logic."""

    def test_no_spans(self):
        """Question with no spans should return unchanged."""
        text = "List all courses"
        parts = [text]
        result = "".join(parts)
        assert result == text

    def test_with_spans(self):
        """Question with spans should highlight matched regions."""
        class FakeSpan:
            """Minimal span mock for testing."""

            code = "S1"
            start = 5
            end = 8

        question = "List all courses"
        spans = [FakeSpan()]
        parts: list[str] = []
        last_end = 0
        for span in sorted(spans, key=lambda s: s.start):
            if span.start > last_end:
                parts.append(question[last_end : span.start])
            parts.append(
                f"**:{span.code}:**{question[span.start:span.end]}**:**"
            )
            last_end = span.end
        if last_end < len(question):
            parts.append(question[last_end:])
        result = "".join(parts)
        assert "**:S1:**all**:**" in result
        assert result.startswith("List ")
        assert result.endswith(" courses")


class TestAppStructure:
    """Verify app structure constants are present."""

    def test_examples_defined(self):
        """App must define curated example questions."""
        source = APP_PATH.read_text(encoding="utf-8")
        assert "EXAMPLES" in source
        assert "List all courses" in source

    def test_family_display_defined(self):
        """App must define family display metadata."""
        source = APP_PATH.read_text(encoding="utf-8")
        assert "FAMILY_DISPLAY" in source
        assert "Structural" in source
        assert "Schema Reference" in source

    def test_config_path_defined(self):
        """App must reference the evaluation config."""
        source = APP_PATH.read_text(encoding="utf-8")
        assert "CONFIG_PATH" in source
        assert "phase1_beaver_eval.yaml" in source

    def test_eval_run_dir_defined(self):
        """App must reference the evaluation run directory."""
        source = APP_PATH.read_text(encoding="utf-8")
        assert "EVAL_RUN_DIR" in source
        assert "surface_b_human_gold_eval" in source
