"""
Purpose: Convert multi-agent findings into ranked, executive-friendly savings opportunities.
Inputs: outputs/discovery_output.json, outputs/waste_findings.json, outputs/financial_optimization_output.json, outputs/scenario_comparison_output.json, outputs/renewal_intelligence_output.json.
Outputs: JSON file outputs/top_savings_opportunities.json with ranked recommendations and confidence ratings.
Assigned Team Member: SOFIA
Dependencies: pathlib, json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_FILE = OUTPUT_DIR / "top_savings_opportunities.json"


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"[WARN] Missing optional input: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - demo-safe behavior
        print(f"[WARN] Could not parse {path.name}: {exc}")
        return {}


def _confidence_label(confidence_score: float, risk_level: str) -> str:
    if confidence_score >= 0.8:
        return "High"
    if confidence_score >= 0.6:
        return "Medium"
    if risk_level.upper() == "HIGH":
        return "Medium"
    return "Low"


def run_savings_opportunity_agent() -> list[dict[str, Any]]:
    """Build a ranked list of top savings opportunities from existing outputs."""
    financial = _safe_read_json(OUTPUT_DIR / "financial_optimization_output.json")
    scenario = _safe_read_json(OUTPUT_DIR / "scenario_comparison_output.json")
    renewal = _safe_read_json(OUTPUT_DIR / "renewal_intelligence_output.json")

    scenario_by_asset = {
        str(item.get("contract", "")): item
        for item in scenario.get("scenario_results", [])
    }

    urgent_renewal_assets = {
        str(item.get("contract_id", ""))
        for item in renewal.get("renewal_risks", [])
        if str(item.get("risk", "")).upper() == "HIGH"
    }

    opportunities: list[dict[str, Any]] = []

    for rec in financial.get("recommendations", []):
        asset_id = str(rec.get("related_asset_id", "UNKNOWN"))
        annual_savings = float(rec.get("estimated_annual_savings", 0) or 0)
        confidence_score = float(rec.get("confidence", 0.5) or 0.5)
        risk_level = str(rec.get("risk_level", "LOW"))

        scenario_item = scenario_by_asset.get(asset_id, {})
        scenario_savings = float(scenario_item.get("projected_savings", 0) or 0)

        # Blend optimization and scenario math to make the ranking more decision-grade.
        weighted_savings = round((annual_savings * 0.7) + (scenario_savings * 0.3), 2)

        if asset_id in urgent_renewal_assets:
            weighted_savings = round(weighted_savings * 1.1, 2)

        opportunities.append(
            {
                "related_asset_id": asset_id,
                "recommendation": str(rec.get("recommended_action", "Review with owner")),
                "annual_savings": weighted_savings,
                "confidence": _confidence_label(confidence_score, risk_level),
                "rationale": rec.get("business_rationale", "No rationale provided."),
            }
        )

    opportunities.sort(key=lambda item: item["annual_savings"], reverse=True)

    ranked = []
    for idx, item in enumerate(opportunities[:15], start=1):
        ranked.append(
            {
                "rank": idx,
                "recommendation": item["recommendation"],
                "asset_id": item["related_asset_id"],
                "annual_savings": item["annual_savings"],
                "confidence": item["confidence"],
                "rationale": item["rationale"],
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as file_handle:
        json.dump(ranked, file_handle, indent=2)

    print("[INFO] Savings opportunity agent completed successfully.")
    print(f"[INFO] Top opportunities generated: {len(ranked)}")
    print(f"[INFO] Output written: {OUTPUT_FILE}")

    return ranked


if __name__ == "__main__":
    run_savings_opportunity_agent()
