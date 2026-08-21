"""BEAVER adapter-local manifest: version pinning, checksums, DatasetManifest.

The framework ships no BEAVER data. An operator downloads the raw distribution
into a gitignored data root and records an integrity ``manifest.json`` there
(version, checksum, downloaded splits, databases). The adapter pins a data
contract version, verifies the on-disk manifest against it, and verifies the
recorded checksum against the data files (docs/05 §5). Everything here is
adapter-local; the core contract returned by the adapter is ``DatasetManifest``.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from eaa.core.contracts.errors import AdapterError
from eaa.core.contracts.manifest import DatasetManifest

#: Data-contract version this adapter understands. Must match the ``version``
#: recorded in the data-root ``manifest.json`` (see configs/datasets/beaver.yaml).
BEAVER_DATA_VERSION = "1.0"

#: Benchmark-level split identity (Chen et al.); the private test set is handled
#: as "unavailable locally" (ADR-013, docs/11 §3.2).
BEAVER_SPLITS = ["dev", "test"]

BEAVER_DIALECT = "mysql"
BEAVER_TYPE_KEYS = ["nl2sql"]
BEAVER_HOMEPAGE = "https://beaverbench.github.io/"
BEAVER_CITATION = (
    "BEAVER: An Enterprise Benchmark for Text-to-SQL "
    "(Chen et al., 2024, arXiv:2409.02038)"
)
BEAVER_LICENSE = "research-use"
BEAVER_DESCRIPTION = (
    "Enterprise text-to-SQL benchmark derived from private data warehouses "
    "(DW/NW, MySQL dialect)."
)

MANIFEST_FILE = "manifest.json"

#: Per-database data files. ``dev.json``/``dev_tables.json`` are the filenames
#: produced by the official ``data/download_hf.py``; the ``tables.json`` /
#: ``questions.json`` aliases are the canonical adapter names.
QUESTION_FILES = ("questions.json", "dev.json")
TABLE_FILES = ("tables.json", "dev_tables.json")

ENTRY_POINT = "eaa.datasets.adapters.beaver:plugin"
_DATA_ROOT_ENV = "EAA_BEAVER_DATA_ROOT"
_DEFAULT_DATA_ROOT = "data/raw/beaver"


def default_data_root() -> Path:
    """Return the data root from ``EAA_BEAVER_DATA_ROOT`` or the repo default."""
    env = os.environ.get(_DATA_ROOT_ENV)
    return Path(env) if env else Path(_DEFAULT_DATA_ROOT)


def load_raw_manifest(root: Path) -> dict[str, Any]:
    """Load and validate the adapter-local integrity manifest at ``root``.

    Raises
    ------
        AdapterError: if the manifest is missing or not a JSON object.
    """
    path = root / MANIFEST_FILE
    if not path.is_file():
        raise AdapterError(
            f"no {MANIFEST_FILE} found at '{root}'. The BEAVER raw data is not shipped "
            "with the framework; download it (docs/05, adapter README) into a gitignored "
            f"data root, record version/checksum/splits, or point EAA_BEAVER_DATA_ROOT at it."
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdapterError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AdapterError(f"{path} must contain a JSON object")
    return data


def verify_version(raw: dict[str, Any], expected: str) -> None:
    """Verify the recorded data version against the adapter's pinned version.

    Raises
    ------
        AdapterError: on a version mismatch or a missing version field.
    """
    recorded = raw.get("version")
    if recorded is None:
        raise AdapterError(
            "data manifest has no 'version'; record the BEAVER data-contract version "
            f"(expected '{expected}') to pin the dataset"
        )
    if str(recorded) != str(expected):
        raise AdapterError(
            f"BEAVER data version mismatch: manifest records '{recorded}', "
            f"adapter expects '{expected}'"
        )


def discover_databases(root: Path, raw: dict[str, Any]) -> list[str]:
    """Return the database ids present in the data root.

    Uses the manifest's ``databases`` list when present, otherwise scans the
    root for subdirectories that contain a tables/questions file.
    """
    declared = raw.get("databases")
    if isinstance(declared, list) and declared:
        return [_as_str(name) for name in declared]

    found: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        has_tables = any((child / name).is_file() for name in TABLE_FILES)
        has_questions = any((child / name).is_file() for name in QUESTION_FILES)
        if has_tables or has_questions:
            found.append(child.name)
    return found


def _database_files(root: Path, databases: list[str]) -> list[Path]:
    """Return the resolved data files for the given databases, in stable order.

    Raises
    ------
        AdapterError: if a database directory is missing a tables or questions
            file.
    """
    files: list[Path] = []
    for db_id in databases:
        db_dir = root / db_id
        if not db_dir.is_dir():
            raise AdapterError(f"database directory '{db_dir}' not found")
        tables = next((db_dir / name for name in TABLE_FILES if (db_dir / name).is_file()), None)
        questions = next(
            (db_dir / name for name in QUESTION_FILES if (db_dir / name).is_file()), None
        )
        if tables is None or questions is None:
            raise AdapterError(
                f"database '{db_id}' must contain a tables file "
                f"({', '.join(TABLE_FILES)}) and a questions file "
                f"({', '.join(QUESTION_FILES)})"
            )
        files.append(tables)
        files.append(questions)
    return files


def compute_checksum(root: Path, databases: list[str]) -> str:
    """Compute a deterministic sha256 checksum over the data files.

    The digest covers each resolved tables/questions file in stable order, so
    the recorded ``checksum`` in ``manifest.json`` can be regenerated and
    compared (docs/05 §5 integrity).
    """
    digest = hashlib.sha256()
    for path in _database_files(root, databases):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(path.read_bytes())
        digest.update(b"\x00")
    return digest.hexdigest()


def verify_checksum(root: Path, databases: list[str], recorded: str | None) -> None:
    """Verify the recorded checksum against the data files.

    Raises
    ------
        AdapterError: when the manifest records a checksum that does not match
            the computed digest.
    """
    if recorded is None:
        return
    expected = compute_checksum(root, databases)
    if recorded != expected:
        raise AdapterError(
            f"BEAVER data checksum mismatch: manifest records '{recorded}', "
            f"computed '{expected}' — the raw data or manifest is corrupted"
        )


def build_dataset_manifest(
    root: Path,
    raw: dict[str, Any],
    *,
    databases: list[str],
    dialect: str,
    checksum: str,
    stats: dict[str, Any],
) -> DatasetManifest:
    """Build the core ``DatasetManifest`` contract for the BEAVER adapter."""
    splits = raw.get("splits")
    return DatasetManifest(
        name="beaver",
        version=str(raw.get("version", BEAVER_DATA_VERSION)),
        license=raw.get("license") or BEAVER_LICENSE,
        description=raw.get("description") or BEAVER_DESCRIPTION,
        type_keys=list(BEAVER_TYPE_KEYS),
        source=raw.get("source"),
        splits=list(splits) if isinstance(splits, list) else list(BEAVER_SPLITS),
        citation=raw.get("citation") or BEAVER_CITATION,
        homepage=BEAVER_HOMEPAGE,
        entry_points={"beaver": ENTRY_POINT},
        extra={
            "databases": databases,
            "checksum": checksum,
            "checksum_recorded": raw.get("checksum"),
            "dialect": dialect,
            "data_root": str(root),
            "stats": stats,
        },
    )


def _as_str(value: Any) -> str:
    if not isinstance(value, str):
        raise AdapterError(f"expected a string value, got {type(value).__name__}")
    return value
