"""
Purpose: Detect utilization-based waste - underused circuits/colo/licenses, unassigned
or inactive mobile lines, and missing asset ownership. Deterministic: these are
threshold rules over measured data, not judgment calls, so an LLM adds latency
without adding correctness.
"""

from __future__ import annotations

from app.agents._util import FindingIdSequence, build_finding
from app.agents.schemas import Finding
from app.tools import dataset_tools

UNDERUTILIZATION_THRESHOLD_PCT = 25
LICENSE_ACTIVE_RATIO_THRESHOLD = 0.60
INACTIVE_DAYS_THRESHOLD = 90


def run() -> list[Finding]:
    seq = FindingIdSequence("W")
    findings: list[Finding] = []

    findings.extend(_circuit_underutilization(seq))
    findings.extend(_colo_underutilization(seq))
    findings.extend(_mobile_issues(seq))
    findings.extend(_license_underutilization(seq))
    findings.extend(_owner_gaps(seq))

    return findings


def _circuit_underutilization(seq: FindingIdSequence) -> list[Finding]:
    out = []
    for row in dataset_tools.fetch_circuits():
        util = row.get("utilization_pct")
        if util is None or float(util) >= UNDERUTILIZATION_THRESHOLD_PCT:
            continue
        monthly = float(row.get("monthly_cost", 0) or 0)
        out.append(build_finding(
            seq.next(), "telecom_underutilization", row["circuit_id"], row.get("contract_id", ""),
            f"Circuit utilization is {util}% (below {UNDERUTILIZATION_THRESHOLD_PCT}%).",
            monthly, monthly * 0.75, "Right-size or disconnect low-utilization circuit.",
        ))
    return out


def _colo_underutilization(seq: FindingIdSequence) -> list[Finding]:
    out = []
    for row in dataset_tools.fetch_colo():
        util = row.get("utilization_pct")
        if util is None or float(util) >= UNDERUTILIZATION_THRESHOLD_PCT:
            continue
        monthly = float(row.get("monthly_cost", 0) or 0)
        out.append(build_finding(
            seq.next(), "colo_underutilization", row["colo_id"], row.get("contract_id", ""),
            f"Colocation deployment utilization is {util}% (below {UNDERUTILIZATION_THRESHOLD_PCT}%).",
            monthly, monthly * 0.6, "Consolidate or downsize colocation footprint.",
        ))
    return out


def _mobile_issues(seq: FindingIdSequence) -> list[Finding]:
    out = []
    for row in dataset_tools.fetch_mobile_lines():
        monthly = float(row.get("monthly_cost", 0) or 0)
        assigned = str(row.get("assigned_user") or "").strip()
        last_activity = row.get("last_activity_days")

        if not assigned:
            out.append(build_finding(
                seq.next(), "mobile_unassigned", row["line_id"], row.get("contract_id", ""),
                "Mobile line has no assigned user.", monthly, monthly, "Cancel line or assign to an active employee.",
            ))
        elif last_activity is not None and float(last_activity) > INACTIVE_DAYS_THRESHOLD:
            out.append(build_finding(
                seq.next(), "mobile_inactive", row["line_id"], row.get("contract_id", ""),
                f"No activity for {int(float(last_activity))} days.", monthly, monthly,
                "Suspend or cancel inactive mobile line.",
            ))
    return out


def _license_underutilization(seq: FindingIdSequence) -> list[Finding]:
    out = []
    for row in dataset_tools.fetch_licenses():
        purchased = float(row.get("purchased_count", 0) or 0)
        active = float(row.get("active_users", 0) or 0)
        if purchased <= 0:
            continue
        ratio = active / purchased
        if ratio >= LICENSE_ACTIVE_RATIO_THRESHOLD:
            continue
        unused = max(purchased - active, 0)
        unit_cost = float(row.get("unit_monthly_cost", 0) or 0)
        monthly = float(row.get("monthly_cost", 0) or 0)
        out.append(build_finding(
            seq.next(), "license_underutilization", row["license_id"], row.get("contract_id", ""),
            f"Active usage ratio is {ratio:.0%} (below {LICENSE_ACTIVE_RATIO_THRESHOLD:.0%}).",
            monthly, unused * unit_cost, "Reduce purchased seat count at next true-up.",
        ))
    return out


def _owner_gaps(seq: FindingIdSequence) -> list[Finding]:
    out = []
    specs = [
        (dataset_tools.fetch_contracts(), "contract_id", "contract_owner_gap", "Contract missing owner."),
        (dataset_tools.fetch_circuits(), "circuit_id", "service_owner_gap", "Circuit missing owner."),
        (dataset_tools.fetch_colo(), "colo_id", "service_owner_gap", "Colocation deployment missing owner."),
        (dataset_tools.fetch_licenses(), "license_id", "service_owner_gap", "License product missing owner."),
        (dataset_tools.fetch_mobile_lines(), "line_id", "service_owner_gap", "Mobile line missing owner."),
    ]
    for rows, id_col, category, message in specs:
        for row in rows:
            if str(row.get("owner") or "").strip():
                continue
            monthly = float(row.get("monthly_cost", row.get("annual_cost", 0) or 0) or 0)
            if "annual_cost" in row and "monthly_cost" not in row:
                monthly = monthly / 12
            out.append(build_finding(
                seq.next(), category, row.get(id_col, "UNKNOWN"), row.get("contract_id", row.get(id_col, "")),
                message, monthly, 0.0, "Review with owner and assign accountable manager.",
            ))
    return out
