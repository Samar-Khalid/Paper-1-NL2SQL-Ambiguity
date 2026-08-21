# Paper 1: Detecting and Classifying Ambiguity in NL2SQL Questions

## Title

**Detecting and Classifying Ambiguity in Natural-Language-to-SQL Questions: A Taxonomy and Baseline Evaluation**

## Abstract

Natural-language questions often contain ambiguity that leads to multiple valid SQL interpretations. Without detection and clarification, NL2SQL systems silently produce incorrect queries. This paper introduces M1.5, a taxonomy of 10 ambiguity types across 6 families, a deterministic baseline detector (SignalAnnotator), and a Human Gold evaluation set of 45 annotated questions from the BEAVER benchmark. We evaluate the baseline on existence detection, span localization, type classification, and persistence prediction. Results show that the deterministic baseline achieves reasonable existence detection (macro F1 = 0.41) but fails at span-level localization (F1 = 0.00) due to granularity differences between token-level evidence and human-annotated phrases. We release all artifacts for reproducibility.

## Research Questions

**RQ1:** What types of ambiguity commonly occur in enterprise NL2SQL questions?

**RQ2:** Can a deterministic signal-based detector identify ambiguous questions and their ambiguity types?

**RQ3:** How well do human annotations align with automated detection?

## Methodology

### Taxonomy (M1.5)

The M1.5 taxonomy classifies NL2SQL ambiguity into 10 types across 6 families:

| Family | Code | Name | Description |
|--------|------|------|-------------|
| S (Structural) | S1 | Quantifier-scope | Words like "all", "every", "each" have multiple scopes |
| S (Structural) | S2 | Attachment-ambiguity | Prepositional phrases attach to wrong clause |
| R (Reasoning) | R1 | Shared-term-across-tables | Same term refers to different entities across tables |
| R (Reasoning) | R2 | Aggregation-order | Unclear whether to aggregate before/after filtering |
| C (Conditional) | C1 | Implicit-comparison | Missing comparison operator or threshold |
| C (Conditional) | C2 | Temporal-ambiguity | Unclear time reference (fiscal vs calendar) |
| C (Conditional) | C3 | Negation-scope | "Not" applies to unexpected scope |
| T (Type) | T1 | Chart-type-mismatch | Visualization intent conflicts with data type |
| I (Referential) | I2 | Implicit-join | Join path ambiguous between tables |
| K (Knowledge) | K1 | Business-rule | Domain-specific rule not stated in question |

### Detectors

1. **SignalAnnotator** (deterministic): Pattern-matching over question text using 16 signal detectors. Produces single-token evidence spans. No LLM required.

2. **ReasoningBasedDetector** (LLM-based): Sends question + schema to an LLM backend. Produces multi-word ambiguity spans. Requires a configured LLM provider.

3. **MetadataGroundedDetector** (enrichment-based): Uses enriched schema metadata to detect metadata-resolvable ambiguities. Requires enrichment data (ADR-015).

### Dataset

- **BEAVER** benchmark (Chen et al., 2024): Enterprise NL2SQL with DW schema
- **Human Gold:** 45 questions annotated by one human annotator (samar)
  - 25 persistent ambiguity (30 originally, 25 in usable set)
  - 18 unambiguous
  - 2 unanswerable

### Annotation Process

1. Candidate questions screened from BEAVER DW dev set
2. Human annotator reviewed each question against the M1.5 taxonomy
3. For ambiguous questions: identified ambiguity type, span, persistence, and interpretation
4. For unambiguous questions: confirmed no ambiguity exists
5. Annotations frozen with SHA-256 hash verification

### Evaluation Metrics (docs/15)

- **Existence:** P/R/F1 for ambiguous vs unambiguous classification
- **Span localization:** IoU >= 0.5, 0.7, 1.0 thresholds
- **Type accuracy:** Correct ambiguity type among localized spans
- **Family accuracy:** Correct family among localized spans
- **Per-family P/R/F1:** Per-family existence and span metrics
- **Band confusion matrix:** Gold vs predicted band cross-tabulation
- **Persistence accuracy:** Correct metadata_closable vs persistent prediction

## Results

### SignalAnnotator Baseline vs Human Gold

| Metric | Value |
|--------|-------|
| Existence accuracy | 0.5778 |
| Existence macro F1 | 0.4099 |
| Ambiguous P / R / F1 | 0.57 / 1.00 / 0.72 |
| Unambiguous P / R / F1 | 1.00 / 0.05 / 0.10 |
| TP / FP / FN / TN | 25 / 19 / 0 / 1 |
| Span IoU>=0.5 F1 | 0.0000 |
| Type accuracy | 0.0000 |
| Family accuracy | 0.0000 |

### Key Observations

1. **Conservative baseline:** The SignalAnnotator flags nearly all questions as ambiguous (recall = 1.0 for ambiguous), but has many false positives (19 FP on 18 unambiguous questions).

2. **Granularity mismatch:** The baseline produces single-token evidence spans (e.g., "all") while Human Gold uses multi-word phrases (e.g., "all such courses"). IoU between these is always below 0.5, yielding zero span-level TP.

3. **Human Gold vs AI-GOLD pilot:** Only 53.3% existence agreement (24/45). The AI pilot over-detected ambiguity compared to the human annotator.

## Limitations

1. Single annotator; no inter-annotator agreement measured
2. No real LLM backend configured; ReasoningBasedDetector not evaluated
3. No enrichment data; MetadataGroundedDetector is N/A
4. Span-level metrics are not meaningful due to annotation granularity mismatch
5. BEAVER raw data not redistributed; reproduction requires separate data access
6. Evaluation is on a 45-question subset, not the full BEAVER benchmark

## Reproducibility

See [README.md](README.md) for full reproduction instructions.

Frozen artifacts:
- Human Gold SHA-256: `1df1ee495b67f2430da995a1ab8ea1c5a693c2b1c32e2737ad9a6e55fee210a4`
- AI Pilot SHA-256: `e215880a439656dfce29d0d9e4f466193fb78f60bf3b894aef9734bc0d469db7`

## Future Work

- Inter-annotator agreement study with multiple annotators
- LLM-based detector evaluation with real backend
- Span-level annotation with token-aligned boundaries
- Broader evaluation on full BEAVER benchmark
- Integration with downstream NL2SQL pipeline for end-to-end clarification
