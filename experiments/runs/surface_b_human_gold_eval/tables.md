# Surface B Human-Gold Evaluation (Paper 1, Final)

questions: 45  gold: human (annotator=samar, sha256=1df1ee495b67f243...)
strata: persistent_ambiguity=25, unambiguous=18, unanswerable=2

## Arms

- **baseline** (signal-annotator-v1): deterministic signal-based detection
- **reasoning** (reasoning-based): N/A — no real LLM backend configured; EchoBackend is test-only and never backs research numbers
- **metadata** (metadata-grounded): N/A — no legitimate enrichment.json
- **combined**: merge of enabled legs (baseline only)

## baseline

- existence F1 (macro): 0.4099 (acc 0.5778)
- ambiguous P/R/F1: 0.5682/1.0000/0.7246
- unambiguous P/R/F1: 1.0000/0.0500/0.0952
- TP=25, FP=19, FN=0, TN=1

- span iou_0.5 P/R/F1: 0.0000/0.0000/0.0000
- span iou_0.7 P/R/F1: 0.0000/0.0000/0.0000
- span iou_1 P/R/F1: 0.0000/0.0000/0.0000

- type accuracy: 0.0000 (1/200 localized)
- family accuracy: 0.0000

## per-family

- **C**: P=0.0000, R=0.0000, F1=0.0000 (TP=0, FP=92, FN=1)
- **I**: P=0.0000, R=0.0000, F1=0.0000 (TP=0, FP=5, FN=0)
- **K**: P=0.0000, R=0.0000, F1=0.0000 (TP=0, FP=24, FN=0)
- **R**: P=0.0000, R=0.0000, F1=0.0000 (TP=0, FP=3, FN=1)
- **S**: P=0.0000, R=0.0000, F1=0.0000 (TP=0, FP=66, FN=24)
- **T**: P=0.0000, R=0.0000, F1=0.0000 (TP=0, FP=10, FN=0)

## band confusion

| Gold \ Pred | persistent | metadata_closable | unambiguous |
|---|---|---|---|
| **persistent** | 25 | 0 | 0 |
| **metadata_closable** | 0 | 0 | 0 |
| **unambiguous** | 19 | 0 | 1 |

## persistence

- localized spans: 1
- persistence accuracy: 1.0000

## Human Gold vs AI-GOLD

- common questions: 45
- existence agreement: 24/45 (53.3%)
- span/type disagreements: 36
