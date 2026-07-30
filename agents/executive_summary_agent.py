"""
Purpose: Generate executive-level business narrative and action summaries from all agent outputs.
Inputs: outputs/discovery_output.json, outputs/waste_findings.json, outputs/renewal_intelligence_output.json, outputs/scenario_comparison_output.json, outputs/top_savings_opportunities.json.
Outputs: JSON file outputs/executive_summary.json with summary, risks, opportunities, actions, and next steps.
Assigned Team Member: SOFIA
Dependencies: pathlib, json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_FILE = OUTPUT_DIR / "executive_summary.json"


def _safe_read_json(path: Path) -> dict[str, Any] | list[Any]:
    if not path.exists():
        print(f"[WARN] Missing optional input: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - demo-safe behavior
        print(f"[WARN] Could not parse {path.name}: {exc}")
        return {}


def run_executive_summary_agent() -> dict[str, Any]:
    """Build executive narrative and concise strategic action plan."""
    discovery = _safe_read_json(OUTPUT_DIR / "discovery_output.json")
    waste = _safe_read_json(OUTPUT_DIR / "waste_findings.json")
    renewal = _safe_read_json(OUTPUT_DIR / "renewal_intelligence_output.json")
    scenario = _safe_read_json(OUTPUT_DIR / "scenario_comparison_output.json")
    savings = _safe_read_json(OUTPUT_DIR / "top_savings_opportunities.json")

    total_spend = float((discovery or {}).get("total_annual_spend", 0) or 0)
    potential_savings = float((waste or {}).get("total_potential_annual_savings", 0) or 0)

    renewal_summary = (renewal or {}).get("summary", {}) if isinstance(renewal, dict) else {}
    high_risk_contracts = int(renewal_summary.get("high_risk_contracts", 0) or 0)

    scenario_summary = (scenario or {}).get("summary", {}) if isinstance(scenario, dict) else {}
    scenario_savings = float(scenario_summary.get("total_projected_savings", 0) or 0)

    top_opps = savings if isinstance(savings, list) else []
    top3 = top_opps[:3]

    savings_pct = (potential_savings / total_spend * 100) if total_spend else 0

    executive_summary_text = (
        f"Infra Spend Intelligence identified ${potential_savings:,.0f} in annual savings opportunities "
        f"against a baseline annual spend of ${total_spend:,.0f}. "
        f"{high_risk_contracts} contracts are currently high renewal risk, and scenario modeling indicates "
        f"up to ${scenario_savings:,.0f} in projected value from prioritized contract decisions. "
        f"Immediate action on top opportunities could reduce recurring spend by approximately {savings_pct:.1f}% annually."
    )

    top_risks = []
    if high_risk_contracts > 0:
        top_risks.append(f"{high_risk_contracts} contracts have HIGH renewal risk and need immediate action.")
    if potential_savings > 0:
        top_risks.append("Underutilized or over-priced services are creating avoidable recurring spend.")
    if not top_risks:
        top_risks.append("No major risks detected; continue monitoring cadence.")

    top_savings_opportunities = [
        {
            "rank": item.get("rank"),
            "recommendation": item.get("recommendation"),
            "asset_id": item.get("asset_id"),
            "annual_savings": item.get("annual_savings"),
            "confidence": item.get("confidence"),
        }
        for item in top3
    ]

    immediate_actions = []
    for item in top3:
        immediate_actions.append(
            f"Execute '{item.get('recommendation', 'Review')}' for {item.get('asset_id', 'Unknown')} "
            f"to target ~${float(item.get('annual_savings', 0) or 0):,.0f} annual savings."
        )
    if not immediate_actions:
        immediate_actions.append("Run savings_opportunity_agent.py to generate prioritized actions.")

    next_steps = [
        "Confirm business owner approvals for top 5 optimization actions.",
        "Launch renegotiation workstream for benchmark-variance services.",
        "Create weekly renewal review for contracts inside 90-day windows.",
        "Track realized vs projected savings in the executive dashboard.",
    ]

    payload = {
        "executive_summary": executive_summary_text,
        "top_risks": top_risks,
        "top_savings_opportunities": top_savings_opportunities,
        "immediate_actions": immediate_actions,
        "recommended_next_steps": next_steps,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2)

    print("[INFO] Executive summary agent completed successfully.")
    print(f"[INFO] Output written: {OUTPUT_FILE}")

    return payload


if __name__ == "__main__":
    run_executive_summary_agent()
