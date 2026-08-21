# Changelog

All notable changes to Paper 1: NL2SQL Ambiguity Detection are documented here.

## [1.0.0] - 2026-08-21

### Final Release — Paper 1 Frozen

#### Added
- Human Gold evaluation set: 45 annotated questions, frozen with SHA-256 verification
- Human Gold evaluation results: SignalAnnotator baseline vs Human Gold
- Error analysis: span granularity mismatch documented
- Human Gold vs AI-GOLD pilot comparison (53.3% existence agreement)
- Standalone repository snapshot

#### Frozen
- Human Gold SHA-256: `1df1ee495b67f2430da995a1ab8ea1c5a693c2b1c32e2737ad9a6e55fee210a4`
- AI Pilot SHA-256: `e215880a439656dfce29d0d9e4f466193fb78f60bf3b894aef9734bc0d469db7`

## [0.9.0] - 2026-08-19

### Human Gold Annotation Workflow

#### Added
- Human annotation app (Flask-based UI)
- Annotation workspace generation from candidates
- Human validator with M1.5 taxonomy enforcement
- Batch regeneration from meta files
- Separate human-gold lock file

#### Fixed
- `clarification_required` bug: 26 spans corrected to `true`
- `dw_1061` unanswerable note added

## [0.8.0] - 2026-08-15

### AI-Gold Pilot Evaluation

#### Added
- SignalAnnotator baseline detector
- 16 signal detectors for M1.5 taxonomy
- Evaluation metrics: existence, span IoU, classification, persistence
- Deterministic evaluation pipeline
- Baseline results: existence macro F1 = 0.4952

## [0.7.0] - 2026-08-10

### Annotation Infrastructure

#### Added
- AI annotation batch generation
- Annotation models with M1.5 taxonomy
- QC validation pipeline
- Provenance tracking
- Batch freeze and lock mechanism

## [0.6.0] - 2026-08-05

### Detector Architecture

#### Added
- ReasoningBasedDetector (LLM-based)
- MetadataGroundedDetector (enrichment-based)
- Schema index for detector grounding
- Text matching utilities

## [0.5.0] - 2026-08-01

### M1.5 Taxonomy

#### Added
- 10 ambiguity types across 6 families
- Ambiguity contracts and models
- Demo CLI with baseline mode

## [0.4.0] - 2026-07-25

### Candidate Selection

#### Added
- Question screening signals
- Candidate pool generation
- BEAVER adapter integration

## [0.3.0] - 2026-07-20

### Core Framework

#### Added
- Core contracts and registry
- Plugin system for dataset adapters
- Configuration loader
- Observability infrastructure

## [0.2.0] - 2026-07-15

### BEAVER Adapter

#### Added
- BEAVER dataset adapter
- Schema provider
- Manifest and metadata handling

## [0.1.0] - 2026-07-10

### Initial Setup

#### Added
- Project structure
- pyproject.toml
- Basic test infrastructure
