"""
Purpose: Build a unified infrastructure and contract inventory from all tabular sources.
Inputs: CSV files under data/ (contracts, circuits, licenses, mobile lines, colo contracts, benchmark rates).
Outputs: JSON file outputs/discovery_output.json summarizing inventory counts and annualized spend.
Assigned Team Member: SETH
Dependencies: pathlib, json, pandas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_FILE = OUTPUT_DIR / "discovery_output.json"


def load_csv(name: str) -> pd.DataFrame:
    """Load a CSV dataset from the data directory."""
    return pd.read_csv(DATA_DIR / name, comment="#")


def build_inventory() -> dict:
    """Aggregate inventory and spend metrics across all datasets."""
    contracts = load_csv("contracts.csv")
    circuits = load_csv("circuits.csv")
    licenses = load_csv("licenses.csv")
    mobile_lines = load_csv("mobile_lines.csv")
    colo = load_csv("colo_contracts.csv")

    annual_circuit_spend = float((circuits["monthly_cost"].sum() * 12))
    annual_mobile_spend = float((mobile_lines["monthly_cost"].sum() * 12))
    annual_colo_spend = float((colo["monthly_cost"].sum() * 12))
    annual_contract_spend = float(contracts["annual_cost"].sum())
    annual_license_spend = float(licenses["annual_cost"].sum())

    total_spend = (
        annual_circuit_spend
        + annual_mobile_spend
        + annual_colo_spend
        + annual_contract_spend
        + annual_license_spend
    )

    # TODO(SETH): Extend with site-level and vendor-level rollups.
    return {
        "summary": {
            "total_contracts": int(len(contracts)),
            "total_circuits": int(len(circuits)),
            "total_licenses": int(len(licenses)),
            "total_mobile_lines": int(len(mobile_lines)),
            "total_colo_contracts": int(len(colo)),
            "annual_spend": round(total_spend, 2),
        },
        "annual_spend_breakdown": {
            "contracts": round(annual_contract_spend, 2),
            "circuits": round(annual_circuit_spend, 2),
            "licenses": round(annual_license_spend, 2),
            "mobile_lines": round(annual_mobile_spend, 2),
            "colo": round(annual_colo_spend, 2),
        },
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    inventory = build_inventory()
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2)
    print(f"Discovery output written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
