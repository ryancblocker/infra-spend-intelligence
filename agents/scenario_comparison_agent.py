"""
Purpose: Compare keep, cancel, and renegotiate scenarios for high-value optimization findings.
Inputs: outputs/financial_optimization_output.json, outputs/waste_findings.json, data/contracts.csv.
Outputs: JSON file outputs/scenario_comparison_output.json with spend outcomes, penalties, break-even periods, and recommendation.
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
SCENARIO_OUTPUT_FILE = OUTPUT_DIR / "scenario_comparison_output.json"

FINANCIAL_FILE = OUTPUT_DIR / "financial_optimization_output.json"
WASTE_FILE = OUTPUT_DIR / "waste_findings.json"
CONTRACTS_FILE = DATA_DIR / "contracts.csv"


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


def _find_monthly_cost(asset_id: str, waste_findings: list[dict[str, Any]]) -> float:
    for finding in waste_findings:
        if str(finding.get("asset_id", "")) == asset_id:
            return float(finding.get("current_monthly_cost", 0) or 0)
    return 0.0


def _termination_penalty_pct(asset_id: str, contracts_df: pd.DataFrame) -> float:
    if contracts_df.empty:
        return 0.10

    match = contracts_df[contracts_df["contract_id"].astype(str).str.upper() == asset_id.upper()]
    if match.empty:
        return 0.10

    fee_pct = float(pd.to_numeric(match.iloc[0].get("termination_fee_pct", 10), errors="coerce") or 10)
    return fee_pct / 100.0


def _best_option(keep_cost: float, cancel_cost: float, renegotiate_cost: float) -> str:
    min_cost = min(keep_cost, cancel_cost, renegotiate_cost)
    if min_cost == renegotiate_cost:
        return "Renegotiate"
    if min_cost == cancel_cost:
        return "Cancel"
    return "Keep"


def run_scenario_comparison_agent() -> dict[str, Any]:
    """Generate scenario economics for high-value optimization findings."""
    financial = _safe_read_json(FINANCIAL_FILE)
    waste_payload = _safe_read_json(WASTE_FILE)
    contracts_df = _safe_read_csv(CONTRACTS_FILE)

    recommendations = financial.get("recommendations", [])
    waste_findings = waste_payload.get("findings", [])

    high_value = [
        rec
        for rec in recommendations
        if float(rec.get("estimated_annual_savings", 0) or 0) >= 50000
        or str(rec.get("risk_level", "")).lower() == "high"
    ]

    scenarios: list[dict[str, Any]] = []
    horizon_months = 36

    for rec in high_value:
        asset_id = str(rec.get("related_asset_id", "UNKNOWN"))
        annual_savings = float(rec.get("estimated_annual_savings", 0) or 0)
        monthly_cost = _find_monthly_cost(asset_id, waste_findings)

        if monthly_cost <= 0:
            monthly_cost = annual_savings / 12 if annual_savings > 0 else 1000

        keep_cost = monthly_cost * horizon_months
        penalty_pct = _termination_penalty_pct(asset_id, contracts_df)
        cancellation_penalties = monthly_cost * 12 * penalty_pct
        cancel_cost = cancellation_penalties
        renegotiate_cost = max(keep_cost * 0.72, keep_cost - (annual_savings * 1.5))

        projected_savings = max(keep_cost - min(cancel_cost, renegotiate_cost), 0)
        monthly_delta = max(keep_cost - min(cancel_cost, renegotiate_cost), 0) / horizon_months
        break_even_period = 0 if monthly_delta <= 0 else round(cancel_cost / monthly_delta, 1)

        recommendation = _best_option(keep_cost, cancel_cost, renegotiate_cost)

        scenarios.append(
            {
                "contract": asset_id,
                "category": rec.get("category", "uncategorized"),
                "issue": rec.get("issue", "No issue provided"),
                "keep_cost": round(keep_cost, 2),
                "cancel_cost": round(cancel_cost, 2),
                "renegotiate_cost": round(renegotiate_cost, 2),
                "total_future_spend": {
                    "keep": round(keep_cost, 2),
                    "cancel": round(cancel_cost, 2),
                    "renegotiate": round(renegotiate_cost, 2),
                },
                "cancellation_penalties": round(cancellation_penalties, 2),
                "break_even_period_months": break_even_period,
                "projected_savings": round(projected_savings, 2),
                "recommendation": recommendation,
            }
        )

    scenarios.sort(key=lambda item: item["projected_savings"], reverse=True)

    payload = {
        "summary": {
            "evaluated_high_value_items": len(scenarios),
            "total_projected_savings": round(
                sum(item["projected_savings"] for item in scenarios), 2
            ),
        },
        "scenario_results": scenarios,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with SCENARIO_OUTPUT_FILE.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2)

    print("[INFO] Scenario comparison agent completed successfully.")
    print(f"[INFO] Scenario rows generated: {len(scenarios)}")
    print(f"[INFO] Output written: {SCENARIO_OUTPUT_FILE}")

    return payload


if __name__ == "__main__":
    run_scenario_comparison_agent()
