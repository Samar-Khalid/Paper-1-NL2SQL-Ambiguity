# Paper 1: NL2SQL Ambiguity Detection

A standalone research artifact for detecting and classifying ambiguity in natural-language-to-SQL (NL2SQL) questions.

## What This Studies

Natural-language questions are often ambiguous when translated to SQL. A question like *"List all courses with more than 5 students"* could mean:

- **Reading A:** Courses where enrollment > 5
- **Reading B:** All courses, then filter students with > 5

Without clarification, an NL2SQL system must guess — and wrong guesses produce silently incorrect SQL. This Paper 1 artifact introduces:

- A **M1.5 ambiguity taxonomy** with 24 codes across eight ambiguity families (Lexical, Structural, Schema reference, Semantic value, Computational, Temporal, Knowledge, Intent) plus a separate unanswerability branch (nine family letters in total)
- Three **detector architectures**: deterministic SignalAnnotator, LLM-based ReasoningBasedDetector, and metadata-grounded MetadataGroundedDetector
- A **Human Gold evaluation set** of 45 annotated questions
- A **deterministic baseline** with reproducible evaluation

## Quick Start

### Install

```bash
git clone https://github.com/Samar-Khalid/Paper-1-NL2SQL-Ambiguity.git
cd Paper-1-NL2SQL-Ambiguity

python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/Mac

pip install -e ".[dev]"
```

### Run the Demo

```bash
python -m eaa.experiments.ambiguity_demo \
  --config configs/experiments/phase1_beaver_eval.yaml
```

Example session:

```
question> List all courses with more than 5 students

VERDICT: AMBIGUOUS
SPANS: [S1] "all" — quantifier-scope ambiguity
RECOMMENDATION: clarification required before SQL generation
```

### Run Tests

```bash
make test        # or: pytest tests/
make lint        # or: ruff check src/
make typecheck   # or: mypy src/
```

## Architecture

```
Paper 1: NL2SQL Ambiguity Detection
│
├── M1.5 Taxonomy (24 codes: 8 ambiguity families + unanswerability branch)
│   ├── L: L1 over-generality, L2 synonym collision (Lexical)
│   ├── S: S1 quantifier scope, S2 attachment (Structural)
│   ├── R: R1 table selection, R2 join path (Schema reference)
│   ├── V: V1 value/entity literal, V2 unit/scale/currency, V3 granularity (Semantic value)
│   ├── C: C1 aggregation/metric, C2 top-N/ranking, C3 existence/negation, C4 constraint boundary (Computational)
│   ├── T: T1 relative temporal, T2 calendar/fiscal (Temporal)
│   ├── K: K1 external knowledge, K2 business rule (Knowledge)
│   ├── I: I1 answer shape, I2 channel/encoding, I3 chart type (Intent)
│   └── U: U1 data absence, U2 false premise, U3 contradiction, U4 out of scope (Unanswerability)
│
├── Detectors
│   ├── SignalAnnotator (deterministic baseline)
│   ├── ReasoningBasedDetector (LLM-based, requires backend)
│   └── MetadataGroundedDetector (requires enrichment data)
│
├── Annotations
│   ├── Human Gold (45 questions, frozen, SHA-256 verified)
│   └── AI-Gold Pilot (60 questions, engineering reference)
│
└── Evaluation
    ├── Existence metrics (P/R/F1)
    ├── Span IoU metrics (0.5 / 0.7 / 1.0)
    ├── Classification accuracy
    ├── Per-family metrics
    ├── Band confusion matrix
    └── Persistence accuracy
```

## Human Gold Evaluation Set

| Property | Value |
|----------|-------|
| Questions | 45 |
| Persistent ambiguity | 25 |
| Unambiguous | 18 |
| Unanswerable | 2 |
| Total spans | 26 |
| Annotator | samar |
| Frozen | Yes |
| SHA-256 | `1df1ee495b67f2430da995a1ab8ea1c5a693c2b1c32e2737ad9a6e55fee210a4` |

The SHA-256 is the freeze digest recorded in `human-gold.v1.lock`
(`sha256(concat(relpath + \0 + file_bytes) sorted by relpath)` over the 45 annotation files plus
`provenance-v1.json`; `tasks.json` is excluded from the freeze). It is reproducible from the
current bytes with the repository's own `eaa.ambiguity_resolution.annotations.qc._freeze_digest`.

## Baseline Results

Results of the deterministic SignalAnnotator against Human Gold:

| Metric | Value |
|--------|-------|
| Existence accuracy | 0.5778 |
| Existence macro F1 | 0.4099 |
| Ambiguous P/R/F1 | 0.57/1.00/0.72 |
| Unambiguous P/R/F1 | 1.00/0.05/0.10 |
| Span IoU>=0.5 F1 | 0.0000 |
| Type accuracy | 0.0000 |

**Interpretation:** The baseline is conservative (high recall on ambiguous questions, FP-heavy on unambiguous). Span-level metrics are zero due to a granularity mismatch: the SignalAnnotator produces single-token evidence spans while Human Gold uses multi-word phrases, resulting in IoU below the 0.5 threshold.

## Dataset Access

This artifact uses the **BEAVER** benchmark (Chen et al., 2024, arXiv:2409.02038). The raw dataset is NOT included due to redistribution terms. To reproduce:

1. Obtain BEAVER from the authors or official release
2. Place data in `data/raw/beaver/` with `manifest.json`
3. See `src/eaa/datasets/adapters/beaver/README.md` for structure

The annotation artifacts and evaluation results ARE included and sufficient for Paper 1 analysis.

## Limitations

- **Single annotator:** Human Gold was annotated by one person; inter-annotator agreement not measured
- **No enrichment:** MetadataGroundedDetector is N/A without legitimate enrichment data
- **No real LLM:** ReasoningBasedDetector requires a configured LLM backend; not included
- **Span granularity:** Baseline span metrics are not comparable to gold due to different annotation granularity
- **BEAVER access:** Raw dataset must be obtained separately

## Relationship to Master Thesis

This is **Paper 1** of a larger Master Thesis:

```
Master Thesis
├── Paper 1: NL2SQL Ambiguity Detection  ← THIS ARTIFACT
└── Visualization Phase (future)
    └── Builds on Paper 1's ambiguity-resolution output contract
```

The Visualization phase will consume Paper 1's output without modifying this frozen research artifact.

## Citation

```bibtex
@software{samar2026paper1,
  author = {Samar, Eng},
  title = {Paper 1: NL2SQL Ambiguity Detection},
  year = {2026},
  version = {1.0.0},
  license = {Apache-2.0}
}
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
