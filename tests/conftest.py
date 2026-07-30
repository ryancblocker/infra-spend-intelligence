from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.data.seed_db import build_database  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    """Deterministic (seed=42) synthetic data, so tests are self-contained -
    no need for a pre-existing runtime/pact.db."""
    build_database()
