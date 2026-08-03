"""
Purpose: Persist the last completed pipeline run to disk so page loads (and
app restarts) don't require re-running the pipeline to show results.
"""

from __future__ import annotations

import json

from app import config
from app.agents.schemas import (
    CriticFlag,
    DiscoverySummary,
    ExtractedContract,
    Finding,
    PipelineRunSummary,
    RenewalRisk,
    ScenarioResult,
)
from app.orchestrator.state import PipelineState

RUN_FILE = config.RUNTIME_DIR / "last_run.json"

_LIST_FIELDS = {
    "extracted_contracts": ExtractedContract,
    "waste_findings": Finding,
    "benchmark_findings": Finding,
    "renewal_risks": RenewalRisk,
    "scenarios": ScenarioResult,
    "critic_flags": CriticFlag,
}
_SCALAR_FIELDS = {
    "discovery": DiscoverySummary,
    "summary": PipelineRunSummary,
}
_STR_FIELDS = ("benchmark_narrative", "renewal_narrative")


def save_run(state: PipelineState) -> None:
    config.ensure_runtime_dirs()
    payload: dict = {}
    for key, model in _SCALAR_FIELDS.items():
        if key in state:
            payload[key] = state[key].model_dump(mode="json")
    for key, model in _LIST_FIELDS.items():
        if key in state:
            payload[key] = [item.model_dump(mode="json") for item in state[key]]
    for key in _STR_FIELDS:
        if key in state:
            payload[key] = state[key]

    RUN_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear_run() -> None:
    """Delete the persisted run. Idempotent - a missing file is not an error."""
    try:
        RUN_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def load_run() -> PipelineState | None:
    if not RUN_FILE.exists():
        return None
    try:
        raw = json.loads(RUN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None

    state: PipelineState = {}
    for key, model in _SCALAR_FIELDS.items():
        if key in raw:
            state[key] = model.model_validate(raw[key])
    for key, model in _LIST_FIELDS.items():
        if key in raw:
            state[key] = [model.model_validate(item) for item in raw[key]]
    for key in _STR_FIELDS:
        if key in raw:
            state[key] = raw[key]
    return state
