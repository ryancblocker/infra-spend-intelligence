"""
Purpose: Demo-mode pipeline run for recordings and walkthroughs.

A full real run can take on the order of tens of hours end-to-end (extraction
alone makes an LLM call per contract per retrieval iteration, and optimization
adds up to fifteen more for high-value findings) - far too slow to sit in
front of while recording a demo. This module runs the *exact same* eight-agent
LangGraph pipeline, forced into the app's existing offline deterministic mode
for the duration of one run only, so it completes in a few seconds with zero
LLM calls (no local Ollama, no Anthropic API) regardless of how this machine
is configured - and paces the progress events emitted to the UI so the
pipeline visualization is still watchable instead of finishing before a
screen recording can even start.

This is deliberately a thin wrapper around run_pipeline(), not a parallel
implementation with its own made-up numbers: every figure a demo run shows
is produced by the same discovery/waste/benchmark/renewal/extraction/
optimization/critic/narrator logic a real run uses, over the real seeded
portfolio, via the offline fallback each of those agents already ships (the
same one that runs when no LLM is configured at all - see docs/setup.md).
A demo run is only relabeled ("offline" -> "demo") on the way out so it's
never mistaken for a real analysis in the UI or in runtime/runs/ history.
"""

from __future__ import annotations

import queue as queue_module
import random
import time
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

# How long each node's completion appears to take on screen. Randomized
# within a tight band so the pipeline rail doesn't animate in obviously
# identical lockstep, without ever feeling like a real wait.
_MIN_NODE_SECONDS = 0.5
_MAX_NODE_SECONDS = 1.3


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


# Discovery fans out to these four workers, which genuinely run concurrently
# (see graph.py's Orchestrator-Worker wiring) - graph.stream() yields their
# "completed" events in whichever order they actually finish. That's correct
# for a real run, but on the pipeline rail it looks like the agents finish
# out of sequence (e.g. Waste lighting up green before Extraction). This
# fixed reading order is only for how demo mode *reveals* them, not for
# execution.
_FAN_OUT_NODES = ("extraction", "waste", "benchmark", "renewal")


class _PacedQueue:
    """Wraps the real event queue so every AgentEvent this pipeline emits gets
    a beat to breathe on screen before the next one lands. Purely a delivery
    delay - it changes nothing about what gets emitted, and adds no delay at
    all when there is no real queue behind it (e.g. a pipeline run invoked
    directly, without the SSE route). The one exception is order: the four
    fan-out workers' events are held back and released in a fixed sequence
    (see _FAN_OUT_NODES) instead of in their real, nondeterministic finish
    order, so the pipeline rail always fills left-to-right on screen."""

    def __init__(self, inner: "queue_module.Queue | None") -> None:
        self._inner = inner
        self._pending_fan_out: dict[str, object] = {}

    def put(self, item) -> None:
        if self._inner is None:
            return
        if isinstance(item, str):  # DONE_SENTINEL
            self._flush_fan_out()  # don't drop a straggler if the run errored mid-fan-out
            self._inner.put(item)
            return
        if item.node == "extraction" and "offline" in item.detail:
            # The real extraction agent's detail text names its own source
            # ("... parsed (offline)"); that's accurate underneath, but a
            # viewer watching Demo Mode shouldn't see that word go by
            # unexplained.
            item = item.model_copy(update={"detail": item.detail.replace("offline", "demo")})

        if item.node in _FAN_OUT_NODES:
            self._pending_fan_out[item.node] = item
            if len(self._pending_fan_out) == len(_FAN_OUT_NODES):
                self._flush_fan_out()
            return

        time.sleep(random.uniform(_MIN_NODE_SECONDS, _MAX_NODE_SECONDS))
        self._inner.put(item)

    def _flush_fan_out(self) -> None:
        for node in _FAN_OUT_NODES:
            event = self._pending_fan_out.pop(node, None)
            if event is None:
                continue
            time.sleep(random.uniform(_MIN_NODE_SECONDS, _MAX_NODE_SECONDS))
            self._inner.put(event)


def _relabel_as_demo(state: PipelineState) -> PipelineState:
    """The run itself is real offline-mode output; this just makes sure it's
    unmistakably labeled as a demo everywhere the UI shows provenance, so it's
    never confused with a genuine degraded (LLM-configured-but-offline) run."""
    summary = state.get("summary")
    if summary is not None:
        state["summary"] = summary.model_copy(update={"llm_mode": "demo"})

    extracted = state.get("extracted_contracts")
    if extracted:
        state["extracted_contracts"] = [
            c.model_copy(update={"extraction_source": "demo"}) for c in extracted
        ]

    scenarios = state.get("scenarios")
    if scenarios:
        state["scenarios"] = [s.model_copy(update={"source": "demo"}) for s in scenarios]

    return state


def run_demo_pipeline(event_queue: "queue_module.Queue | None" = None) -> PipelineState:
    """Same return shape and event contract as run_pipeline() - callers (the
    /api/run route, persistence) don't need to know a run was a demo except
    via the labels _relabel_as_demo applies to the result."""
    paced = _PacedQueue(event_queue)
    with _forced_offline_mode():
        state = run_pipeline(paced)  # type: ignore[arg-type]
    return _relabel_as_demo(state)
