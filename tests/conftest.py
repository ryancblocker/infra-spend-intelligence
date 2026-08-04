from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Unit tests assume offline (deterministic) agent behavior unless a test
# explicitly monkeypatches llm_client. Without this, whether the suite is
# fast and hermetic depends on whether Ollama happens to be installed and
# reachable on the machine running it - tests that never mock get_mode()
# would silently start making real model calls. setdefault() so a
# deliberate `PACT_LLM_MODE=ollama pytest` override still works.
os.environ.setdefault("PACT_LLM_MODE", "offline")

import pytest  # noqa: E402

from app.data.seed_db import build_database  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    """Deterministic (seed=42) synthetic data, so tests are self-contained -
    no need for a pre-existing runtime/pact.db."""
    build_database()
