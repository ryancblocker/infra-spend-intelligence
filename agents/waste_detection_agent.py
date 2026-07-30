"""
Purpose: Identify infrastructure waste patterns across circuits, licenses, mobile, and contract ownership data.
Inputs: CSV files under data/ and optional summary from outputs/discovery_output.json.
Outputs: JSON file outputs/waste_findings.json with structured findings and estimated savings.
Assigned Team Member: RYAN
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
OUTPUT_FILE = OUTPUT_DIR / "waste_findings.json"
DISCOVERY_FILE = OUTPUT_DIR / "discovery_output.json"


def _safe_read_csv(file_name: str) -> pd.DataFrame:
    path = DATA_DIR / file_name
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
        print(f"[WARN] Optional file not found: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - demo-safe behavior
        print(f"[WARN] Could not parse {path.name}: {exc}")
        return {}


def _benchmark_lookup(benchmarks: pd.DataFrame) -> dict[str, float]:
    if benchmarks.empty or "category" not in benchmarks.columns:
        return {}

    rate_map: dict[str, float] = {}
    for _, row in benchmarks.iterrows():
        category = str(row.get("category", "")).strip().lower()
        rate = float(pd.to_numeric(row.get("benchmark_rate", 0), errors="coerce") or 0)
        if category:
            rate_map[category] = rate
    return rate_map


def _priority(annual_savings: float, category: str) -> str:
    if annual_savings > 50000 or "contract" in category:
        return "High"
    if annual_savings > 15000:
        return "Medium"
    return "Low"


def _build_finding(
    finding_id: int,
    category: str,
    asset_id: str,
    issue: str,
    current_monthly_cost: float,
    estimated_monthly_savings: float,
    recommended_action: str,
) -> dict[str, Any]:
    annual_savings = round(estimated_monthly_savings * 12, 2)
    return {
        "finding_id": f"W-{finding_id:04d}",
        "category": category,
        "asset_id": asset_id,
        "issue": issue,
        "current_monthly_cost": round(current_monthly_cost, 2),
        "estimated_monthly_savings": round(estimated_monthly_savings, 2),
        "estimated_annual_savings": annual_savings,
        "recommended_action": recommended_action,
        "priority": _priority(annual_savings, category),
    }


def run_waste_detection_agent() -> dict[str, Any]:
    """Run waste detection rules and persist findings to JSON."""
    circuits = _safe_read_csv("circuits.csv")
    licenses = _safe_read_csv("licenses.csv")
    mobile = _safe_read_csv("mobile_lines.csv")
    contracts = _safe_read_csv("contracts.csv")
    colo = _safe_read_csv("colo_contracts.csv")
    benchmarks = _safe_read_csv("benchmark_rates.csv")
    discovery = _safe_read_json(DISCOVERY_FILE)

    benchmark_rates = _benchmark_lookup(benchmarks)
    findings: list[dict[str, Any]] = []
    finding_counter = 1

    if not circuits.empty:
        low_util = circuits[pd.to_numeric(circuits.get("utilization_pct"), errors="coerce") < 25]
        for _, row in low_util.iterrows():
            monthly_cost = float(row.get("monthly_cost", 0) or 0)
            findings.append(
                _build_finding(
                    finding_counter,
                    "telecom_underutilization",
                    str(row.get("circuit_id", "UNKNOWN")),
                    f"Circuit utilization is {row.get('utilization_pct', 'N/A')}% (below 25%).",
                    monthly_cost,
                    monthly_cost * 0.75,
                    "Right-size or disconnect low-utilization circuit.",
                )
            )
            finding_counter += 1

    if not mobile.empty:
        no_user = mobile[mobile.get("assigned_user", "").fillna("").astype(str).str.strip() == ""]
        for _, row in no_user.iterrows():
            monthly_cost = float(row.get("monthly_cost", 0) or 0)
            findings.append(
                _build_finding(
                    finding_counter,
                    "mobile_unassigned",
                    str(row.get("line_id", "UNKNOWN")),
                    "Mobile line has no assigned user.",
                    monthly_cost,
                    monthly_cost,
                    "Cancel line or assign to an active employee.",
                )
            )
            finding_counter += 1

        inactive = mobile[pd.to_numeric(mobile.get("last_activity_days"), errors="coerce") > 90]
        for _, row in inactive.iterrows():
            monthly_cost = float(row.get("monthly_cost", 0) or 0)
            findings.append(
                _build_finding(
                    finding_counter,
                    "mobile_inactive",
                    str(row.get("line_id", "UNKNOWN")),
                    f"No activity for {row.get('last_activity_days', 'N/A')} days.",
                    monthly_cost,
                    monthly_cost,
                    "Suspend or cancel inactive mobile line.",
                )
            )
            finding_counter += 1

    if not licenses.empty:
        active_ratio = (
            pd.to_numeric(licenses.get("active_users"), errors="coerce").fillna(0)
            / pd.to_numeric(licenses.get("purchased_count"), errors="coerce").replace(0, pd.NA)
        ).fillna(0)
        underused = licenses[active_ratio < 0.60]
        for idx, row in underused.iterrows():
            purchased = int(pd.to_numeric(row.get("purchased_count"), errors="coerce") or 0)
            active_users = int(pd.to_numeric(row.get("active_users"), errors="coerce") or 0)
            unused_count = max(purchased - active_users, 0)
            unit_monthly = float(pd.to_numeric(row.get("unit_monthly_cost"), errors="coerce") or 0)
            monthly_cost = float(pd.to_numeric(row.get("monthly_cost"), errors="coerce") or 0)

            findings.append(
                _build_finding(
                    finding_counter,
                    "license_underutilization",
                    str(row.get("license_id", f"LICENSE-{idx}")),
                    f"Active usage ratio is {active_ratio.loc[idx]:.2%} (below 60%).",
                    monthly_cost,
                    unused_count * unit_monthly,
                    "Reduce purchased license count at next true-up.",
                )
            )
            finding_counter += 1

    # Missing-owner checks across datasets (review-required findings).
    owner_specs = [
        (contracts, "contract_id", "contract_owner_gap", "Contract missing owner."),
        (circuits, "circuit_id", "service_owner_gap", "Circuit missing owner."),
        (licenses, "license_id", "service_owner_gap", "License product missing owner."),
        (mobile, "line_id", "service_owner_gap", "Mobile line missing owner."),
        (colo, "colo_id", "service_owner_gap", "Colo service missing owner."),
    ]
    for dataset, id_col, category, message in owner_specs:
        if dataset.empty or "owner" not in dataset.columns:
            continue
        missing_owner = dataset[dataset["owner"].fillna("").astype(str).str.strip() == ""]
        for _, row in missing_owner.iterrows():
            monthly_cost = float(pd.to_numeric(row.get("monthly_cost"), errors="coerce") or 0)
            findings.append(
                _build_finding(
                    finding_counter,
                    category,
                    str(row.get(id_col, "UNKNOWN")),
                    message,
                    monthly_cost,
                    0.0,
                    "Review with owner and assign accountable manager.",
                )
            )
            finding_counter += 1

    # Benchmark checks (cost above benchmark).
    telecom_rate = benchmark_rates.get("telecom_circuit", 0.0)
    if telecom_rate and not circuits.empty:
        for _, row in circuits.iterrows():
            bandwidth = float(pd.to_numeric(row.get("bandwidth_mbps"), errors="coerce") or 0)
            expected = bandwidth * telecom_rate
            current = float(pd.to_numeric(row.get("monthly_cost"), errors="coerce") or 0)
            if current > expected and expected > 0:
                findings.append(
                    _build_finding(
                        finding_counter,
                        "benchmark_variance",
                        str(row.get("circuit_id", "UNKNOWN")),
                        "Circuit monthly cost is above telecom benchmark.",
                        current,
                        max(current - expected, 0),
                        "Renegotiate telecom circuit rate.",
                    )
                )
                finding_counter += 1

    mobile_rate = benchmark_rates.get("mobile_line", 0.0)
    if mobile_rate and not mobile.empty:
        high_mobile = mobile[pd.to_numeric(mobile.get("monthly_cost"), errors="coerce") > mobile_rate]
        for _, row in high_mobile.iterrows():
            current = float(pd.to_numeric(row.get("monthly_cost"), errors="coerce") or 0)
            findings.append(
                _build_finding(
                    finding_counter,
                    "benchmark_variance",
                    str(row.get("line_id", "UNKNOWN")),
                    "Mobile line monthly cost is above benchmark.",
                    current,
                    max(current - mobile_rate, 0),
                    "Move line to benchmark-aligned mobile plan.",
                )
            )
            finding_counter += 1

    software_rate = benchmark_rates.get("software_license", 0.0)
    if software_rate and not licenses.empty:
        high_license = licenses[pd.to_numeric(licenses.get("unit_monthly_cost"), errors="coerce") > software_rate]
        for _, row in high_license.iterrows():
            unit_monthly = float(pd.to_numeric(row.get("unit_monthly_cost"), errors="coerce") or 0)
            purchased = float(pd.to_numeric(row.get("purchased_count"), errors="coerce") or 0)
            current_monthly = float(pd.to_numeric(row.get("monthly_cost"), errors="coerce") or 0)
            findings.append(
                _build_finding(
                    finding_counter,
                    "benchmark_variance",
                    str(row.get("license_id", "UNKNOWN")),
                    "License unit cost is above software benchmark.",
                    current_monthly,
                    max((unit_monthly - software_rate) * purchased, 0),
                    "Renegotiate software license unit rates.",
                )
            )
            finding_counter += 1

    total_monthly_savings = round(sum(item["estimated_monthly_savings"] for item in findings), 2)
    total_annual_savings = round(sum(item["estimated_annual_savings"] for item in findings), 2)
    high_priority_findings = sum(1 for item in findings if item["priority"] == "High")

    output = {
        "metadata": {
            "source": "waste_detection_agent",
            "discovery_total_annual_spend": discovery.get("total_annual_spend"),
        },
        "number_of_findings": len(findings),
        "high_priority_findings": high_priority_findings,
        "total_potential_monthly_savings": total_monthly_savings,
        "total_potential_annual_savings": total_annual_savings,
        "findings": findings,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUTPUT_FILE.open("w", encoding="utf-8") as file_handle:
        json.dump(output, file_handle, indent=2)

    print("[INFO] Waste detection agent completed successfully.")
    print(f"[INFO] Findings generated: {len(findings)}")
    print(f"[INFO] Output written: {OUTPUT_FILE}")

    return output


if __name__ == "__main__":
    run_waste_detection_agent()
