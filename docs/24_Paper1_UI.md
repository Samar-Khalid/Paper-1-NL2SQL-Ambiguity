# 24. Paper 1 Streamlit UI

**Status:** Active
**Purpose:** Interactive web interface for Paper 1 ambiguity detection demo

## Overview

The Streamlit UI provides a professional, multi-page interface for demonstrating
Paper 1's NL2SQL ambiguity detection research artifact. It is a research
demonstration tool — not a benchmark evaluation.

## Pages

### Demo

Main analysis page. Users enter a natural-language question, and the frozen
Paper 1 detectors analyze it for ambiguity. Results include:

- Verdict (ambiguous / unambiguous)
- Detected spans with M1.5 taxonomy codes
- Screening signals fired
- System status (which detectors are active)
- Clarification recommendation

Requires the BEAVER dataset (`data/raw/beaver/`). If the dataset is not
available, the page shows an informational message and the other pages
remain fully functional.

### Evaluation

Displays verified results from the Paper 1 Human Gold evaluation:

- Existence accuracy (0.5778), macro F1 (0.4099)
- TP/FP/FN/TN counts
- Per-class precision/recall/F1
- Span metrics at multiple IoU thresholds
- Classification accuracy (type, family)
- Band confusion matrix
- Human Gold vs AI-GOLD pilot agreement

Data source: `experiments/runs/surface_b_human_gold_eval/metrics/baseline.json`

### Architecture

Visual overview of:

- Detection pipeline (Question → Detection → Clarification → NL2SQL → Visualization)
- M1.5 taxonomy (24 codes: 8 ambiguity families + unanswerability branch)
- Detector architecture and status

### About

Project description, key components, dataset information, and limitations.

## Running

From the standalone repo root:

```bash
streamlit run ui/app.py --server.port 8501
```

Or:

```bash
python -m streamlit run ui/app.py
```

## Technical Details

- **Entry point:** `ui/app.py`
- **Framework:** Streamlit (installed in thesis venv)
- **Data loading:** `_load_schema()` wraps `analyze_demo()` API; gracefully
  handles missing BEAVER data
- **Evaluation data:** Loaded from JSON artifacts in `experiments/runs/`
- **No research logic:** The UI does not modify detection algorithms or
  evaluation methodology

## Design Principles

1. **Fidelity first:** All demo output comes from the frozen Paper 1 detectors
2. **No fabrication:** No fake LLM reasoning, SQL, or confidence scores
3. **Graceful degradation:** Works without raw data (taxonomy + eval pages)
4. **Professional presentation:** Clean layout, clear status indicators,
   structured output

## Integration with Existing Code

The UI imports from:

- `eaa.ambiguity_resolution.demo`: `analyze_demo()`, `DemoAnalysis`,
  `DemoSpan`, `DemoSignal`, `DEMO_VERSION`
- `eaa.core.configuration`: `resolve_config()`
- `eaa.core.registry`: `plugin_registry`

No modifications to the detection pipeline or evaluation code.
