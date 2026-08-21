"""Deterministic JSON I/O shared by the annotation-preparation tooling."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(payload: Any, path: str | Path) -> Path:
    """Write ``payload`` as deterministic JSON (sorted keys, fixed indent)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return target


def read_json(path: str | Path) -> Any:
    """Read and parse a UTF-8 JSON file (``JSONDecodeError`` on failure)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
