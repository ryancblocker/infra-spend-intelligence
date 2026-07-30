"""
Purpose: Extract high-value renewal and termination terms from synthetic contract text samples.
Inputs: .txt files under contract_texts/.
Outputs: JSON file outputs/contract_intelligence_output.json with structured contract clause fields.
Assigned Team Member: JESSIE
Dependencies: pathlib, json, re.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
TEXT_DIR = BASE_DIR / "contract_texts"
OUTPUT_FILE = BASE_DIR / "outputs" / "contract_intelligence_output.json"


def _extract(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _to_int_days(value: str) -> int | None:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else None


def _risk_level(auto_renew: bool, notice_period_days: int | None, termination_fee: str, annual_escalator: str) -> str:
    score = 0
    if auto_renew:
        score += 2
    if notice_period_days and notice_period_days >= 90:
        score += 2
    fee_pct = _extract(termination_fee, r"(\d+(?:\.\d+)?)")
    if fee_pct and float(fee_pct) >= 15:
        score += 2
    esc_pct = _extract(annual_escalator, r"(\d+(?:\.\d+)?)")
    if esc_pct and float(esc_pct) >= 4:
        score += 1

    if score >= 5:
        return "High"
    if score >= 3:
        return "Medium"
    return "Low"


def parse_contract_file(path: Path) -> dict[str, Any]:
    """Rule-based extraction from semi-structured text contract content."""
    text = path.read_text(encoding="utf-8")

    contract_id = _extract(text, r"Contract ID:\s*(.+)") or path.stem.upper()
    vendor = _extract(text, r"Vendor:\s*(.+)")
    category = _extract(text, r"Category:\s*(.+)")
    renewal_date = _extract(text, r"Renewal Date:\s*(.+)")
    auto_renew_text = _extract(text, r"Auto-Renew:\s*(.+)")
    notice_text = _extract(text, r"Notice Period:\s*(.+)")
    termination_fee = _extract(text, r"Termination Fee:\s*(.+)")
    annual_escalator = _extract(text, r"Annual Escalator:\s*(.+)")
    minimum_commitment = _extract(text, r"Minimum Commitment:\s*(.+)")
    clause_summary = _extract(text, r"Clause Summary:\s*(.+)")

    auto_renew = "yes" in auto_renew_text.lower()
    notice_period_days = _to_int_days(notice_text)
    risk_level = _risk_level(auto_renew, notice_period_days, termination_fee, annual_escalator)

    return {
        "contract_id": contract_id,
        "vendor": vendor,
        "category": category,
        "auto_renew": auto_renew,
        "renewal_date": renewal_date,
        "notice_period_days": notice_period_days,
        "termination_fee": termination_fee,
        "annual_escalator": annual_escalator,
        "minimum_commitment": minimum_commitment,
        "clause_summary": clause_summary,
        "risk_level": risk_level,
        "source_file": path.name,
    }


def run_contract_intelligence_agent() -> dict[str, Any]:
    """Read all contract texts and save extracted structured terms."""
    if not TEXT_DIR.exists():
        print(f"[WARN] Contract text directory is missing: {TEXT_DIR}")
        payload = {"contracts": [], "total_contracts_parsed": 0}
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    contract_files = sorted(TEXT_DIR.glob("contract_*.txt"))
    if not contract_files:
        print("[WARN] No contract text files found matching contract_*.txt")

    parsed_contracts = [parse_contract_file(path) for path in contract_files]

    payload = {
        "total_contracts_parsed": len(parsed_contracts),
        "contracts": parsed_contracts,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as file_handle:
        json.dump(payload, file_handle, indent=2)

    print("[INFO] Contract intelligence agent completed successfully.")
    print(f"[INFO] Contracts parsed: {len(parsed_contracts)}")
    print(f"[INFO] Output written: {OUTPUT_FILE}")

    return payload


if __name__ == "__main__":
    run_contract_intelligence_agent()
