"""Generic baseline pipeline stages (dataset-independent, ADR-002/006).

The stages compose into the M1.2 baseline pipeline: prompt builder -> LLM
generation -> validation -> evaluation. They consume only core contracts and
injected collaborators (``LLMBackend``, ``SchemaProvider``, ``gold_for``), so
the same pipeline runs against any dataset adapter that yields ``TaskEnvelope``
objects. No dataset name appears here.
"""
