"""
Purpose: Build a unified infrastructure and contract inventory from all tabular sources.
Inputs: CSV files under data/ (contracts, circuits, licenses, mobile lines, colo contracts, benchmark rates).
Outputs: JSON file outputs/discovery_output.json with spend summaries and asset counts by category.
Assigned Team Member: SETH
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
OUTPUT_FILE = OUTPUT_DIR / "discovery_output.json"

REQUIRED_FILES = {
    "contracts": "contracts.csv",
    "circuits": "circuits.csv",
    "licenses": "licenses.csv",
    "mobile_lines": "mobile_lines.csv",
    "colo_contracts": "colo_contracts.csv",
    "benchmark_rates": "benchmark_rates.csv",
}


def load_csv(name: str) -> pd.DataFrame | None:
    """Load a CSV dataset with friendly warning behavior."""
    csv_path = DATA_DIR / name
    if not csv_path.exists():
        print(f"[WARN] Missing input file: {csv_path}")
        return None

    try:
        return pd.read_csv(csv_path, comment="#")
    except Exception as exc:  # pragma: no cover - demo-safe behavior
        print(f"[WARN] Could not read {csv_path.name}: {exc}")
        return None


def _value_or_zero(df: pd.DataFrame | None, column: str) -> float:
    if df is None or column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def _count_or_zero(df: pd.DataFrame | None) -> int:
    return int(len(df)) if df is not None else 0


def _annual_from_monthly(df: pd.DataFrame | None, monthly_col: str) -> float:
    return _value_or_zero(df, monthly_col) * 12


def run_discovery_agent() -> dict[str, Any]:
    """Run discovery pipeline and return a clean summary payload."""
    datasets = {key: load_csv(filename) for key, filename in REQUIRED_FILES.items()}

    missing = [name for name, df in datasets.items() if df is None]
    if missing:
        print(f"[WARN] Discovery running with missing datasets: {', '.join(missing)}")

    contracts = datasets["contracts"]
    circuits = datasets["circuits"]
    licenses = datasets["licenses"]
    mobile_lines = datasets["mobile_lines"]
    colo_contracts = datasets["colo_contracts"]

    # Annualize monthly datasets so every category uses the same annual basis.
    annual_circuit_spend = _annual_from_monthly(circuits, "monthly_cost")
    annual_mobile_spend = _annual_from_monthly(mobile_lines, "monthly_cost")
    annual_colo_spend = _annual_from_monthly(colo_contracts, "monthly_cost")
    annual_contract_spend = _value_or_zero(contracts, "annual_cost")
    annual_license_spend = _value_or_zero(licenses, "annual_cost")

    spend_by_category = {
        "contracts": round(annual_contract_spend, 2),
        "telecom_circuits": round(annual_circuit_spend, 2),
        "software_licenses": round(annual_license_spend, 2),
        "mobile_lines": round(annual_mobile_spend, 2),
        "colo_contracts": round(annual_colo_spend, 2),
    }

    total_annual_spend = round(sum(spend_by_category.values()), 2)
    total_monthly_spend = round(total_annual_spend / 12, 2)

    asset_count_by_category = {
        "contracts": _count_or_zero(contracts),
        "telecom_circuits": _count_or_zero(circuits),
        "software_license_products": _count_or_zero(licenses),
        "mobile_lines": _count_or_zero(mobile_lines),
        "colo_contracts": _count_or_zero(colo_contracts),
    }

    output = {
        "total_contracts": asset_count_by_category["contracts"],
        "total_circuits": asset_count_by_category["telecom_circuits"],
        "total_licenses": asset_count_by_category["software_license_products"],
        "total_mobile_lines": asset_count_by_category["mobile_lines"],
        "total_colo_contracts": asset_count_by_category["colo_contracts"],
        "total_monthly_spend": total_monthly_spend,
        "total_annual_spend": total_annual_spend,
        "spend_by_category": spend_by_category,
        "asset_count_by_category": asset_count_by_category,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as file_handle:
        json.dump(output, file_handle, indent=2)

    print("[INFO] Discovery agent completed successfully.")
    print(f"[INFO] Output written: {OUTPUT_FILE}")
    print(f"[INFO] Total annual spend: ${total_annual_spend:,.2f}")

    return output


if __name__ == "__main__":
    run_discovery_agent()
