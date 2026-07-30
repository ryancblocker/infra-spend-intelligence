"""
Purpose: Analyze contract renewal risk windows and generate action-oriented renewal intelligence.
Inputs: data/contracts.csv, outputs/contract_intelligence_output.json, outputs/financial_optimization_output.json.
Outputs: JSON file outputs/renewal_intelligence_output.json with renewal risk groupings and recommended actions.
Assigned Team Member: JESSIE
Dependencies: pathlib, json, pandas, datetime.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_FILE = OUTPUT_DIR / "renewal_intelligence_output.json"

CONTRACTS_FILE = DATA_DIR / "contracts.csv"
CONTRACT_INTEL_FILE = OUTPUT_DIR / "contract_intelligence_output.json"
FINANCIAL_FILE = OUTPUT_DIR / "financial_optimization_output.json"


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        print(f"[WARN] Missing input file: {path}")
        return pd.DataFrame()
    try:
        return pd.read_csv(path, comment="#")
    except Exception as exc:  # pragma: no cover - demo-safe behavior
        print(f"[WARN] Could not parse {path.name}: {exc}")
        return pd.DataFrame()


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        print(f"[WARN] Missing optional input: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - demo-safe behavior
        print(f"[WARN] Could not parse {path.name}: {exc}")
        return {}


def _contract_risk(days_remaining: int, notice_closing: bool, auto_renew: bool, annual_value: float) -> str:
    if days_remaining <= 30 or (notice_closing and auto_renew) or annual_value >= 350000:
        return "HIGH"
    if days_remaining <= 90 or auto_renew:
        return "MEDIUM"
    return "LOW"


def _recommended_action(risk: str, auto_renew: bool, notice_closing: bool) -> str:
    if risk == "HIGH" and notice_closing:
        return "Escalate immediately and issue renewal/termination notice"
    if risk == "HIGH":
        return "Renegotiate"
    if auto_renew:
        return "Review terms and pre-negotiate before notice deadline"
    return "Monitor and schedule review"


def run_renewal_intelligence_agent(reference_date: datetime | None = None) -> dict[str, Any]:
    """Run renewal intelligence analysis and store contract risk output."""
    contracts = _safe_read_csv(CONTRACTS_FILE)
    contract_intel = _safe_read_json(CONTRACT_INTEL_FILE)
    financial = _safe_read_json(FINANCIAL_FILE)

    today = reference_date or datetime.today()

    intel_by_id: dict[str, dict[str, Any]] = {}
    for item in contract_intel.get("contracts", []):
        contract_id = str(item.get("contract_id", "")).strip().upper()
        if contract_id:
            intel_by_id[contract_id] = item

    high_value_assets = {
        str(rec.get("related_asset_id", "")).strip()
        for rec in financial.get("recommendations", [])
        if float(rec.get("estimated_annual_savings", 0) or 0) >= 50000
    }

    renewal_items: list[dict[str, Any]] = []

    if contracts.empty:
        print("[WARN] No contracts available for renewal intelligence.")

    for _, row in contracts.iterrows():
        contract_id = str(row.get("contract_id", "")).strip().upper()
        vendor = str(row.get("vendor", "Unknown Vendor"))

        try:
            renewal_date = datetime.strptime(str(row.get("end_date", "")), "%Y-%m-%d")
        except ValueError:
            print(f"[WARN] Contract {contract_id} has invalid end_date. Skipping.")
            continue

        notice_days = int(pd.to_numeric(row.get("notice_days", 0), errors="coerce") or 0)
        notice_deadline = renewal_date - timedelta(days=notice_days)
        days_remaining = (renewal_date - today).days
        days_to_notice_deadline = (notice_deadline - today).days

        row_auto_renew = str(row.get("auto_renew", "No")).strip().lower() == "yes"
        intel_auto_renew = bool(intel_by_id.get(contract_id, {}).get("auto_renew", False))
        auto_renew = row_auto_renew or intel_auto_renew

        annual_cost = float(pd.to_numeric(row.get("annual_cost", 0), errors="coerce") or 0)
        notice_closing = 0 <= days_to_notice_deadline <= 30
        risk = _contract_risk(days_remaining, notice_closing, auto_renew, annual_cost)

        if days_remaining <= 90 or auto_renew or notice_closing or contract_id in high_value_assets:
            renewal_items.append(
                {
                    "contract": f"{vendor} {row.get('service_type', 'Service')}",
                    "contract_id": contract_id,
                    "renewal_date": renewal_date.strftime("%Y-%m-%d"),
                    "notice_deadline": notice_deadline.strftime("%Y-%m-%d"),
                    "days_remaining": days_remaining,
                    "days_to_notice_deadline": days_to_notice_deadline,
                    "auto_renew": auto_renew,
                    "notice_window_closing": notice_closing,
                    "risk": risk,
                    "recommended_action": _recommended_action(risk, auto_renew, notice_closing),
                    "annual_cost": round(annual_cost, 2),
                }
            )

    renewals_30 = [item for item in renewal_items if item["days_remaining"] <= 30]
    renewals_60 = [item for item in renewal_items if item["days_remaining"] <= 60]
    renewals_90 = [item for item in renewal_items if item["days_remaining"] <= 90]
    auto_renew_contracts = [item for item in renewal_items if item["auto_renew"]]
    closing_notice_windows = [item for item in renewal_items if item["notice_window_closing"]]

    payload = {
        "reference_date": today.strftime("%Y-%m-%d"),
        "summary": {
            "contracts_renewing_within_30_days": len(renewals_30),
            "contracts_renewing_within_60_days": len(renewals_60),
            "contracts_renewing_within_90_days": len(renewals_90),
            "contracts_with_auto_renew": len(auto_renew_contracts),
            "contracts_with_notice_windows_closing": len(closing_notice_windows),
            "high_risk_contracts": len([item for item in renewal_items if item["risk"] == "HIGH"]),
        },
        "renewal_risks": sorted(renewal_items, key=lambda item: item["days_remaining"]),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2)

    print("[INFO] Renewal intelligence agent completed successfully.")
    print(f"[INFO] Contracts flagged: {len(renewal_items)}")
    print(f"[INFO] Output written: {OUTPUT_FILE}")

    return payload


if __name__ == "__main__":
    run_renewal_intelligence_agent()
