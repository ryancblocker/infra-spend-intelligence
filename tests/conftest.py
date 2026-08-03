from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# PACT_LLM_MODE defaults to "auto", which probes for a running Ollama. That makes
# the suite's result depend on whether a server happens to be up on the developer's
# machine - test_agents.py::test_critic_does_not_flag_well_formed_scenario passes
# with Ollama down and fails with it up, because a small local model flags the
# scenario. Pin to offline so the agent tests are hermetic; test_llm_agents.py
# exercises the LLM paths through a fake injected at the llm_client boundary.
# setdefault, not assignment: an explicit PACT_LLM_MODE=ollama run still works.
#
# Must precede the app import below - config reads this at module scope.
os.environ.setdefault("PACT_LLM_MODE", "offline")

import pytest  # noqa: E402

from app.data.seed_db import build_database  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    """Deterministic (seed=42) synthetic data, so tests are self-contained -
    no need for a pre-existing runtime/pact.db."""
    build_database()
