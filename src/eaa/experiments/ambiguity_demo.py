"""Paper 1 live-demo CLI (docs/22).

Launches the interactive ambiguity-analysis demo over the frozen Paper 1
detectors: pick a BEAVER warehouse, ask an arbitrary question, and read a
human-readable ``AmbiguityAnalysis`` (deterministic baseline, plus the
reasoning leg when a real LLM backend is configured). The demo is research
tooling, not a benchmark: it reads no gold, writes no labels, and never
touches the frozen Surface B batch.

Usage::

    eaa-ambiguity-demo                          # interactive REPL (dw)
    eaa-ambiguity-demo --database neutron
    eaa-ambiguity-demo --question "Show the subject code where the department is Mathematics."
    eaa-ambiguity-demo --mode reasoning --question "..."
    eaa-ambiguity-demo --examples               # curated real BEAVER questions
    eaa-ambiguity-demo --list-databases

The reasoning leg requires ``llm.provider`` (openai/openai-compatible/vllm/
ollama), ``llm.model``, and the ``llm.api_key_env`` credential; otherwise it is
reported as unavailable, never faked (``EchoBackend`` is test-only).
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from eaa.ambiguity_resolution.candidates.selection import CandidateRecord, load_candidates
from eaa.ambiguity_resolution.demo import (
    DEMO_DISCLAIMER,
    DEMO_VERSION,
    DemoAnalysis,
    analyze_demo,
    render_analysis,
)
from eaa.core.configuration import resolve_config
from eaa.core.contracts.errors import EAAError
from eaa.core.contracts.schema import DatabaseSchema
from eaa.core.registry import plugin_registry

from .errors import ExperimentError

DEFAULT_CONFIG = "configs/experiments/phase1_beaver_eval.yaml"
DEFAULT_CANDIDATES = "data/annotations/surface_b/candidates.json"
DEFAULT_DATABASE = "dw"

_REAL_PROVIDERS = ("openai", "openai-compatible", "vllm", "ollama")

_EXAMPLE_MAX_QUESTION_LEN = 260

#: Control example demonstrating the unambiguous path. Deliberately NOT a
#: BEAVER candidate: every dev question in the candidate pool fires at least
#: one reasoning-grounded screening signal, so the deterministic baseline never
#: reports "no ambiguity" on them (docs/19 — the pool screens suspicious
#: questions only). A clearly-labelled control question shows the unambiguous
#: output path without mislabelling a benchmark question.
_CONTROL_QUESTION = ("dw", "control-01", "Show the department names.")

#: Curation targets: (signal id, display label) for the ``--examples`` tour.
_EXAMPLE_TARGETS: tuple[tuple[str, str], ...] = (
    ("s1", "scope/constraint (quantifier scope, S1)"),
    ("r1", "table-selection risk (R1 screening hint)"),
    ("r2", "join path (R2)"),
    ("c1", "aggregation/metric (C1)"),
    ("t1", "relative temporal (T1)"),
    ("v1", "entity/value (V1 screening hint)"),
)


def list_databases(config_path: str | Path) -> list[str]:
    """Return the database ids served by the configured dataset adapter."""
    adapter = _build_adapter(config_path)
    databases = (adapter.manifest().extra or {}).get("databases")
    if not isinstance(databases, list) or not databases:
        raise ExperimentError(
            "the dataset adapter manifest exposes no 'databases' list"
        )
    return [str(item) for item in databases]


def load_schema(config_path: str | Path, database_id: str) -> DatabaseSchema:
    """Return the plain (un-enriched) schema for one BEAVER warehouse."""
    adapter = _build_adapter(config_path)
    return cast(DatabaseSchema, adapter.schema_provider().get_schema(database_id))


def load_backend(config_path: str | Path) -> Any | None:
    """Return a real LLM backend when configured, else ``None``.

    A missing provider, model, or credential yields ``None`` so the demo can
    report the reasoning leg as unavailable instead of faking it (EchoBackend
    is test-only and is never used for demo results).
    """
    config = resolve_config(config_path)
    llm = config.root.llm
    provider = (llm.provider or "").lower()
    if provider not in _REAL_PROVIDERS or not llm.model:
        return None
    key_env = llm.api_key_env or "OPENAI_API_KEY"
    if not os.environ.get(key_env):
        return None
    from eaa.llm import backend_from_config

    return backend_from_config(llm)


def example_questions(
    candidates_path: str | Path,
) -> list[tuple[str, str, str, str]]:
    """Curate real, gold-free BEAVER dev questions for the demo tour.

    Returns ``(database_id, question_id, question, label)`` tuples: one real
    candidate per signal target plus one clearly-labelled control question
    demonstrating the unambiguous path. The pool screens only suspicious
    questions (every dev candidate fires a reasoning-grounded signal, so the
    baseline never reports "no ambiguity" on them, docs/19); no benchmark
    question is therefore mislabelled as unambiguous. Selection reads only the
    gold-free candidate artifact; the analysis itself always runs live.
    """
    pool = load_candidates(Path(candidates_path))
    records = [
        record
        for record in pool.candidates
        if record.database_id != "dw_real"
    ]
    chosen: list[tuple[str, str, str, str]] = []
    seen_questions: set[str] = set()

    def _pick(record: CandidateRecord) -> bool:
        if len(record.question) > _EXAMPLE_MAX_QUESTION_LEN:
            return False
        return record.question not in seen_questions

    for signal_id, label in _EXAMPLE_TARGETS:
        for record in records:
            if not _pick(record):
                continue
            if any(hit.signal == signal_id for hit in record.signals):
                seen_questions.add(record.question)
                chosen.append(
                    (record.database_id, record.question_id, record.question, label)
                )
                break

    control_db, control_id, control_text = _CONTROL_QUESTION
    if control_text not in seen_questions:
        chosen.append(
            (
                control_db,
                control_id,
                control_text,
                "control - unambiguous path (not a benchmark question)",
            )
        )

    return chosen


def _build_adapter(config_path: str | Path) -> Any:
    """Resolve the configured dataset adapter plugin (entry-point group)."""
    config = resolve_config(config_path)
    name = config.root.dataset.name
    if not name:
        raise ExperimentError("dataset.name is not set in the experiment config")
    factory = plugin_registry.discover().get(name)
    if factory is None:
        raise ExperimentError(
            f"no dataset adapter plugin named {name!r} in 'eaa.datasets'"
        )
    data_root = config.root.dataset.data_root
    if data_root:
        try:
            return cast(Any, factory)(root=data_root)
        except TypeError:
            return factory()
    return factory()


def _run(
    *,
    question: str,
    database_id: str,
    mode: str,
    config_path: str | Path,
    backend: Any | None,
    session_id: str | None,
) -> DemoAnalysis:
    schema = load_schema(config_path, database_id)
    return analyze_demo(
        question,
        schema,
        mode=mode,
        llm_backend=backend,
        session_id=session_id,
    )


def _run_examples(
    config_path: str | Path,
    candidates_path: str | Path,
    mode: str,
    backend: Any | None,
) -> int:
    examples = example_questions(candidates_path)
    if not examples:
        print(
            f"error: no example questions found in {candidates_path}",
            file=sys.stderr,
        )
        return 1
    schemas: dict[str, DatabaseSchema] = {}
    session_id = "paper1-demo-examples"
    for index, (database_id, question_id, question, label) in enumerate(
        examples, start=1
    ):
        print("=" * 72)
        print(f"EXAMPLE {index}/{len(examples)}  [{database_id}] {question_id}")
        print(f"focus   : {label}")
        print("=" * 72)
        schema = schemas.get(database_id) or load_schema(config_path, database_id)
        schemas[database_id] = schema
        analysis = analyze_demo(
            question,
            schema,
            mode=mode,
            llm_backend=backend,
            session_id=session_id,
        )
        print(render_analysis(analysis))
        print()
    return 0


def _repl(
    database_id: str,
    mode: str,
    config_path: str | Path,
    backend: Any | None,
    session_id: str | None,
) -> int:
    print("Paper 1 demo - ambiguity analysis (deterministic baseline)"
          f" | mode={mode} | database={database_id}")
    print(DEMO_DISCLAIMER)
    print("Type a question (empty line to exit).")
    while True:
        try:
            line = input("\nquestion> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            return 0
        try:
            analysis = _run(
                question=line,
                database_id=database_id,
                mode=mode,
                config_path=config_path,
                backend=backend,
                session_id=session_id,
            )
        except (EAAError, ValueError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            continue
        print()
        print(render_analysis(analysis))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the demo CLI; return a process exit code."""
    parser = argparse.ArgumentParser(
        prog="eaa-ambiguity-demo",
        description="Interactive Paper 1 ambiguity-analysis demo (docs/22).",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument(
        "--mode",
        default="baseline",
        choices=("baseline", "reasoning", "combined"),
    )
    parser.add_argument("--question", default=None, help="one-shot question")
    parser.add_argument("--examples", action="store_true",
                        help="run curated real BEAVER questions")
    parser.add_argument("--list-databases", action="store_true")
    parser.add_argument("--candidates", default=DEFAULT_CANDIDATES)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--version", action="version", version=DEMO_VERSION)
    args = parser.parse_args(argv)

    try:
        if args.list_databases:
            print("\n".join(list_databases(args.config)))
            return 0

        backend = None
        if args.mode in ("reasoning", "combined"):
            backend = load_backend(args.config)
            if backend is None:
                print(
                    "note: no real LLM backend configured (llm.provider/model/"
                    "api key); the reasoning leg will be reported as "
                    "unavailable (never faked).",
                    file=sys.stderr,
                )

        if args.examples:
            return _run_examples(args.config, args.candidates, args.mode, backend)

        if args.question:
            if not args.question.strip():
                print("error: --question must not be empty", file=sys.stderr)
                return 1
            analysis = _run(
                question=args.question,
                database_id=args.database,
                mode=args.mode,
                config_path=args.config,
                backend=backend,
                session_id=args.session_id,
            )
            print(render_analysis(analysis))
            return 0

        return _repl(
            args.database, args.mode, args.config, backend, args.session_id
        )
    except (EAAError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_CANDIDATES",
    "DEFAULT_CONFIG",
    "DEFAULT_DATABASE",
    "example_questions",
    "list_databases",
    "load_backend",
    "load_schema",
    "main",
]
