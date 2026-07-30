"""
Purpose: Main pipeline runner for Infra Spend Intelligence and callable integration point for the Streamlit dashboard.
Inputs: Agent modules under agents/ and generated JSON files under outputs/.
Outputs: Console execution log and a structured pipeline_summary dictionary for UI rendering.
Assigned Team Member: SOFIA
Dependencies: pathlib, json, importlib, traceback, datetime.
"""

from __future__ import annotations

import importlib
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"


PIPELINE_STEPS = [
    {
        "name": "Discovery Agent",
        "module": "agents.discovery_agent",
        "function": "run_discovery_agent",
        "optional": False,
        "output": "discovery_output.json",
    },
    {
        "name": "Waste Detection Agent",
        "module": "agents.waste_detection_agent",
        "function": "run_waste_detection_agent",
        "optional": False,
        "output": "waste_findings.json",
    },
    {
        "name": "Contract Intelligence Agent",
        "module": "agents.contract_intelligence_agent",
        "function": "run_contract_intelligence_agent",
        "optional": False,
        "output": "contract_intelligence_output.json",
    },
    {
        "name": "Renewal Intelligence Agent",
        "module": "agents.renewal_intelligence_agent",
        "function": "run_renewal_intelligence_agent",
        "optional": True,
        "output": "renewal_intelligence_output.json",
    },
    {
        "name": "Scenario Comparison Agent",
        "module": "agents.scenario_comparison_agent",
        "function": "run_scenario_comparison_agent",
        "optional": True,
        "output": "scenario_comparison_output.json",
    },
    {
        "name": "Financial Optimization Agent",
        "module": "agents.financial_optimization_agent",
        "function": "run_financial_optimization_agent",
        "optional": False,
        "output": "financial_optimization_output.json",
    },
    {
        "name": "Executive Summary Agent",
        "module": "agents.executive_summary_agent",
        "function": "run_executive_summary_agent",
        "optional": True,
        "output": "executive_summary.json",
    },
]


def _safe_load_json(path: Path) -> dict[str, Any] | list[Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_callable(module_name: str, function_name: str) -> Callable[..., Any] | None:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None

    fn = getattr(module, function_name, None)
    if callable(fn):
        return fn
    return None


def run_pipeline() -> dict[str, Any]:
    """
    Runs the full Infra Spend Intelligence agent pipeline.
    Returns a structured dictionary summary for the dashboard.
    """
    print("=" * 48)
    print("Infra Spend Intelligence")
    print("=" * 48)

    agents_run: list[str] = []
    agents_skipped: list[str] = []
    agents_failed: list[str] = []

    for step in PIPELINE_STEPS:
        step_name = str(step["name"])
        module_name = str(step["module"])
        function_name = str(step["function"])
        optional = bool(step["optional"])

        print(f"[STARTED] {step_name}")
        runner = _resolve_callable(module_name, function_name)

        if runner is None:
            if optional:
                message = f"{step_name}: missing module/function ({module_name}.{function_name})"
                print(f"[SKIPPED] {message}")
                agents_skipped.append(message)
                continue

            message = f"{step_name}: missing module/function ({module_name}.{function_name})"
            print(f"[FAILED] {message}")
            agents_failed.append(message)
            continue

        try:
            runner()
            print(f"[COMPLETED] {step_name}")
            agents_run.append(step_name)
        except Exception as exc:  # pragma: no cover - demo-safe behavior
            short_err = f"{step_name}: {exc}"
            print(f"[FAILED] {short_err}")
            print(traceback.format_exc(limit=1).strip())

            if optional:
                agents_skipped.append(f"{short_err} (optional step skipped)")
            else:
                agents_failed.append(short_err)

    output_files_generated = []
    for step in PIPELINE_STEPS:
        output_name = str(step["output"])
        output_path = OUTPUTS_DIR / output_name
        if output_path.exists():
            output_files_generated.append(output_name)

    waste_payload = _safe_load_json(OUTPUTS_DIR / "waste_findings.json")
    financial_payload = _safe_load_json(OUTPUTS_DIR / "financial_optimization_output.json")

    total_identified_annual_savings = None
    if isinstance(financial_payload, dict):
        total_identified_annual_savings = financial_payload.get("total_identified_annual_savings")
    if total_identified_annual_savings in (None, 0) and isinstance(waste_payload, dict):
        total_identified_annual_savings = waste_payload.get("total_potential_annual_savings")

    number_of_findings = None
    if isinstance(waste_payload, dict):
        number_of_findings = waste_payload.get("number_of_findings")

    pipeline_status = "success"
    if agents_failed:
        pipeline_status = "partial_failure"

    pipeline_summary = {
        "pipeline_status": pipeline_status,
        "agents_run": agents_run,
        "agents_skipped": agents_skipped,
        "agents_failed": agents_failed,
        "output_files_generated": output_files_generated,
        "total_identified_annual_savings": total_identified_annual_savings,
        "number_of_findings": number_of_findings,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    print("=" * 48)
    print("Pipeline Summary")
    print("=" * 48)
    print(json.dumps(pipeline_summary, indent=2))

    return pipeline_summary


if __name__ == "__main__":
    summary = run_pipeline()
    print(summary)
