"""
Unit tests for demo mode - it must run fully offline (no network/LLM calls,
regardless of how PACT_LLM_MODE is configured), must label its output so a
demo run can never be mistaken for a real one, and must restore every
get_mode() reference it patches even when the pipeline raises.
"""

from __future__ import annotations

import queue

from app.agents import benchmark, critic, extraction, narrator, optimization, renewal
from app.orchestrator.demo import run_demo_pipeline
from app.orchestrator.events import DONE_SENTINEL

_PATCHED_MODULES = (extraction, benchmark, renewal, optimization, critic, narrator)

# The order the pipeline rail displays nodes in (app/static/js/app.js
# nodeOrder) - discovery's four workers run concurrently for real, but the
# rail should still always fill in this reading order during a demo run.
_EXPECTED_NODE_ORDER = [
    "discovery", "extraction", "waste", "benchmark", "renewal",
    "optimization", "critic", "narrator",
]


def test_demo_pipeline_produces_a_full_labeled_run():
    state = run_demo_pipeline()

    summary = state.get("summary")
    assert summary is not None
    assert summary.llm_mode == "demo"

    extracted = state.get("extracted_contracts")
    assert extracted
    assert all(c.extraction_source == "demo" for c in extracted)

    scenarios = state.get("scenarios")
    assert scenarios
    assert all(s.source == "demo" for s in scenarios)

    # Real, DB-backed IDs - not placeholder data - so contract detail pages
    # (which look up contract_id against the real seeded database) resolve.
    assert all(c.contract_id.startswith("C-") for c in extracted)


def test_demo_pipeline_restores_get_mode_after_running():
    originals = {module: module.get_mode for module in _PATCHED_MODULES}
    run_demo_pipeline()
    for module in _PATCHED_MODULES:
        assert module.get_mode is originals[module], f"{module.__name__}.get_mode was not restored"


def test_demo_pipeline_has_no_artificial_pacing_without_a_real_queue():
    """Pacing only delays events handed to a real SSE queue - calling the
    pipeline directly (as this test, and any other caller without a queue,
    does) must stay fast."""
    import time

    start = time.monotonic()
    run_demo_pipeline(event_queue=None)
    assert time.monotonic() - start < 5.0


def test_demo_pipeline_emits_events_in_fixed_reading_order():
    """Discovery's four workers (extraction/waste/benchmark/renewal) race for
    real, so graph.stream() yields their completion events in whatever order
    they actually finish. On the pipeline rail that reads as agents lighting
    up out of sequence. Demo mode's pacing queue must hold them back and
    release them in a fixed order so the rail always fills left-to-right,
    regardless of which worker actually finished first underneath."""
    q: "queue.Queue" = queue.Queue()
    run_demo_pipeline(event_queue=q)

    nodes = []
    while True:
        item = q.get_nowait()
        if item == DONE_SENTINEL:
            break
        nodes.append(item.node)

    assert nodes == _EXPECTED_NODE_ORDER
