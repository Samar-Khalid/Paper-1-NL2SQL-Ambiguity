"""Test helpers: expose the reusable fixture modules under ``tests/fixtures``."""
from __future__ import annotations

import sys
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))
