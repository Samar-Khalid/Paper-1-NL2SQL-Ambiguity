"""Detection boundary: question -> ``AmbiguityAnalysis``.

M1.5 slice 1 defines the contract boundary only; the detectors live in the
``detectors`` subpackage. They implement ``AmbiguityResolver.analyze``: the
first evidence family (``metadata_grounded``, docs/14 §4A) is a deterministic
pass that pins readings with enterprise-enrichment lookups; a later reasoning
pass will label persistent ambiguity with the ``AmbiguityType`` taxonomy
(docs/12). They consume schemas through the injected ``SchemaProvider`` /
``MetadataProvider`` — never adapter internals — so the ON/OFF experiment
factor stays dataset-independent.
"""