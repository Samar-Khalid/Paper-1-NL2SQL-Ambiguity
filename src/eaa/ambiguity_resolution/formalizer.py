"""Formalization boundary: ``AmbiguityAnalysis`` -> ``Assumption`` list.

Formalization turns detected ambiguity into explicit candidate interpretations:
for each detected span it records the reading adopted and the resolution channel
that closed it (metadata lookup, clarification answer, or assumed default). The
output feeds ``ClarifiedQuestion.assumptions`` so every downstream query can be
audited back to the ambiguity it resolves (docs/12, ADR-014).
"""