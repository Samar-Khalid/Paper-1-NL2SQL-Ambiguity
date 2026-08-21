"""Run identity: a short, sortable, parseable id for each research run."""
from __future__ import annotations

import datetime
import re
import uuid

_RUN_ID_RE = re.compile(r"^([0-9a-f]{8})-(\d{8}T\d{6}Z)(?:-(.+))?$")


class RunId:
    """A run id of the form ``<hex8>-<YYYYMMDDTHHMMSSZ>[-<tag>]``.

    The leading hex gives collision safety; the UTC timestamp makes runs
    sortable in artifact paths; the optional tag (e.g. ``sweep-1``) gives
    human readability.
    """

    def __init__(self, value: str) -> None:
        match = _RUN_ID_RE.match(value)
        if not match:
            raise ValueError(f"invalid RunId: {value!r}")
        self.value = value
        self.hex8 = match.group(1)
        self.timestamp = match.group(2)
        self.tag = match.group(3)

    def __str__(self) -> str:
        """Return the run id string."""
        return self.value

    def __repr__(self) -> str:
        """Return a developer-friendly representation."""
        return f"RunId({self.value!r})"

    def __eq__(self, other: object) -> bool:
        """Return whether ``other`` is an equal RunId."""
        return isinstance(other, RunId) and self.value == other.value

    def __hash__(self) -> int:
        """Return a hash based on the id value."""
        return hash(self.value)

    @classmethod
    def parse(cls, value: str) -> RunId:
        """Parse a run id string into a ``RunId``."""
        return cls(value)

    @property
    def path_segment(self) -> str:
        """Return the safe path segment for this run id."""
        return self.value


def generate_run_id(tag: str | None = None) -> RunId:
    """Generate a new run id, optionally tagged."""
    hex8 = uuid.uuid4().hex[:8]
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    value = f"{hex8}-{stamp}" + (f"-{tag}" if tag else "")
    return RunId(value)
