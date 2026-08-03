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

from app import config  # noqa: E402
from app.data.seed_db import build_database  # noqa: E402
from app.tools import vector_store  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_database(tmp_path_factory):
    """Deterministic (seed=42) synthetic data in a throwaway runtime directory.

    Every path the suite writes to is redirected here first. The upload tests
    insert real contracts rows, and against the developer's runtime/pact.db
    those rows outlived the temp files they described: no manifest entry, no
    document, no Remove button on the manifest-driven dashboard card, and a 404
    from the remove route - but still rendered on /contracts and still counted
    in portfolio totals and renewal risk.

    Redirection works because every reader resolves these through the config
    module at call time (config.DB_PATH, config.VECTOR_STORE_DIR, ...) rather
    than binding the value at import. The one exception is the Chroma client,
    which caches a handle on the directory it first saw, so its cache is
    cleared on both sides of the redirect.
    """
    runtime = tmp_path_factory.mktemp("pact-runtime")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(config, "DB_PATH", runtime / "pact.db")
    monkeypatch.setattr(config, "VECTOR_STORE_DIR", runtime / "vector_store")
    monkeypatch.setattr(config, "UPLOAD_DIR", runtime / "uploads")
    monkeypatch.setattr(config, "UPLOAD_MANIFEST_PATH", runtime / "uploads" / "manifest.json")
    monkeypatch.setattr(config, "EXTRACTION_CACHE_PATH", runtime / "extraction_cache.json")
    monkeypatch.setattr(config, "LLM_LOG_PATH", runtime / "llm_calls.jsonl")

    vector_store._client.cache_clear()
    (runtime / "vector_store").mkdir(parents=True, exist_ok=True)
    (runtime / "uploads").mkdir(parents=True, exist_ok=True)

    build_database()
    try:
        yield
    finally:
        vector_store._client.cache_clear()
        monkeypatch.undo()
