"""Baseline validation stage: structural and read-only checks on predicted SQL.

The baseline validator is deliberately simple (docs/11 §11): non-empty, single
statement, no destructive lead keyword, and referenced tables existing in the
schema. It never raises; the verdict is attached to the prediction metadata and
recorded in state for evaluation and error analysis.
"""
from __future__ import annotations

import re
from typing import Any

from ...contracts.errors import PipelineError
from ...contracts.prediction import PredictionEnvelope
from ...contracts.runtime import RuntimeContext
from ...contracts.task import TaskEnvelope
from ..stage import OUTPUT_KEY, PROMPT_KEY, VALIDATION_KEY, get_state, set_state

_FORBIDDEN_LEAD = frozenset(
    {
        "insert", "update", "delete", "drop", "alter", "create", "truncate",
        "grant", "revoke", "merge", "replace", "call", "exec", "execute",
        "vacuum", "attach", "detach", "pragma", "set", "use",
    }
)
_FROM_TABLE = re.compile(r"\bfrom\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)
_JOIN_TABLE = re.compile(r"\bjoin\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE = re.compile(r"--[^\n]*")


def _strip_comments(sql: str) -> str:
    """Replace SQL comments with spaces so tokens are not glued together."""
    return _COMMENT_LINE.sub(" ", _COMMENT_BLOCK.sub(" ", sql))


def _first_word(sql: str) -> str:
    match = re.search(r"[A-Za-z_][A-Za-z0-9_]*", _strip_comments(sql))
    return match.group(0) if match is not None else ""


def _count_statements(sql: str) -> int:
    """Count top-level statement terminators, ignoring those inside strings."""
    clean = _strip_comments(sql)
    in_single = in_double = False
    count = 0
    for char in clean:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == ";" and not in_single and not in_double:
            count += 1
    return count


def _referenced_tables(sql: str) -> list[str]:
    """Return the sorted table names mentioned in FROM/JOIN clauses."""
    clean = _strip_comments(sql)
    names = _FROM_TABLE.findall(clean) + _JOIN_TABLE.findall(clean)
    return sorted({name for name in names})


def validate_sql(
    sql: str,
    *,
    schema_tables: list[str] | None = None,
) -> dict[str, Any]:
    """Run the baseline checks and return a JSON-safe verdict dict."""
    referenced = _referenced_tables(sql)
    checks: dict[str, bool] = {
        "non_empty": bool(sql.strip()),
        "single_statement": _count_statements(sql) <= 1,
        "read_only": _first_word(sql).lower() not in _FORBIDDEN_LEAD,
    }
    if schema_tables is not None:
        known = set(schema_tables)
        unknown = sorted(name for name in referenced if name not in known)
        checks["tables_exist"] = not unknown
    else:
        unknown = []
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not failed,
        "checks": checks,
        "referenced_tables": referenced,
        "unknown_tables": unknown,
        "error": "; ".join(failed) if failed else None,
    }


class ValidationStage:
    """Stage 3: validate the predicted SQL and record the verdict."""

    name = "validation"

    def run(self, context: RuntimeContext, task: TaskEnvelope) -> TaskEnvelope:
        """Attach a validation verdict to the prediction and state."""
        prediction = get_state(context, OUTPUT_KEY)
        if not isinstance(prediction, PredictionEnvelope):
            raise PipelineError(
                f"no prediction in state under '{OUTPUT_KEY}'; validation "
                "must run after the generation stage"
            )
        prompt = get_state(context, PROMPT_KEY)
        schema_tables = prompt.get("schema_tables") if isinstance(prompt, dict) else None
        if prediction.error is not None:
            verdict: dict[str, Any] = {
                "ok": False,
                "checks": {},
                "error": f"prediction carries an error: {prediction.error.error_type}",
            }
        else:
            sql = getattr(prediction.payload, "sql", None)
            verdict = validate_sql(
                sql if isinstance(sql, str) else "",
                schema_tables=schema_tables if isinstance(schema_tables, list) else None,
            )
        set_state(context, VALIDATION_KEY, verdict)
        updated = prediction.model_copy(
            update={"metadata": {**prediction.metadata, "validation": verdict}}
        )
        set_state(context, OUTPUT_KEY, updated)
        return task
