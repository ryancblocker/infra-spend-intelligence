"""
Unit tests for Demo Mode - it must run fully offline (no network/LLM calls,
regardless of how PACT_LLM_MODE is configured), must restore every
get_mode() reference it patches even when the pipeline raises, and must
always reveal the four fan-out agents in a fixed reading order regardless
of the real (nondeterministic) order they finish in.
"""

from __future__ import annotations

import queue
from itertools import groupby

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

_FAN_OUT_NODES = ("extraction", "waste", "benchmark", "renewal")


def test_demo_pipeline_produces_a_full_run():
    state = run_demo_pipeline()

    summary = state.get("summary")
    assert summary is not None
    assert summary.llm_mode == "offline"

    extracted = state.get("extracted_contracts")
    assert extracted
    assert all(c.extraction_source == "offline" for c in extracted)

    # Real, DB-backed IDs - not placeholder data - so contract detail pages
    # (which look up contract_id against the real seeded database) resolve.
    assert all(c.contract_id.startswith("C-") for c in extracted)


def test_demo_pipeline_restores_get_mode_after_running():
    originals = {module: module.get_mode for module in _PATCHED_MODULES}
    run_demo_pipeline()
    for module in _PATCHED_MODULES:
        assert module.get_mode is originals[module], f"{module.__name__}.get_mode was not restored"


def test_demo_pipeline_emits_events_in_fixed_reading_order():
    """Every node emits a "started" then a "completed" event (see graph.py's
    _announce). Discovery's four workers race for real, so those events
    arrive in whatever order the workers actually finish - on the pipeline
    rail that reads as agents lighting up out of sequence. Demo Mode's
    reordering queue must hold each fan-out worker's events back and
    release every worker's events together, in a fixed order, so the rail
    always fills left-to-right regardless of which worker actually finished
    first underneath."""
    q: "queue.Queue" = queue.Queue()
    run_demo_pipeline(event_queue=q)

    events = []
    while True:
        item = q.get_nowait()
        if item == DONE_SENTINEL:
            break
        events.append(item)

    completed_order = [e.node for e in events if e.status == "completed"]
    assert completed_order == _EXPECTED_NODE_ORDER, (
        f"expected one 'completed' event per node, in this order: {_EXPECTED_NODE_ORDER}, "
        f"got: {completed_order}"
    )

    # Each fan-out worker's own events (started, completed) stay contiguous -
    # no interleaving between workers - and the four workers' event groups
    # appear in the fixed order even though they raced underneath.
    fan_out_nodes_in_order = [n for n, _ in groupby(e.node for e in events if e.node in _FAN_OUT_NODES)]
    assert fan_out_nodes_in_order == list(_FAN_OUT_NODES)


def test_demo_pipeline_has_no_artificial_pacing_without_a_real_queue():
    """Demo Mode reorders events but no longer adds artificial delay itself
    (on-screen pacing is the frontend's job) - calling the pipeline directly
    (as this test, and any other caller without a queue, does) must stay
    fast regardless."""
    import time

    start = time.monotonic()
    run_demo_pipeline(event_queue=None)
    assert time.monotonic() - start < 5.0
