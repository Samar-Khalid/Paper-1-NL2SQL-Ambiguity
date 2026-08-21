"""Resolution boundary: assemble the ``ClarifiedQuestion``.

Resolution composes detection and formalization into the final re-phrased
question, honoring ``AmbiguityConfig`` (resolution engine, ``max_assumptions``,
``interactive``). A ``resolution: off`` configuration never reaches this module
— the original question flows to the prompt builder unchanged (M1.2–M1.4
behavior is preserved byte-for-byte). See docs/12 for the channel ordering:
metadata -> clarification -> assumption -> refusal.
"""