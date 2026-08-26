"""
Purpose: Demo Mode - forces every LLM-backed agent onto its offline
deterministic path for one run, regardless of how PACT_LLM_MODE/Ollama is
configured, so it's always fast and reproducible for a walkthrough. A real
run with Ollama configured can take minutes; this makes it near-instant.

On-screen pacing (giving each event a beat to render) is the frontend's
job now (MIN_DWELL_MS in pipelineRunner(), app/static/js/app.js) and
applies to every run, not just a demo one. What pacing alone can't fix:
Discovery's four workers (extraction/waste/benchmark/renewal) genuinely
run concurrently, so graph.stream() yields their "started"/"completed"
events in whichever order they actually finish - correct for a real run,
but on the pipeline rail it reads as agents lighting up out of sequence.
_ReorderedQueue holds each fan-out worker's events until all four have
fully finished, then releases every worker's events in a fixed reading
order, so Demo Mode's rail always fills left-to-right.
"""

from __future__ import annotations

import queue as queue_module
from contextlib import contextmanager

from app.agents import benchmark, critic, extraction, narrator, optimization, renewal
from app.orchestrator.graph import run_pipeline
from app.orchestrator.state import PipelineState

# Every one of these modules did `from app.tools.llm_client import get_mode`,
# so each holds its own reference to that function object - patching
# app.tools.llm_client.get_mode would not reach any of them (Python looks up
# a plain name where it's used, not where it's defined). Each module's own
# reference is swapped instead.
_PATCH_TARGETS = (extraction, benchmark, renewal, optimization, critic, narrator)

# The four agents Discovery fans out to (see app/orchestrator/graph.py) -
# the ones whose relative event order isn't guaranteed.
_FAN_OUT_NODES = ("extraction", "waste", "benchmark", "renewal")


@contextmanager
def _forced_offline_mode():
    """Force every LLM-backed agent onto its offline deterministic path for
    the duration of the block, then restore the originals unconditionally.
    Safe under the app's single-run lock (only one pipeline - real or demo -
    ever runs at a time) and does not touch the real get_mode() cache that
    concurrent requests such as /api/ask rely on.
    """
    originals = {module: module.get_mode for module in _PATCH_TARGETS}
    try:
        for module in _PATCH_TARGETS:
            module.get_mode = lambda: "offline"
        yield
    finally:
        for module, original in originals.items():
            module.get_mode = original


class _ReorderedQueue:
    """Wraps the real event queue so the four fan-out workers' events are
    held back and released together, in a fixed order, instead of in their
    real (nondeterministic) finish order. Every other node's events pass
    straight through untouched - this changes delivery order only, never
    what gets emitted, timing, or content."""

    def __init__(self, inner: "queue_module.Queue | None") -> None:
        self._inner = inner
        self._pending: dict[str, list] = {}

    def put(self, item) -> None:
        if self._inner is None:
            return
        if isinstance(item, str):  # DONE_SENTINEL
            self._flush_fan_out()  # don't drop stragglers if the run errored mid-fan-out
            self._inner.put(item)
            return

        if item.node not in _FAN_OUT_NODES:
            self._inner.put(item)
            return

        self._pending.setdefault(item.node, []).append(item)
        all_finished = len(self._pending) == len(_FAN_OUT_NODES) and all(
            any(e.status == "completed" for e in events) for events in self._pending.values()
        )
        if all_finished:
            self._flush_fan_out()

    def _flush_fan_out(self) -> None:
        for node in _FAN_OUT_NODES:
            for event in self._pending.pop(node, []):
                self._inner.put(event)


def run_demo_pipeline(event_queue: "queue_module.Queue | None" = None) -> PipelineState:
    """Same return shape and event contract as run_pipeline() - callers (the
    /api/run route, persistence) don't need to know a run was a demo run."""
    reordered = _ReorderedQueue(event_queue)
    with _forced_offline_mode():
        return run_pipeline(reordered)  # type: ignore[arg-type]
