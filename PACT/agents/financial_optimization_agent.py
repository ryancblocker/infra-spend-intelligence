"""
Purpose: Generate strategic keep/cancel/renegotiate/right-size recommendations from all prior agent outputs.
Inputs: outputs/discovery_output.json, outputs/waste_findings.json, outputs/contract_intelligence_output.json, outputs/renewal_intelligence_output.json.
Outputs: JSON file outputs/financial_optimization_output.json with recommendation list and projected savings.
Assigned Team Member: SOFIA
Dependencies: pathlib, json.
"""

from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
FINANCIAL_OUTPUT_FILE = OUTPUT_DIR / "financial_optimization_output.json"


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def optimize() -> dict:
    discovery = read_json(OUTPUT_DIR / "discovery_output.json")
    waste = read_json(OUTPUT_DIR / "waste_findings.json")
    renewal = read_json(OUTPUT_DIR / "renewal_intelligence_output.json")

    estimated_waste_savings = float(waste.get("estimated_annual_savings", 0.0))
    total_spend = float(discovery.get("summary", {}).get("annual_spend", 0.0))

    # TODO(SOFIA): Add weighted scoring model from contract and benchmark dimensions.
    recommendations = [
        {
            "category": "Right-size",
            "action": "Reduce low-utilization circuits by 30% bandwidth tier",
            "impact": "Medium",
        },
        {
            "category": "Cancel",
            "action": "Disconnect idle mobile lines after stakeholder approval",
            "impact": "High",
        },
        {
            "category": "Renegotiate",
            "action": "Target contracts with upcoming renewals and escalation clauses",
            "impact": "High",
        },
    ]

    return {
        "baseline_annual_spend": round(total_spend, 2),
        "projected_annual_savings": round(estimated_waste_savings * 1.15, 2),
        "renewal_contracts_in_scope": len(renewal.get("upcoming_renewals", [])),
        "recommendations": recommendations,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = optimize()
    with FINANCIAL_OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Financial optimization output written to: {FINANCIAL_OUTPUT_FILE}")


if __name__ == "__main__":
    main()
