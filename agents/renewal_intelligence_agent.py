"""
Purpose: Detect renewal risk windows, notice deadlines, and review actions from contract data.
Inputs: data/contracts.csv and optional parsed contract clause hints from contract_texts/.
Outputs: JSON file outputs/renewal_intelligence_output.json with upcoming renewal risks and actions.
Assigned Team Member: JESSIE
Dependencies: pathlib, json, pandas, datetime.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
CONTRACTS_FILE = BASE_DIR / "data" / "contracts.csv"
OUTPUT_FILE = BASE_DIR / "outputs" / "renewal_intelligence_output.json"


def build_renewal_view(reference_date: datetime | None = None) -> dict:
    contracts = pd.read_csv(CONTRACTS_FILE, comment="#")
    today = reference_date or datetime.today()

    risks = []
    for _, row in contracts.iterrows():
        end_date = datetime.strptime(str(row["end_date"]), "%Y-%m-%d")
        notice_days = int(row["notice_days"])
        notice_deadline = end_date - timedelta(days=notice_days)
        days_to_end = (end_date - today).days

        if days_to_end <= 365:
            # TODO(JESSIE): Add confidence score and clause-linked rationale.
            risks.append(
                {
                    "contract_id": row["contract_id"],
                    "vendor": row["vendor"],
                    "end_date": end_date.strftime("%Y-%m-%d"),
                    "notice_deadline": notice_deadline.strftime("%Y-%m-%d"),
                    "auto_renew": row["auto_renew"],
                    "termination_fee_pct": row["termination_fee_pct"],
                    "recommended_action": "Initiate review within 30 days",
                }
            )

    return {"upcoming_renewals": risks, "reference_date": today.strftime("%Y-%m-%d")}


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = build_renewal_view()
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"Renewal intelligence output written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
