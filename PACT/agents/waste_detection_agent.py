"""
Purpose: Identify infrastructure waste patterns across circuits, licenses, and mobile inventory.
Inputs: CSV files under data/ and optional discovery summary from outputs/discovery_output.json.
Outputs: JSON file outputs/waste_findings.json with categorized waste findings and estimated savings.
Assigned Team Member: RYAN
Dependencies: pathlib, json, pandas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = BASE_DIR / "outputs" / "waste_findings.json"


def load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / name, comment="#")


def detect_waste() -> dict:
    circuits = load_csv("circuits.csv")
    licenses = load_csv("licenses.csv")
    mobile = load_csv("mobile_lines.csv")

    underutilized_circuits = circuits[circuits["utilization_pct"] < 25]
    unused_licenses = licenses[(licenses["assigned_licenses"] - licenses["active_users"]) > 100]
    idle_lines = mobile[(mobile["avg_data_gb"] < 0.5) & (mobile["last_30d_voice_mins"] < 5)]

    # TODO(RYAN): Add duplicate service and statistical anomaly detection.
    estimated_savings = float(
        underutilized_circuits["monthly_cost"].sum() * 12 * 0.30
        + unused_licenses["annual_cost"].sum() * 0.20
        + idle_lines["monthly_cost"].sum() * 12 * 0.80
    )

    return {
        "findings": {
            "underutilized_circuits": underutilized_circuits.to_dict(orient="records"),
            "unused_licenses": unused_licenses.to_dict(orient="records"),
            "idle_mobile_lines": idle_lines.to_dict(orient="records"),
        },
        "estimated_annual_savings": round(estimated_savings, 2),
    }


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    results = detect_waste()
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Waste findings written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
