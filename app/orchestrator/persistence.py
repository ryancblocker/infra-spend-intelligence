"""
Purpose: Persist every completed pipeline run to disk (not just the latest)
so page loads survive app restarts and past runs can be browsed to see how
spend/savings estimates trended over time.

Each run is its own file under runtime/runs/ - the full payload is ~450KB, so
listing history reads a separate lightweight index (runtime/runs/index.json)
instead of loading every run just to show a table of past summaries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

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

RUNS_DIR = config.RUNS_DIR
INDEX_FILE = RUNS_DIR / "index.json"

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


def _run_file(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.json"


def _read_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_index(entries: list[dict]) -> None:
    INDEX_FILE.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _new_run_id() -> str:
    now = datetime.now(timezone.utc)
    base = now.strftime("%Y%m%d-%H%M%S")
    run_id = base
    suffix = 2
    while _run_file(run_id).exists():
        run_id = f"{base}-{suffix}"
        suffix += 1
    return run_id


def save_run(state: PipelineState) -> str:
    """Writes a new run file and appends its summary to the index. Returns the
    new run_id."""
    config.ensure_runtime_dirs()
    run_id = _new_run_id()
    timestamp = datetime.now(timezone.utc).isoformat()

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

    _run_file(run_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary = state.get("summary")
    entries = _read_index()
    entries.append({
        "run_id": run_id,
        "timestamp": timestamp,
        "llm_mode": summary.llm_mode if summary else "unknown",
        "total_annual_spend": summary.total_annual_spend if summary else 0.0,
        "total_potential_annual_savings": summary.total_potential_annual_savings if summary else 0.0,
        "number_of_findings": summary.number_of_findings if summary else 0,
        "high_risk_contracts": summary.high_risk_contracts if summary else 0,
    })
    _write_index(entries)
    return run_id


def list_runs() -> list[dict]:
    """Lightweight run metadata from the index, newest first."""
    return list(reversed(_read_index()))


def load_run(run_id: str | None = None) -> PipelineState | None:
    """Loads a specific run, or the most recent one if run_id is omitted."""
    if run_id is None:
        entries = _read_index()
        if not entries:
            return None
        run_id = entries[-1]["run_id"]

    run_file = _run_file(run_id)
    if not run_file.exists():
        return None
    try:
        raw = json.loads(run_file.read_text(encoding="utf-8"))
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
