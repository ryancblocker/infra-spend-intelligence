"""
Purpose: Generate strategic recommendations from discovery, waste, and contract intelligence outputs.
Inputs: outputs/discovery_output.json, outputs/waste_findings.json, outputs/contract_intelligence_output.json, data/contracts.csv, data/benchmark_rates.csv.
Outputs: JSON file outputs/financial_optimization_output.json with prioritized actions and projected savings.
Assigned Team Member: SOFIA
Dependencies: pathlib, json, pandas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_FILE = OUTPUT_DIR / "financial_optimization_output.json"

DISCOVERY_FILE = OUTPUT_DIR / "discovery_output.json"
WASTE_FILE = OUTPUT_DIR / "waste_findings.json"
CONTRACT_INTEL_FILE = OUTPUT_DIR / "contract_intelligence_output.json"


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"[WARN] Missing optional input: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - demo-safe behavior
        print(f"[WARN] Could not parse {path.name}: {exc}")
        return {}


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"[WARN] Missing optional input: {path}")
        return pd.DataFrame()
    try:
        return pd.read_csv(path, comment="#")
    except Exception as exc:  # pragma: no cover - demo-safe behavior
        print(f"[WARN] Could not parse {path.name}: {exc}")
        return pd.DataFrame()


def _risk_level(estimated_annual_savings: float, issue: str, recommended_action: str) -> str:
    issue_lower = issue.lower()
    if estimated_annual_savings >= 100000 or "termination" in issue_lower:
        return "High"
    if recommended_action in {"Renegotiate", "Cancel"} and estimated_annual_savings >= 30000:
        return "Medium"
    return "Low"


def _confidence_score(finding: dict[str, Any], recommended_action: str) -> float:
    annual = float(finding.get("estimated_annual_savings", 0) or 0)
    category = str(finding.get("category", "")).lower()

    score = 0.55
    if annual >= 50000:
        score += 0.2
    if "underutilization" in category or "inactive" in category:
        score += 0.15
    if "owner_gap" in category:
        score -= 0.2
    if recommended_action == "Keep but monitor":
        score -= 0.1

    return round(max(0.1, min(score, 0.95)), 2)


def _recommended_action(finding: dict[str, Any]) -> str:
    category = str(finding.get("category", "")).lower()
    annual = float(finding.get("estimated_annual_savings", 0) or 0)
    issue = str(finding.get("issue", "")).lower()

    if "owner_gap" in category:
        return "Review with owner"
    if "underutilization" in category and annual >= 40000:
        return "Cancel"
    if "underutilization" in category:
        return "Right-size"
    if "benchmark_variance" in category or "contract" in category or "rate" in issue:
        return "Renegotiate"
    if "inactive" in category and annual >= 12000:
        return "Cancel"
    if annual <= 5000:
        return "Keep but monitor"
    return "Review with owner"


def _business_rationale(finding: dict[str, Any], action: str) -> str:
    asset_id = finding.get("asset_id", "Unknown asset")
    annual = float(finding.get("estimated_annual_savings", 0) or 0)
    issue = finding.get("issue", "No issue provided")
    return (
        f"{asset_id} has issue '{issue}'. Action '{action}' is expected to recover "
        f"approximately ${annual:,.0f} annually while reducing recurring waste."
    )


def run_financial_optimization_agent() -> dict[str, Any]:
    """Build recommendation list from waste findings with demo-friendly business logic."""
    discovery = _safe_read_json(DISCOVERY_FILE)
    waste = _safe_read_json(WASTE_FILE)
    contract_intel = _safe_read_json(CONTRACT_INTEL_FILE)
    contracts_df = _safe_read_csv(DATA_DIR / "contracts.csv")
    benchmark_df = _safe_read_csv(DATA_DIR / "benchmark_rates.csv")

    findings = waste.get("findings", [])
    recommendations: list[dict[str, Any]] = []

    for idx, finding in enumerate(findings, start=1):
        action = _recommended_action(finding)
        annual_savings = float(finding.get("estimated_annual_savings", 0) or 0)
        issue = str(finding.get("issue", ""))

        recommendation = {
            "recommendation_id": f"R-{idx:04d}",
            "related_asset_id": finding.get("asset_id", "UNKNOWN"),
            "category": finding.get("category", "uncategorized"),
            "issue": issue,
            "recommended_action": action,
            "estimated_annual_savings": round(annual_savings, 2),
            "risk_level": _risk_level(annual_savings, issue, action),
            "confidence": _confidence_score(finding, action),
            "business_rationale": _business_rationale(finding, action),
        }
        recommendations.append(recommendation)

    recommendations.sort(
        key=lambda item: (item["estimated_annual_savings"], item["confidence"]),
        reverse=True,
    )

    total_identified_annual_savings = round(
        sum(item["estimated_annual_savings"] for item in recommendations), 2
    )

    output = {
        "metadata": {
            "source": "financial_optimization_agent",
            "baseline_total_annual_spend": discovery.get("total_annual_spend"),
            "contracts_loaded": int(len(contracts_df)) if not contracts_df.empty else 0,
            "benchmark_categories_loaded": int(len(benchmark_df)) if not benchmark_df.empty else 0,
            "contract_intelligence_records": int(len(contract_intel.get("contracts", []))),
        },
        "total_identified_annual_savings": total_identified_annual_savings,
        "recommended_cancellations": sum(1 for item in recommendations if item["recommended_action"] == "Cancel"),
        "recommended_renegotiations": sum(
            1 for item in recommendations if item["recommended_action"] == "Renegotiate"
        ),
        "recommended_right_sizing_actions": sum(
            1 for item in recommendations if item["recommended_action"] == "Right-size"
        ),
        "top_recommendations": recommendations[:10],
        "recommendations": recommendations,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as file_handle:
        json.dump(output, file_handle, indent=2)

    print("[INFO] Financial optimization agent completed successfully.")
    print(f"[INFO] Recommendations generated: {len(recommendations)}")
    print(f"[INFO] Output written: {OUTPUT_FILE}")

    return output


if __name__ == "__main__":
    run_financial_optimization_agent()
