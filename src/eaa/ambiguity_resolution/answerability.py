"""Answerability boundary: task -> ``AnswerabilityVerdict`` (RQ1.4).

An implementer of ``AnswerabilityJudger`` decides whether the (possibly
clarified) question is answerable from the available data: missing data,
false premises, contradictions, and out-of-scope questions produce an
``unanswerable`` verdict with a reason instead of a guessed SQL (docs/12).
Evaluation uses the project's self-labeled subset; the benchmark itself ships
no answerability labels (ADR-013).
"""