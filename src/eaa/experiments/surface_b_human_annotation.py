"""Human Gold annotation CLI + local web UI for Surface B (M1.5, docs/23).

A single-process, stdlib-only workflow for the researcher to annotate the 45
usable Surface B questions into a genuine Human Gold reference set, fully
separated from the frozen AI pilot (``batch-1`` / ``surface_b.v1.lock``)::

    # 1. rebuild + inspect the deterministic task list (45 usable questions)
    python -m eaa.experiments.surface_b_human_annotation --mode list

    # 2. launch the local annotation UI (browser on http://127.0.0.1:8765)
    python -m eaa.experiments.surface_b_human_annotation --mode launch --annotator researcher

    # 3. validate the in-progress human annotations without freezing
    python -m eaa.experiments.surface_b_human_annotation --mode validate --annotator researcher

    # 4. freeze the complete Human Gold set (separate lock; AI pilot untouched)
    python -m eaa.experiments.surface_b_human_annotation --mode freeze --annotator researcher

    # 5. status: counts, artifact path, commands, AI-pilot lock verification
    python -m eaa.experiments.surface_b_human_annotation --mode status

The UI exposes only question text, database id, the warehouse schema, and the
signal hints; it never serves gold, AI labels, or the pilot stratum. Decisions
persist as per-question JSON under ``meta/`` (source of truth) with derived
``annotation-schema-v1`` files under ``annotations/``; the freeze hashes only
the derived files and the human provenance sidecar. No label is ever generated
by this tool itself.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from eaa.ambiguity_resolution.annotations import (
    AnnotationPrepError,
    build_human_provenance,
    build_human_record,
    build_human_task_list,
    freeze_human_gold,
    human_task_payload,
    record_to_flat_dict,
    regenerate_human_records,
    schema_to_annotator_view,
    validate_human_record,
    validate_human_root,
    write_human_provenance,
    write_human_task_list,
)
from eaa.ambiguity_resolution.annotations._io import write_json
from eaa.ambiguity_resolution.annotations.human import _enrichment_tokens
from eaa.ambiguity_resolution.annotations.qc import _freeze_digest
from eaa.core.contracts.errors import EAAError
from eaa.core.contracts.schema import DatabaseSchema

from .errors import ExperimentError

DEFAULT_CONFIG = Path("configs/experiments/phase1_beaver_eval.yaml")
DEFAULT_CANDIDATES = Path("data/annotations/surface_b/candidates.json")
DEFAULT_BATCH_ROOT = Path("data/annotations/surface_b/batch-1")
DEFAULT_HUMAN_ROOT = Path("data/annotations/surface_b/human-gold")
DEFAULT_DATA_ROOT = Path("data/raw/beaver")
DEFAULT_LOCK = DEFAULT_HUMAN_ROOT / "human-gold.v1.lock"
DEFAULT_AI_LOCK = Path("data/annotations/surface_b/surface_b.v1.lock")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_UI_FILE = Path(__file__).with_name("web") / "human_annotation_ui.html"


class HumanGoldApp:
    """Application logic behind the local annotation UI (no HTTP knowledge).

    Routes are exposed through :meth:`route`, which returns
    ``(status, json_payload, html)`` so tests can drive it directly and the
    stdlib HTTP handler stays a thin transport.
    """

    def __init__(
        self,
        *,
        task_list: Mapping[str, Any],
        schemas: Mapping[str, DatabaseSchema],
        human_root: str | Path,
        annotator_id: str,
        enrichment_tokens: Mapping[str, str | None] | None = None,
    ) -> None:
        self._task_list = task_list
        self._schemas = schemas
        self._root = Path(human_root)
        self._annotator_id = annotator_id
        self._tokens = dict(enrichment_tokens) if enrichment_tokens else {}
        self._tasks = {
            task["question_id"]: task for task in task_list["tasks"]
        }
        self._html: str | None = None

    @property
    def root(self) -> Path:
        """Return the Human Gold workspace root."""
        return self._root

    @property
    def meta_dir(self) -> Path:
        """Return the directory holding the researcher's raw decisions."""
        return self._root / "meta"

    @property
    def annotations_dir(self) -> Path:
        """Return the directory holding the derived annotation records."""
        return self._root / "annotations"

    def annotated_ids(self) -> list[str]:
        """Question ids with a saved meta decision, sorted."""
        meta_dir = self.meta_dir
        if not meta_dir.is_dir():
            return []
        return sorted(path.stem for path in meta_dir.glob("*.json"))

    def route(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any] | None, str | None]:
        """Dispatch one request; returns ``(status, json, html)``."""
        parsed = urllib.parse.urlparse(path)
        parts = [part for part in parsed.path.split("/") if part]
        if method == "GET" and not parts:
            return 200, None, self._ui_html()
        if method == "GET" and parts == ["api", "tasks"]:
            return 200, self._api_tasks(), None
        if method == "GET" and parts == ["api", "schemas"]:
            return 200, self._api_schemas(), None
        if method == "GET" and parts == ["api", "status"]:
            return 200, self._api_status(), None
        if (
            method == "GET"
            and len(parts) == 3
            and parts[0] == "api"
            and parts[1] == "task"
        ):
            return self._api_task(parts[2])
        if (
            method == "POST"
            and len(parts) == 4
            and parts[0] == "api"
            and parts[1] == "task"
            and parts[3] == "annotation"
        ):
            return self._save_annotation(parts[2], body or {})
        if method == "POST" and parts == ["api", "regenerate"]:
            return self._regenerate()
        return 404, {"error": f"no route for {method} {path}"}, None

    def _ui_html(self) -> str:
        if self._html is None:
            if not _UI_FILE.is_file():
                raise AnnotationPrepError(
                    f"annotation UI template missing: {_UI_FILE}"
                )
            self._html = _UI_FILE.read_text(encoding="utf-8")
        return self._html

    def _api_tasks(self) -> dict[str, Any]:
        return human_task_payload(self._task_list)

    def _api_schemas(self) -> dict[str, Any]:
        database_ids = sorted(
            {task["database_id"] for task in self._task_list["tasks"]}
        )
        return {
            database_id: (
                schema_to_annotator_view(self._schemas[database_id])
                if database_id in self._schemas
                else None
            )
            for database_id in database_ids
        }

    def _api_status(self) -> dict[str, Any]:
        annotated = self.annotated_ids()
        return {
            "annotator_id": self._annotator_id,
            "root": str(self._root),
            "total": len(self._tasks),
            "annotated": len(annotated),
            "annotated_ids": annotated,
        }

    def _api_task(self, question_id: str) -> tuple[int, dict[str, Any], None]:
        task = self._tasks.get(question_id)
        if task is None:
            return 404, {"error": f"unknown task {question_id!r}"}, None
        payload = {
            "question_id": task["question_id"],
            "database_id": task["database_id"],
            "question": task["question"],
            "signals": task["signals"],
            "saved": (self.meta_dir / f"{question_id}.json").is_file(),
        }
        return 200, payload, None

    def _save_annotation(
        self, question_id: str, body: Mapping[str, Any]
    ) -> tuple[int, dict[str, Any], None]:
        task = self._tasks.get(question_id)
        if task is None:
            return 404, {"error": f"unknown task {question_id!r}"}, None
        answerability = body.get("answerability") or {}
        try:
            record = build_human_record(
                question_id=question_id,
                question_text=task["question"],
                database_id=task["database_id"],
                answerability=str(answerability.get("label", "answerable")),
                confidence=float(answerability.get("confidence", 1.0)),
                spans=list(body.get("spans") or []),
                readings=body.get("interpretations"),
                notes=body.get("notes"),
            )
        except (ValueError, TypeError) as exc:
            return 400, {"saved": False, "problems": [str(exc)]}, None
        token = self._tokens.get(task["database_id"])
        problems = validate_human_record(record, enrichment_token=token)
        if problems:
            return 400, {"saved": False, "problems": problems}, None

        decision = {
            "question_id": question_id,
            "answerability": {
                "label": record.question.answerability.label.value,
                "confidence": record.question.answerability.confidence,
            },
            "spans": [
                {
                    "type": span.ambiguity_type.value,
                    "phrase": span.text,
                    "assumption_risk": span.assumption_risk.value,
                    "resolution_channel": span.resolution_channel.value,
                    "clarification_required": span.clarification_required,
                    "metadata_resolution": span.metadata_resolution,
                }
                for span in record.question.spans
            ],
            "interpretations": (
                {
                    "sql_reading_A": {
                        "sql": record.interpretations["sql_reading_A"].sql,
                        "note": record.interpretations["sql_reading_A"].note,
                    },
                    "sql_reading_B": {
                        "sql": record.interpretations["sql_reading_B"].sql,
                        "note": record.interpretations["sql_reading_B"].note,
                    },
                }
                if record.interpretations is not None
                else None
            ),
            "notes": record.notes,
        }
        write_json(decision, self.meta_dir / f"{question_id}.json")
        write_json(
            record_to_flat_dict(record),
            self.annotations_dir / f"{question_id}.json",
        )
        return 200, {"saved": True, "question_id": question_id}, None

    def _regenerate(self) -> tuple[int, dict[str, Any], None]:
        written = regenerate_human_records(
            self._task_list, self.meta_dir, self.annotations_dir
        )
        return 200, {"regenerated": len(written)}, None


class _HttpAppHandler(BaseHTTPRequestHandler):
    """Thin stdlib transport around :class:`HumanGoldApp`."""

    server: HumanGoldHttpServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
        self._dispatch("GET", {})

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        body: Mapping[str, Any] = {}
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._respond(400, {"error": "request body is not valid JSON"}, None)
                return
            if not isinstance(parsed, dict):
                self._respond(400, {"error": "request body must be a JSON object"}, None)
                return
            body = parsed
        self._dispatch("POST", body)

    def _dispatch(self, method: str, body: Mapping[str, Any]) -> None:
        try:
            status, payload, html = self.server.app.route(method, self.path, body)
        except (AnnotationPrepError, ValueError, OSError) as exc:
            status, payload, html = 500, {"error": str(exc)}, None
        self._respond(status, payload, html)

    def _respond(
        self,
        status: int,
        payload: dict[str, Any] | None,
        html: str | None,
    ) -> None:
        if html is not None:
            data = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        data = json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        sys.stderr.write(f"[human-gold] {self.address_string()}: {format % args}\n")


class HumanGoldHttpServer(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` carrying the application instance."""

    daemon_threads = True

    def __init__(self, addr: tuple[str, int], app: HumanGoldApp) -> None:
        self.app = app
        super().__init__(addr, _HttpAppHandler)


def _resolve_adapter_schemas(
    config_path: str | Path, config_root: str | None
) -> dict[str, DatabaseSchema]:
    """Resolve the per-database schemas from the configured adapter."""
    from eaa.core.configuration import resolve_config

    from .baseline import _load_adapter, _schema_provider_of

    config = resolve_config(config_path, config_root=config_root, overrides={})
    adapter = _load_adapter(config)
    provider = _schema_provider_of(adapter)
    databases = adapter.manifest().extra.get("databases", [])
    schemas: dict[str, DatabaseSchema] = {}
    for database_id in databases:
        schema = provider.get_schema(database_id)
        if isinstance(schema, DatabaseSchema):
            schemas[database_id] = schema
    return schemas


def _load_config_or_warn(config_path: str | Path) -> dict[str, DatabaseSchema]:
    """Best-effort schema resolution; the UI degrades to 'unavailable'."""
    try:
        return _resolve_adapter_schemas(config_path, None)
    except Exception as exc:  # noqa: BLE001 - the UI must still launch
        print(
            f"warning: cannot resolve warehouse schemas ({exc}); the UI will "
            "show schema as unavailable",
            file=sys.stderr,
        )
        return {}


def _build_task_list(
    candidates: str | Path, batch_root: str | Path
) -> dict[str, Any]:
    return build_human_task_list(candidates, batch_root)


def _verify_ai_pilot_lock(
    batch_root: str | Path, lock_path: str | Path
) -> tuple[bool, str | None]:
    """Recompute the frozen AI-pilot digest from its own lock file.

    Uses exactly the file list recorded in ``surface_b.v1.lock`` so the check
    reproduces the original SHA-256; ``True`` means the pilot is untouched.
    """
    lock_file = Path(lock_path)
    if not lock_file.is_file():
        return False, "AI-pilot lock file missing"
    payload = json.loads(lock_file.read_text(encoding="utf-8"))
    files = [Path(str(item)) for item in payload.get("files", [])]
    if not files:
        return False, "AI-pilot lock records no files"
    try:
        digest = _freeze_digest(files, base=Path(batch_root))
    except OSError as exc:
        return False, f"cannot recompute AI-pilot digest: {exc}"
    expected = payload.get("sha256")
    return digest == expected, expected


def _write_human_provenance(
    task_list: Mapping[str, Any],
    root: Path,
    *,
    annotator_id: str,
    tokens: Mapping[str, str | None],
) -> None:
    """Create/refresh the honest single-annotator sidecar (docs/23 §4)."""
    provenance_path = root / "provenance-v1.json"
    if provenance_path.is_file():
        existing = json.loads(provenance_path.read_text(encoding="utf-8"))
        if existing:
            first = next(iter(existing.values()))
            if first.get("annotator_ids") != [annotator_id]:
                raise AnnotationPrepError(
                    f"existing provenance sidecar records annotator "
                    f"{first.get('annotator_ids')!r}; refusing to overwrite with "
                    f"{annotator_id!r}"
                )
            return
    by_database: dict[str, list[str]] = {}
    for task in task_list["tasks"]:
        by_database.setdefault(task["database_id"], []).append(task["question_id"])
    entries: dict[str, Any] = {}
    for database_id, question_ids in sorted(by_database.items()):
        entries.update(
            build_human_provenance(
                question_ids,
                database_id=database_id,
                annotator_id=annotator_id,
                enrichment_token=tokens.get(database_id),
            )
        )
    write_human_provenance(entries, provenance_path)


def _run_list(args: argparse.Namespace) -> int:
    task_list = _build_task_list(args.candidates, args.batch_root)
    root = Path(args.human_root)
    root.mkdir(parents=True, exist_ok=True)
    write_human_task_list(task_list, root / "tasks.json")
    totals = task_list["totals"]
    print(f"human-gold task list written to {root / 'tasks.json'}")
    print(
        f"usable tasks: {totals['usable']} "
        f"(persistent_ambiguity={totals['persistent_ambiguity']}, "
        f"unambiguous={totals['unambiguous']}); "
        f"excluded metadata_deferred={totals['excluded_metadata_deferred']}, "
        f"excluded unanswerable={totals['excluded_unanswerable']}"
    )
    return 0


def _run_launch(args: argparse.Namespace) -> int:
    if not args.annotator:
        print("error: --annotator (researcher id) is required to launch", file=sys.stderr)
        return 1
    task_list = _build_task_list(args.candidates, args.batch_root)
    schemas = _load_config_or_warn(args.config)
    root = Path(args.human_root)
    root.mkdir(parents=True, exist_ok=True)
    write_human_task_list(task_list, root / "tasks.json")
    tokens = _enrichment_tokens(
        args.data_root, [task["database_id"] for task in task_list["tasks"]]
    )
    _write_human_provenance(task_list, root, annotator_id=args.annotator, tokens=tokens)
    app = HumanGoldApp(
        task_list=task_list,
        schemas=schemas,
        human_root=root,
        annotator_id=args.annotator,
        enrichment_tokens=tokens,
    )
    server = HumanGoldHttpServer((args.host, args.port), app)
    url = f"http://{args.host}:{args.port}"
    print(f"Human Gold annotation UI: {url}")
    print(f"annotator: {args.annotator}; tasks: {len(task_list['tasks'])}")
    print("decisions persist under " + str(root / "meta"))
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        server.server_close()
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    if not args.annotator:
        print("error: --annotator is required to validate", file=sys.stderr)
        return 1
    task_list = _build_task_list(args.candidates, args.batch_root)
    dataset, problems = validate_human_root(
        args.human_root,
        annotator_id=args.annotator,
        data_root=args.data_root,
        task_list=task_list,
    )
    if problems:
        for problem in problems:
            print(f"problem: {problem}", file=sys.stderr)
        print(f"human-gold INVALID ({len(problems)} problems)", file=sys.stderr)
        return 1
    if dataset is None:
        print("human-gold INVALID (records did not load)", file=sys.stderr)
        return 1
    print(f"human-gold VALID ({len(dataset.records)} annotated questions)")
    return 0


def _run_freeze(args: argparse.Namespace) -> int:
    if not args.annotator:
        print("error: --annotator is required to freeze", file=sys.stderr)
        return 1
    task_list = _build_task_list(args.candidates, args.batch_root)
    record = freeze_human_gold(
        root=args.human_root,
        annotator_id=args.annotator,
        lock_path=args.lock,
        data_root=args.data_root,
        task_list=task_list,
    )
    print(f"human-gold freeze OK: sha256={record['sha256']}")
    print(
        f"lock written to {args.lock} ({len(record['files'])} files hashed); "
        "AI-pilot lock and batch-1 untouched"
    )
    return 0


def _run_status(args: argparse.Namespace) -> int:
    root = Path(args.human_root)
    task_list = _build_task_list(args.candidates, args.batch_root)
    annotated = (
        sorted(path.stem for path in (root / "meta").glob("*.json"))
        if (root / "meta").is_dir()
        else []
    )
    ok, expected = _verify_ai_pilot_lock(args.batch_root, args.ai_lock)
    print(f"human-gold root : {root}")
    print(f"task list       : {root / 'tasks.json'} ({task_list['totals']['usable']} usable)")
    print(f"annotated       : {len(annotated)}/{task_list['totals']['usable']}")
    if ok:
        print(f"AI-pilot lock   : OK (sha256={expected})")
    else:
        print(f"AI-pilot lock   : MISMATCH ({expected})", file=sys.stderr)
    print("commands:")
    print(
        "  python -m eaa.experiments.surface_b_human_annotation "
        "--mode launch --annotator <id>"
    )
    print(
        "  python -m eaa.experiments.surface_b_human_annotation "
        "--mode validate --annotator <id>"
    )
    print(
        "  python -m eaa.experiments.surface_b_human_annotation "
        "--mode freeze --annotator <id>"
    )
    return 0 if ok else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m eaa.experiments.surface_b_human_annotation",
        description="Build the Human Gold task list, run the local annotation "
        "UI, validate, and freeze the Human Gold set (docs/23).",
    )
    parser.add_argument(
        "--mode",
        choices=["list", "launch", "validate", "freeze", "status"],
        default="status",
        help="workflow step (default: status)",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument(
        "--candidates",
        default=str(DEFAULT_CANDIDATES),
        help="gold-free candidate pool artifact",
    )
    parser.add_argument(
        "--batch-root",
        default=str(DEFAULT_BATCH_ROOT),
        help="frozen batch-1 root whose labels define the usable task set",
    )
    parser.add_argument(
        "--human-root",
        default=str(DEFAULT_HUMAN_ROOT),
        help="Human Gold artifact directory (meta/, annotations/, sidecar, lock)",
    )
    parser.add_argument(
        "--data-root",
        default=str(DEFAULT_DATA_ROOT),
        help="raw BEAVER data root used to verify enrichment snapshots",
    )
    parser.add_argument(
        "--annotator",
        default=None,
        help="researcher id recorded as the single human annotator",
    )
    parser.add_argument(
        "--lock",
        default=str(DEFAULT_LOCK),
        help="Human Gold freeze lock output path",
    )
    parser.add_argument(
        "--ai-lock",
        default=str(DEFAULT_AI_LOCK),
        help="frozen AI-pilot lock used by --mode status for integrity checks",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="UI bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UI bind port")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested Human Gold step; return the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        if args.mode == "list":
            return _run_list(args)
        if args.mode == "launch":
            return _run_launch(args)
        if args.mode == "validate":
            return _run_validate(args)
        if args.mode == "freeze":
            return _run_freeze(args)
        if args.mode == "status":
            return _run_status(args)
        raise AnnotationPrepError(f"unknown mode {args.mode!r}")
    except (AnnotationPrepError, ExperimentError, EAAError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


__all__ = [
    "DEFAULT_AI_LOCK",
    "DEFAULT_BATCH_ROOT",
    "DEFAULT_CANDIDATES",
    "DEFAULT_CONFIG",
    "DEFAULT_DATA_ROOT",
    "DEFAULT_HOST",
    "DEFAULT_HUMAN_ROOT",
    "DEFAULT_LOCK",
    "DEFAULT_PORT",
    "HumanGoldApp",
    "HumanGoldHttpServer",
    "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
