# 15. M1.5 — Ambiguity Detector Evaluation Design (Research Design)

> Pre-registered evaluation methodology for the ambiguity detector (M1.5 slice
> 2.3). This is a **research evaluation design**, not an engineering
> specification: it fixes what "correct detection" means, which metrics are
> reported, and how results are broken down and compared — before any detector
> is implemented. No code, algorithms, or prompts are defined here.
>
> Related: docs/12 (main NL2SQL experiment — the detector is the mechanism
> behind the AR factor), docs/13 (annotation protocol — the gold labels),
> docs/14 (detector architecture — the artifact being evaluated), docs/11
> §6.2/§8/§13.1 (contracts, protocols, contribution), ADR-013 (self-labeled
> subset), ADR-014 (ambiguity contracts), ADR-015 (metadata enrichment),
> docs/07 (evaluation framework).

## 1. Evaluation Objective

### 1.1 What capability is being evaluated

The detector's ability to establish, for a question against a specific schema
and its enrichment (docs/14 §2, §3):

1. **whether** ambiguity exists (verdict: unambiguous / ambiguous /
   underdetermined / unanswerable),
2. **which** taxonomy class it is (L1–I3, canonical vocabulary in docs/13 §2),
3. **where** it is (span localization),
4. **whether it persists after metadata** (metadata-closable underspecification
   vs strict ambiguity),
5. **whether the question is answerable** (answerability signal, U1–U4).

This is a *diagnostic* capability: it evaluates the detector's claims about the
question–schema relationship, not the SQL it enables.

### 1.2 Why detecting ambiguity is different from solving NL2SQL

End-to-end NL2SQL success (execution accuracy, EX) depends on many downstream
factors — schema linking, generation, validation, resolution policy. Two
systems can produce identical EX with very different detection quality, and
identical detection quality can yield different EX depending on how resolution
and generation consume it. EX therefore cannot stand in for detection quality:
a detector may detect everything yet still lose EX to a weak resolver, or
detect nothing and win EX on an unambiguous test slice. Detection quality must
be measured on the detection output itself.

### 1.3 Why detection quality is measured separately from resolution quality

docs/14 §5 separates the two stages: detection is descriptive ("what ambiguity
exists?"), resolution is normative ("how should the system handle it?"). The
two answer different scientific questions and must be scored independently:

- **Detection metrics** answer *"Can we identify ambiguity?"* (this document).
- **Resolution metrics** answer *"Can we handle ambiguity correctly?"*
  (clarification behavior, assumption accuracy, answer-change rate — docs/12).
- **The NL2SQL experiment** answers *"Does handling it improve SQL
  generation?"* (EX — docs/12).

Mixing them conflates three mechanisms into one number, breaks the M1.11
per-module ablation, and makes the AR factor unattributable (docs/14 §5). The
evaluation boundary therefore mirrors the architectural boundary.

## 2. Evaluation Dataset

**Surface B** — the human-labeled ambiguity subset (docs/13 §8).

- **Source of questions.** (i) Questions sampled from Surface A (the benchmark
  task stream, unlabeled) and (ii) constructed enterprise-style questions where
  the benchmark under-supplies ambiguity, because the benchmark ships no
  ambiguity or answerability labels (ADR-013).
- **Annotation protocol dependency.** Every item is labeled per the annotation
  protocol (docs/13): span-level and multi-label, with a question-level
  answerability label. The defining criterion for strict ambiguity is two
  schema-consistent SQL interpretations with different result sets
  (docs/13 §4, Step 3); the metadata-resolvable/underspecification distinction
  follows docs/13 §4, Step 2.
- **Taxonomy labels as gold references.** Gold ambiguity types use the
  canonical taxonomy codes L1–I3 (+ U branch), per docs/13 §2.
- **Answerability labels.** Gold `answerable` / `unanswerable` plus the U class
  (U1 data absence, U2 false premise, U3 contradiction, U4 out-of-scope), per
  item.
- **Size.** Initial targets are 100 clear / 150 ambiguous / 50 unanswerable
  (total 300). These are targets, not commitments: the final sample size is
  determined by the **power analysis at label time** (docs/12 §7), which must
  also power the detection metrics here (per-family span precision/recall and
  the refusal-detection recall), not only the EX effect.
- **Splits and leakage.** 80/20 dev/test split per database (docs/12 §4);
  detectors are tuned on dev only. Labels are frozen before any AR ON run
  (docs/13 §7); the detector never sees gold SQL or gold labels at inference
  (docs/14 §2.2).

## 3. Gold Standard Definition

A prediction is a **correct detection** only when all of the following hold,
decided per span with an agreed matching rule.

### 3.1 Ambiguity existence (question level)

Predicted verdict (`ambiguous` / `underdetermined` counts as *ambiguous
detected*; `unambiguous` as *not detected*) is compared with the gold
question-level existence (does the item carry at least one strict-ambiguity
span?).

### 3.2 Taxonomy classification

A predicted span is *type-correct* if its predicted taxonomy code equals the
gold code of the span it matches. Type match is evaluated only on spans that
first satisfy the localization rule (§3.3) — a well-placed span with a wrong
type is a *wrong-type* error, not a localization error.

### 3.3 Span localization

A predicted span *matches* a gold span when they **overlap by character
intersection-over-union (IoU) ≥ 0.5**. This partial-overlap rule is the primary
localization criterion (it tolerates boundary imprecision); an exact-boundary
rule (start/end equal) is reported as a stricter secondary. Both are reported
so span quality is not a single, arbitrary threshold.

A predicted span is a **true positive** iff it matches a gold span
(localization) **and** its type equals the gold type (classification) **and**,
where the gold span is metadata-resolvable, the prediction also marks it
metadata-closable (persistence, §3.4).

### 3.4 Metadata persistence

For every matched span, the predicted persistence judgment is compared with the
gold: does the system correctly identify a **metadata-resolvable
underspecification** (gold `metadata_resolution: true`) versus a **strict
ambiguity** (gold `metadata_resolution: false`)? This is the gold-standard
expression of docs/14 §4 A/B split: a span the enrichment pins must not be
reported as persistent ambiguity.

### 3.5 Answerability (question level)

Predicted answerability signal (`answerable` / `unanswerable`) is compared with
the gold answerability label; when `unanswerable`, the predicted U class is
compared with the gold U class (U1–U4).

## 4. Metrics

All metrics are reported on the frozen Surface B **test** split (tuned on dev),
with bootstrap 95% CIs (≥1000 resamples, stratified by database — docs/07).

### 4.1 Detection existence

- **Precision / Recall / F1** over the question-level existence decision
  (ambiguous-detected vs not). Because the strata are imbalanced by design,
  accuracy alone is not reported as a headline; precision/recall and the
  corresponding macro-averaged measures are primary.

### 4.2 Type classification

- **Macro-F1 across the eight ambiguity families** (L, S, R, V, C, T, K, I)
  and macro-F1 across all codes — the headline classification metric, immune
  to family imbalance.
- **Per-family F1** (§5.2) for the diagnosis of which families are detectable.

### 4.3 Span detection

- **Span precision / recall / F1** under the primary IoU ≥ 0.5 + type-match
  rule, and under the exact-boundary rule.
- **IoU sweep:** F1 reported at several IoU thresholds (e.g., 0.5, 0.7, exact)
  so localization quality is not a single threshold artifact.

### 4.4 Confidence quality

- **Calibration:** reliability diagram and expected calibration error for the
  binary existence decision and the answerability signal.
- **AUROC** for the existence decision (ambiguous vs not) and for the
  answerability signal — discrimination independent of the operating point.

### 4.5 Metadata awareness

- **False ambiguity rate after metadata:** among gold metadata-resolvable
  underspecifications, the fraction still reported as persistent ambiguity.
  This must be low when metadata is available — it is the direct measure of the
  metadata-grounded family (docs/14 §4A).
- **Unnecessary clarification rate:** among gold underspecifications, the
  fraction for which the pipeline proposes clarification instead of closing the
  issue via metadata. This connects detection directly to docs/12 H2 (M×AR):
  metadata awareness is what makes metadata ON reduce the clarification burden.

### 4.6 Answerability detection (U1–U4)

- **Balanced accuracy** on the answerable/unanswerable decision (the strata are
  ~5:1 imbalanced, so balanced accuracy is the primary existence metric here).
- **Refusal detection metrics:** recall (of gold unanswerable items flagged
  unanswerable), precision (of flagged items that are truly unanswerable), and
  F1, plus per-U-class recall. These evaluate the detector's *signal*; the
  policy-level refusal correctness/AUROC (H3/E6) is reported in the main
  experiment (docs/12), not here — keeping detection and resolution evaluation
  separate.

## 5. Evaluation Breakdown

### 5.1 Overall performance

Headline existence, type, span, calibration, metadata-awareness, and
answerability metrics over the whole test split (§4).

### 5.2 By ambiguity family

Per-family span precision/recall/F1 for the eight families (Lexical,
Structural, Schema, Value, Computational, Temporal, Knowledge, Intent). This
answers *which ambiguity classes are detectable* and is the mechanism evidence
behind H1 (docs/12): an AR gain concentrated in detectable families is
attributable; a gain in undetectable families is suspect.

### 5.3 By resolution band

Metrics broken down by the three bands of the resolution model (docs/12 §5,
docs/14 §6):

| Band | Detector claim evaluated |
|---|---|
| Metadata-closable | correct persistence judgment (underspecification recognized) — the metadata-awareness metrics (§4.5) |
| Persistent ambiguity | span + type detection on strict ambiguities — existence/span/type metrics |
| Unanswerability | answerability signal and U-class recall — §4.6 |

Report the **band confusion matrix** (gold band × predicted band): 
metadata-closable ↔ persistent-ambiguity confusion is a persistence error,
persistent/unanswerable confusion is an answerability or band error. This matrix
is the compact summary of the three-band model's detectability.

## 6. Baselines

Three conceptual comparison conditions, from least to most capable:

| Baseline | Configuration | What the comparison proves |
|---|---|---|
| **1. No ambiguity detection** | The AR OFF pipeline (docs/12 A1/A2); detector never fires | The counterfactual. Establishes the *cost of not resolving* (E2) and anchors the trivial-predictor floor for existence metrics (always-unambiguous). Detection being toggleable is itself what makes the experiment possible |
| **2. Schema-only detection** | Question + schema, no enrichment (metadata OFF) | The marginal value of the *schema*: how much ambiguity is discoverable from the schema alone, and how much remains misclassified as persistent when metadata is withheld. Sets the M OFF condition of the factorial (docs/12 §3.1) |
| **3. Metadata-aware detector** | Question + schema + enriched metadata (metadata ON) | The full configuration and the thesis claim. The B2→B3 delta isolates *metadata awareness*: the reduction in false-ambiguity rate and the improvement in persistence judgment (H2) attributable to enrichment (ADR-015) |

An **upper-bound reference** (not a baseline): human performance, given by the
annotator agreement (κ ≥ 0.7 per family, docs/13 §7). Detector metrics are
interpreted against this ceiling — a detector approaching the family
agreement bound is effectively at the label-reliability limit. Together with
the oracle-clarification arm A5 of the main experiment (docs/12 §3.2), this
bounds what detection quality can contribute.

## 7. Error Analysis Framework

Every false decision is assigned to exactly one category:

| Error category | Definition | Downstream consequence (docs/12) |
|---|---|---|
| **False positive** | Detector reports ambiguity (a span or an existence verdict) that is not present | Unnecessary clarification — inflates user burden and answer-change rate; dilutes the AR benefit |
| **False negative** | Detector misses a gold ambiguity | Unresolved ambiguity propagates into generation — the EX loss the experiment measures (H1a) |
| **Wrong type** | Span localized correctly but the taxonomy class is wrong | Wrong channel/policy downstream (e.g., an assumption where clarification was needed); distorts per-family attribution |
| **Wrong persistence judgment** | Fails to distinguish metadata-resolvable underspecification from strict ambiguity | Misattributes the M and AR factors (H2); forces clarification the metadata could have closed |
| **Wrong answerability judgment** | Misclassifies answerable/unanswerable, or assigns the wrong U class | Refusal failures — the harm rate of H3/E6 (docs/12 §6) |

Reporting:

- Per-family and per-band error counts (extending §5).
- Confusion matrices: type codes, resolution bands, U classes.
- A manual-review pass on a sampled subset of each category to characterize
  error causes at the guideline level (e.g., span-boundary imprecision vs
  semantic misreading vs missing metadata) — for the methodology chapter, not
  as an automated detector behavior.

## 8. Relation to the Main NL2SQL Experiment

The two evaluations are **kept separate but designed to compose**
(docs/12):

| Question | Answered by | Artifact scored |
|---|---|---|
| *Can we identify ambiguity?* | This document (detector evaluation) | the `AmbiguityAnalysis` artifact |
| *Can we handle it?* | docs/12 resolution DVs (clarification, assumptions) | the resolution output |
| *Does resolving it improve SQL generation?* | docs/12 (EX, McNemar over arms A1–A4) | the prediction |

Separation rules:

- **Different DVs and different referents.** Detection metrics are per-span and
  per-question diagnostic; the NL2SQL experiment is per-task EX. Neither is
  derivable from the other.
- **Shared, frozen test items.** Both evaluations run on the same Surface B
  dev/test splits (docs/12 §4), so detection quality and EX can be reported on
  identical tasks — but detection never consumes the labels at inference.
- **The bridge arm.** Arm A5 of the factorial (oracle clarification, docs/12
  §3.2) feeds the gold analysis into resolution; arm A3 feeds the detector's
  analysis. The A5→A3 gap is therefore attributable to **detection error
  alone** (resolution/generation are identical), connecting the two evaluations
  without merging them.
- **Sequence.** Detector evaluation is reported first (diagnosis), the EX
  experiment second (treatment effect); a strong EX gain in the absence of
  detection signal is treated as unresolved mechanism evidence, not as
  resolution success.

## 9. Research Contribution

**Thesis claim.** This evaluation design is a contribution because it is
**schema-aware, metadata-aware, taxonomy-grounded, enterprise-focused, and
separates detection, resolution, and generation evaluation** — it defines not
just a detector but a reusable *evaluation architecture* for enterprise
ambiguity in text-to-SQL.

Where prior work scores end-to-end accuracy and, at best, a generic
classification on free text, this design makes the schema and the enterprise
metadata part of the measurement: the gold standard (docs/13) and the metrics
here test whether a system can tell *resolvable underspecification from
persistent ambiguity* and *ambiguity from unanswerability*, with span-level
localization and family/band-level breakdowns. The three-condition baseline
ladder (none → schema-only → metadata-aware) turns the metadata factor into a
measurable scientific variable rather than an implementation detail, and the
separation of detection, resolution, and generation evaluation — with the
oracle arm as the bridge — lets the research attribute an NL2SQL gain to the
module that produced it. The result is a methodology that any enterprise
text-to-SQL system can be scored against: *when is enterprise ambiguity
detectable, when does metadata close it, and does closing it change what the
system answers.*
