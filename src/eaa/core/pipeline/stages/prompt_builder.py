"""Prompt-building stage: render a generic NL2SQL prompt from task + schema.

Dataset-independent (ADR-004): the prompt carries only the question, the
schema, and generic SQL-writing instructions — never a benchmark or dataset
name. The prompt text is versioned via ``PROMPT_VERSION`` so recorded runs stay
reproducible.

Metadata is handled by the *injected* schema provider (ADR-015): when the
resolved schema is an ``EnrichedSchema`` carrying content, the stage renders the
enriched prompt variant (``ENRICHED_PROMPT_VERSION``) and records it; otherwise
it renders the byte-identical baseline prompt. This stage never imports the
``eaa.metadata`` module.
"""
from __future__ import annotations

from ...contracts.errors import PipelineError
from ...contracts.llm import Message
from ...contracts.runtime import RuntimeContext
from ...contracts.schema import ColumnSchema, ColumnSemantics, DatabaseSchema, EnrichedSchema
from ...contracts.task import TaskEnvelope
from ...interfaces.schema import SchemaProvider
from ..stage import PROMPT_KEY, set_state

#: Version of the generic baseline prompt (ADR-004: prompts are versioned data).
PROMPT_VERSION = "baseline-v1"

#: Version of the generic enriched prompt (metadata OFF/ON experiment: the
#: enriched variant is a distinct, versioned prompt so recorded runs stay
#: reproducible and comparable).
ENRICHED_PROMPT_VERSION = "enriched-v1"

_INSTRUCTIONS = (
    "Translate the natural-language question into a single read-only SQL query "
    "against the schema below. Return only the SQL query, without explanation, "
    "code fences, or a leading marker."
)


def _render_column(column: ColumnSchema) -> str:
    fk = ""
    if column.foreign_key is not None:
        fk = (
            f" -> {column.foreign_key.references_table}."
            f"{column.foreign_key.references_column}"
        )
    return f"{column.name} {column.data_type}{fk}"


def render_schema(
    schema: DatabaseSchema,
    *,
    allowed_tables: list[str] | None = None,
) -> str:
    """Serialize a schema into the prompt body (tables, columns, keys only)."""
    tables = [
        table
        for table in schema.tables
        if allowed_tables is None or table.name in allowed_tables
    ]
    lines: list[str] = []
    for table in tables:
        columns = ", ".join(_render_column(column) for column in table.columns)
        primary = (
            f"  primary key: {', '.join(table.primary_keys)}"
            if table.primary_keys
            else ""
        )
        lines.append(f"TABLE {table.name} ({columns}){primary}")
    return "\n".join(lines)


def _has_semantics(semantics: ColumnSemantics) -> bool:
    """Return whether a column semantics entry carries any content."""
    return bool(
        semantics.business_term
        or semantics.synonyms
        or semantics.unit
        or semantics.domain_values
        or semantics.description
    )


def _render_semantics(semantics: ColumnSemantics) -> str:
    """Render one column's semantics as a compact, key-value line."""
    parts: list[str] = []
    if semantics.business_term:
        parts.append(f"business term '{semantics.business_term}'")
    if semantics.synonyms:
        parts.append(f"synonyms: {', '.join(semantics.synonyms)}")
    if semantics.unit:
        parts.append(f"unit '{semantics.unit}'")
    if semantics.domain_values:
        parts.append(f"domain values: {', '.join(semantics.domain_values)}")
    if semantics.description:
        parts.append(semantics.description)
    return "; ".join(parts)


def _semantics_lines(
    schema: EnrichedSchema, table_names: set[str]
) -> list[str]:
    """Render glossary lines for the tables in scope, preserving order."""
    lines: list[str] = []
    for table_name, columns in schema.column_semantics.items():
        if table_name not in table_names:
            continue
        for column_name in sorted(columns):
            semantics = columns[column_name]
            if _has_semantics(semantics):
                lines.append(
                    f"- {table_name}.{column_name}: {_render_semantics(semantics)}"
                )
    return lines


def _relationship_lines(
    schema: EnrichedSchema, table_names: set[str]
) -> list[str]:
    """Render relationship notes for relationships within the tables in scope."""
    lines: list[str] = []
    for relationship in schema.relationships:
        if (
            relationship.from_table not in table_names
            or relationship.to_table not in table_names
        ):
            continue
        line = (
            f"- {relationship.from_table}.{relationship.from_column} -> "
            f"{relationship.to_table}.{relationship.to_column} "
            f"({relationship.kind})"
        )
        if relationship.description:
            line += f": {relationship.description}"
        lines.append(line)
    return lines


def render_enriched_schema(
    schema: EnrichedSchema,
    *,
    allowed_tables: list[str] | None = None,
) -> str:
    """Serialize an enriched schema: base schema plus glossary and relations.

    Each enrichment section (table descriptions, column semantics,
    relationships) is emitted only when it has content, so an enriched schema
    with sparse metadata still renders cleanly.
    """
    tables = [
        table.name
        for table in schema.tables
        if allowed_tables is None or table.name in allowed_tables
    ]
    table_names = set(tables)
    blocks: list[str] = [
        "Schema:",
        render_schema(schema, allowed_tables=allowed_tables),
    ]
    descriptions = [
        f"- {name}: {schema.table_descriptions[name]}"
        for name in tables
        if name in schema.table_descriptions and schema.table_descriptions[name]
    ]
    if descriptions:
        blocks.append("Table descriptions:\n" + "\n".join(descriptions))
    semantics_lines = _semantics_lines(schema, table_names)
    if semantics_lines:
        blocks.append("Column semantics:\n" + "\n".join(semantics_lines))
    relationship_lines = _relationship_lines(schema, table_names)
    if relationship_lines:
        blocks.append("Relationships:\n" + "\n".join(relationship_lines))
    return "\n\n".join(blocks)


def build_prompt_messages(
    question: str,
    schema: DatabaseSchema,
    *,
    dialect: str | None = None,
    allowed_tables: list[str] | None = None,
) -> list[Message]:
    """Build the system + user message pair for one NL2SQL task."""
    body = render_schema(schema, allowed_tables=allowed_tables)
    dialect_line = f"\nDialect: {dialect}." if dialect else ""
    user = (
        f"{_INSTRUCTIONS}\n\nSchema:{dialect_line}\n{body}"
        f"\n\nQuestion: {question}\n\nSQL:"
    )
    return [
        Message(role="system", content=_INSTRUCTIONS),
        Message(role="user", content=user),
    ]


def build_enriched_prompt_messages(
    question: str,
    schema: EnrichedSchema,
    *,
    dialect: str | None = None,
    allowed_tables: list[str] | None = None,
) -> list[Message]:
    """Build the system + user message pair for an enriched NL2SQL task."""
    body = render_enriched_schema(schema, allowed_tables=allowed_tables)
    dialect_line = f"\nDialect: {dialect}." if dialect else ""
    user = (
        f"{_INSTRUCTIONS}\n\nSchema:{dialect_line}\n{body}"
        f"\n\nQuestion: {question}\n\nSQL:"
    )
    return [
        Message(role="system", content=_INSTRUCTIONS),
        Message(role="user", content=user),
    ]


def prompt_version_for(schema: DatabaseSchema, configured: str) -> str:
    """Return the effective prompt version for ``schema``.

    An ``EnrichedSchema`` with content renders with ``ENRICHED_PROMPT_VERSION``;
    any other schema renders with ``configured`` (the baseline token). This is
    how the metadata OFF/ON experiment keeps distinct, versioned prompts.
    """
    if isinstance(schema, EnrichedSchema) and schema.has_enrichment:
        return ENRICHED_PROMPT_VERSION
    return configured


class PromptBuilderStage:
    """Stage 1: resolve the schema and build the generic prompt messages."""

    name = "prompt_builder"

    def __init__(
        self,
        schema_provider: SchemaProvider,
        *,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self._schema_provider = schema_provider
        self.prompt_version = prompt_version

    def run(self, context: RuntimeContext, task: TaskEnvelope) -> TaskEnvelope:
        """Resolve ``database_id`` -> schema and store the rendered prompt."""
        database_id = getattr(task.payload, "database_id", None)
        if not isinstance(database_id, str):
            raise PipelineError(
                f"task '{task.header.task_id}' has no 'database_id' in its payload"
            )
        allowed = getattr(task.payload, "allowed_tables", None)
        allowed_tables = list(allowed) if isinstance(allowed, list) else None
        schema = self._schema_provider.get_schema(database_id)
        if isinstance(schema, EnrichedSchema) and schema.has_enrichment:
            messages = build_enriched_prompt_messages(
                task.header.question,
                schema,
                dialect=task.header.dialect,
                allowed_tables=allowed_tables,
            )
            prompt_version = ENRICHED_PROMPT_VERSION
            enriched = True
        else:
            messages = build_prompt_messages(
                task.header.question,
                schema,
                dialect=task.header.dialect,
                allowed_tables=allowed_tables,
            )
            prompt_version = self.prompt_version
            enriched = False
        set_state(
            context,
            PROMPT_KEY,
            {
                "messages": [message.model_dump() for message in messages],
                "prompt_version": prompt_version,
                "schema_tables": [table.name for table in schema.tables],
                "metadata_enriched": enriched,
            },
        )
        return task
