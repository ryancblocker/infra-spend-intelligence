"""
Purpose: Compare live contract rates against market benchmark rates (telecom,
colocation, mobile, SaaS) - deterministic math, since "above/below benchmark"
has one correct answer per the reference table. Adds one LLM-generated market
narrative paragraph summarizing negotiating leverage across the flagged items;
offline mode uses a templated equivalent.
"""

from __future__ import annotations

from app.agents._util import FindingIdSequence, build_finding
from app.agents.schemas import Finding
from app.tools import dataset_tools
from app.tools.llm_client import get_mode, plain_complete


def run() -> tuple[list[Finding], str]:
    benchmarks = dataset_tools.fetch_benchmarks()
    seq = FindingIdSequence("B")
    findings: list[Finding] = []

    findings.extend(_circuit_variance(seq, benchmarks))
    findings.extend(_colo_variance(seq, benchmarks))
    findings.extend(_mobile_variance(seq, benchmarks))
    findings.extend(_license_variance(seq, benchmarks))

    narrative = _market_narrative(findings)
    return findings, narrative


def _circuit_variance(seq: FindingIdSequence, benchmarks: dict[str, float]) -> list[Finding]:
    out = []
    for row in dataset_tools.fetch_circuits():
        rate = benchmarks.get(f"circuit_{row.get('circuit_type')}")
        if not rate:
            continue
        bandwidth = float(row.get("bandwidth_mbps", 0) or 0)
        expected = bandwidth * rate
        current = float(row.get("monthly_cost", 0) or 0)
        if current <= expected or expected <= 0:
            continue
        out.append(build_finding(
            seq.next(), "benchmark_variance", row["circuit_id"], row.get("contract_id", ""),
            f"Circuit rate is above the {row.get('circuit_type')} market benchmark "
            f"(${current / bandwidth:.2f}/Mbps vs ${rate:.2f}/Mbps).",
            current, current - expected, "Renegotiate telecom circuit rate.",
        ))
    return out


def _colo_variance(seq: FindingIdSequence, benchmarks: dict[str, float]) -> list[Finding]:
    out = []
    rack_rate = benchmarks.get("colo_rack_unit", 0)
    power_rate = benchmarks.get("colo_power_kw", 0)
    for row in dataset_tools.fetch_colo():
        rack_units = float(row.get("rack_units", 0) or 0)
        power_kw = float(row.get("power_kw", 0) or 0)
        current = float(row.get("monthly_cost", 0) or 0)
        expected = max(rack_units * rack_rate, power_kw * power_rate)
        if expected <= 0 or current <= expected:
            continue
        out.append(build_finding(
            seq.next(), "benchmark_variance", row["colo_id"], row.get("contract_id", ""),
            "Colocation rate is above the market benchmark for equivalent capacity.",
            current, current - expected, "Renegotiate colocation rate or right-size footprint.",
        ))
    return out


def _mobile_variance(seq: FindingIdSequence, benchmarks: dict[str, float]) -> list[Finding]:
    out = []
    for row in dataset_tools.fetch_mobile_lines():
        rate = benchmarks.get(f"mobile_{row.get('plan_tier')}")
        if not rate:
            continue
        current = float(row.get("monthly_cost", 0) or 0)
        if current <= rate:
            continue
        out.append(build_finding(
            seq.next(), "benchmark_variance", row["line_id"], row.get("contract_id", ""),
            f"{row.get('plan_tier')} line is above the ${rate:.0f}/month benchmark.",
            current, current - rate, "Move line to a benchmark-aligned plan.",
        ))
    return out


def _license_variance(seq: FindingIdSequence, benchmarks: dict[str, float]) -> list[Finding]:
    out = []
    for row in dataset_tools.fetch_licenses():
        rate = benchmarks.get(f"license_{row.get('category')}")
        if not rate:
            continue
        unit_cost = float(row.get("unit_monthly_cost", 0) or 0)
        purchased = float(row.get("purchased_count", 0) or 0)
        current_monthly = float(row.get("monthly_cost", 0) or 0)
        if unit_cost <= rate:
            continue
        out.append(build_finding(
            seq.next(), "benchmark_variance", row["license_id"], row.get("contract_id", ""),
            f"{row.get('category')} unit cost is above the ${rate:.0f}/seat benchmark.",
            current_monthly, (unit_cost - rate) * purchased, "Renegotiate per-seat rate at next renewal.",
        ))
    return out


def _market_narrative(findings: list[Finding]) -> str:
    total = round(sum(f.estimated_annual_savings for f in findings), 2)
    categories = sorted({f.asset_id[:3] for f in findings})

    if get_mode() != "offline" and findings:
        summary_lines = "\n".join(f"- {f.asset_id}: {f.issue} (~${f.estimated_annual_savings:,.0f}/yr)" for f in findings[:12])
        result = plain_complete(
            system="You are a procurement analyst. Write a tight 2-3 sentence market positioning "
                   "note for an infrastructure spend executive summary. No preamble, no headers.",
            user=f"These items are priced above their market benchmark:\n{summary_lines}\n\n"
                 f"Total above-benchmark exposure: ${total:,.0f}/year.",
        )
        if result:
            return result.strip()

    if not findings:
        return "No contracts are currently priced above their market benchmark rate."
    return (
        f"{len(findings)} items across {len(categories)} asset types are priced above their market "
        f"benchmark rate, representing roughly ${total:,.0f} in annual renegotiation upside. "
        "Circuits and colocation deployments nearing renewal are typically the fastest wins since "
        "carriers and data center operators price-protect existing customers less aggressively than "
        "new ones."
    )
