"""
Purpose: Compare keep, terminate, and renegotiate options to quantify spend and savings outcomes.
Inputs: outputs/financial_optimization_output.json and data/contracts.csv.
Outputs: JSON file outputs/scenario_comparison_output.json with scenario totals, savings, fees, and break-even periods.
Assigned Team Member: SOFIA
Dependencies: pathlib, json, pandas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "outputs"
CONTRACTS_FILE = BASE_DIR / "data" / "contracts.csv"
SCENARIO_OUTPUT_FILE = OUTPUT_DIR / "scenario_comparison_output.json"


def compare_scenarios() -> dict:
    contracts = pd.read_csv(CONTRACTS_FILE, comment="#")
    baseline_spend = float(contracts["annual_cost"].sum())

    # TODO(SOFIA): Replace assumptions with contract-specific economic models.
    option_keep = {
        "option": "Keep Contract",
        "total_spend": round(baseline_spend, 2),
        "savings": 0.0,
        "cancellation_fees": 0.0,
        "break_even_months": None,
    }
    option_terminate = {
        "option": "Terminate Contract",
        "total_spend": round(baseline_spend * 0.72, 2),
        "savings": round(baseline_spend * 0.28, 2),
        "cancellation_fees": round(baseline_spend * 0.08, 2),
        "break_even_months": 7,
    }
    option_renegotiate = {
        "option": "Renegotiate Contract",
        "total_spend": round(baseline_spend * 0.82, 2),
        "savings": round(baseline_spend * 0.18, 2),
        "cancellation_fees": 0.0,
        "break_even_months": 4,
    }

    return {"scenarios": [option_keep, option_terminate, option_renegotiate]}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = compare_scenarios()
    with SCENARIO_OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Scenario comparison output written to: {SCENARIO_OUTPUT_FILE}")


if __name__ == "__main__":
    main()
