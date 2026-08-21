"""Synthetic BEAVER-format data for adapter tests.

The framework ships no real BEAVER data; these fixtures mimic the raw layout the
adapter consumes (per-database ``tables.json`` + ``questions.json`` plus the
adapter-local integrity ``manifest.json``). The table records use the ``db#sep#``
keyed, ``primary_key``/``foreign_key`` shape of the MIT distribution; the
question records use the official ``id``/``db``/``sql``/``tables`` shape.

``ENRICHMENT`` / ``build_beaver_metadata`` add the optional enrichment sidecar
(M1.4): the adapter publishes it in the generic ``EnrichmentData`` core-contract
shape, exercising the metadata-ON arm without inventing dataset-specific logic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eaa.datasets.adapters.beaver import manifest as beaver_manifest

DB_ID = "dw"
DATABASES = [DB_ID]

#: Optional enrichment sidecar content for the ``dw`` warehouse (M1.4).
ENRICHMENT: dict[str, Any] = {
    "database_id": "dw",
    "table_descriptions": {
        "building": "Buildings on campus, including their street address and build date.",
        "room": "Rooms inside buildings, with floor area in square meters.",
    },
    "column_semantics": {
        "building": {
            "building_id": {
                "business_term": "building identifier",
                "synonyms": ["bid", "building number"],
                "description": "Unique identifier for a building.",
            },
            "built_date": {
                "business_term": "construction date",
                "description": "Date the building was completed.",
            },
        },
        "room": {
            "room_id": {
                "business_term": "room identifier",
                "synonyms": ["room number"],
                "description": "Unique identifier for a room.",
            },
            "building_id": {
                "business_term": "building identifier",
                "description": "Foreign key to the building that contains the room.",
            },
            "area": {
                "business_term": "floor area",
                "unit": "square meters",
                "domain_values": ["10.00", "25.50", "40.00"],
                "description": "Usable floor area of the room.",
            },
        },
    },
    "relationships": [
        {
            "from_table": "room",
            "from_column": "building_id",
            "to_table": "building",
            "to_column": "building_id",
            "kind": "foreign_key",
            "description": "A building contains many rooms; each room belongs to one building.",
        }
    ],
}

TABLES: dict[str, Any] = {
    "dw#sep#building": {
        "db_id": "dw",
        "table_name_original": "building",
        "column_names_original": ["building_id", "street", "city", "built_date"],
        "column_types": [
            "int NOT NULL",
            "varchar(255) DEFAULT NULL",
            "varchar(255) DEFAULT NULL",
            "date DEFAULT NULL",
        ],
        "primary_key": ["building_id"],
        "foreign_key": [],
    },
    "dw#sep#room": {
        "db_id": "dw",
        "table_name_original": "room",
        "column_names_original": ["room_id", "building_id", "area"],
        "column_types": [
            "int NOT NULL",
            "int NOT NULL",
            "decimal(10,2) DEFAULT NULL",
        ],
        "primary_key": ["room_id"],
        "foreign_key": [
            {
                "column_name": "building_id",
                "referenced_table_name": "dw#sep#building",
                "referenced_column_name": "building_id",
            }
        ],
    },
}

QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "beaver-0001",
        "question": "What is the total area of history department buildings?",
        "db": "dw",
        "sql": (
            "SELECT SUM(r.area) FROM room r JOIN building b "
            "ON r.building_id = b.building_id;"
        ),
        "tables": ["dw#sep#room", "dw#sep#building"],
        "join_keys": [["room.building_id", "building.building_id"]],
        "column_mapping": {
            "total area": ["room.area"],
            "history department": ["building.street"],
        },
        "category": "domain_specific_complex",
        "detailed_category": "domain-specific complex",
        "contains_domain_knowledge": True,
        "split": "dev",
    },
    {
        "id": "beaver-0002",
        "question": "List buildings built before 1950.",
        "db": "dw",
        "sql": "SELECT * FROM building WHERE built_date < '1950-01-01';",
        "tables": ["dw#sep#building"],
        "category": "complex_without_domain_knowledge",
        "split": "dev",
    },
    {
        "id": "beaver-0003",
        "question": "Count rooms per building.",
        "db": "dw",
        "sql": "SELECT building_id, COUNT(*) FROM room GROUP BY building_id;",
        "tables": ["dw#sep#room"],
        "oracle_sql": "SELECT building_id, COUNT(*) FROM room GROUP BY building_id;",
        "category": "domain_specific_with_minimal_complexity",
        "split": "test",
    },
]


def build_beaver_root(
    root: Path,
    *,
    version: str = beaver_manifest.BEAVER_DATA_VERSION,
    splits: tuple[str, ...] = ("dev", "test"),
    default_split: str = "dev",
    databases: list[str] | None = None,
    checksum: str | None = None,
) -> Path:
    """Materialize a synthetic BEAVER data root (tables, questions, manifest)."""
    db_ids = databases or DATABASES
    root.mkdir(parents=True, exist_ok=True)
    for db_id in db_ids:
        db_dir = root / db_id
        db_dir.mkdir(parents=True, exist_ok=True)
        (db_dir / "tables.json").write_text(json.dumps(TABLES), encoding="utf-8")
        (db_dir / "questions.json").write_text(json.dumps(QUESTIONS), encoding="utf-8")

    raw: dict[str, Any] = {
        "name": "beaver",
        "version": version,
        "license": "research-use",
        "citation": beaver_manifest.BEAVER_CITATION,
        "splits": list(splits),
        "default_split": default_split,
        "databases": db_ids,
    }
    if checksum is not None:
        raw["checksum"] = checksum
    else:
        raw["checksum"] = beaver_manifest.compute_checksum(root, db_ids)
    (root / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    return root


def build_beaver_metadata(
    root: Path,
    *,
    databases: list[str] | None = None,
    enrichment: dict[str, Any] | None = None,
) -> Path:
    """Write the enrichment sidecar(s) into an existing BEAVER data root.

    The sidecar is written in the generic ``EnrichmentData`` core-contract shape
    (M1.4, ADR-015); ``enrichment`` defaults to ``{DB_ID: ENRICHMENT}``, and a
    ``None`` value for a database simulates a warehouse without a sidecar.
    """
    if enrichment is None:
        enrichment = {db: ENRICHMENT for db in (databases or DATABASES)}
    for db_id in databases or DATABASES:
        db_dir = root / db_id
        db_dir.mkdir(parents=True, exist_ok=True)
        if enrichment.get(db_id) is None:
            continue
        (db_dir / "enrichment.json").write_text(
            json.dumps(enrichment[db_id]), encoding="utf-8"
        )
    return root
