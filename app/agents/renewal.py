"""
Purpose: Classify contract renewal risk from date math (deterministic - a notice
deadline either has passed or hasn't) and produce one portfolio-level renewal
risk narrative (LLM when available, templated otherwise).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app import config
from app.agents.schemas import RenewalRisk
from app.tools import dataset_tools
from app.tools.llm_client import UNTRUSTED_PREAMBLE, get_mode, plain_complete, wrap_untrusted

RENEWAL_SYSTEM_PROMPT = (
    "You are a contracts manager. Write a tight 2-3 sentence renewal risk briefing "
    "for an executive summary. No preamble, no headers."
    "\n\n" + UNTRUSTED_PREAMBLE
)


def _reference_date() -> datetime:
    if config.REFERENCE_DATE:
        return datetime.strptime(config.REFERENCE_DATE, "%Y-%m-%d")
    return datetime.today()


def _risk(days_remaining: int, notice_closing: bool, auto_renew: bool, annual_value: float) -> str:
    """Risk is primarily about timing urgency; contract size only escalates
    MEDIUM to HIGH when a renewal is already inside the 90-day window - a
    large contract renewing in two years is not itself a HIGH risk."""
    if days_remaining <= 30 or (notice_closing and auto_renew):
        return "HIGH"
    if days_remaining <= 90:
        return "HIGH" if (auto_renew and annual_value >= 250_000) else "MEDIUM"
    if auto_renew:
        return "MEDIUM"
    return "LOW"


def _recommended_action(risk: str, auto_renew: bool, notice_closing: bool) -> str:
    if risk == "HIGH" and notice_closing:
        return "Escalate immediately and issue renewal/termination notice"
    if risk == "HIGH":
        return "Renegotiate before renewal"
    if auto_renew:
        return "Review terms and pre-negotiate before notice deadline"
    return "Monitor and schedule review"


def run() -> tuple[list[RenewalRisk], str]:
    today = _reference_date()
    risks: list[RenewalRisk] = []

    for row in dataset_tools.fetch_contracts():
        try:
            renewal_date = datetime.strptime(str(row.get("end_date", "")), "%Y-%m-%d")
        except ValueError:
            continue

        notice_days = int(row.get("notice_days", 0) or 0)
        notice_deadline = renewal_date - timedelta(days=notice_days)
        days_remaining = (renewal_date - today).days
        days_to_notice_deadline = (notice_deadline - today).days
        auto_renew = str(row.get("auto_renew", "No")).strip().lower() == "yes"
        annual_cost = float(row.get("annual_cost", 0) or 0)
        notice_closing = 0 <= days_to_notice_deadline <= 30
        risk = _risk(days_remaining, notice_closing, auto_renew, annual_cost)

        if days_remaining <= 90 or auto_renew or notice_closing:
            risks.append(RenewalRisk(
                contract_id=row["contract_id"],
                vendor=row.get("vendor", "Unknown Vendor"),
                contract_label=f"{row.get('vendor', 'Unknown Vendor')} {row.get('service_type', 'Service')}",
                renewal_date=renewal_date.strftime("%Y-%m-%d"),
                notice_deadline=notice_deadline.strftime("%Y-%m-%d"),
                days_remaining=days_remaining,
                days_to_notice_deadline=days_to_notice_deadline,
                auto_renew=auto_renew,
                notice_window_closing=notice_closing,
                risk=risk,
                recommended_action=_recommended_action(risk, auto_renew, notice_closing),
                annual_cost=round(annual_cost, 2),
            ))

    risks.sort(key=lambda r: r.days_remaining)
    narrative = _renewal_narrative(risks)
    return risks, narrative


def _renewal_narrative(risks: list[RenewalRisk]) -> str:
    high = [r for r in risks if r.risk == "HIGH"]
    closing = [r for r in risks if r.notice_window_closing]

    if get_mode() != "offline" and risks:
        lines = "\n".join(
            f"- {r.contract_label} ({r.contract_id}): {r.risk} risk, {r.days_remaining} days to renewal, "
            f"notice window closing: {r.notice_window_closing}, ${r.annual_cost:,.0f}/yr"
            for r in risks[:12]
        )
        # contract_label is vendor + service_type, which for an uploaded
        # contract are raw regex captures off a user-supplied document. Delimit
        # them the same way extraction and /api/ask delimit retrieved clause
        # text: this is third-party data about a contract, never an instruction.
        result = plain_complete(
            system=RENEWAL_SYSTEM_PROMPT,
            user=f"Upcoming renewal risk items:\n{wrap_untrusted(lines)}",
        )
        if result:
            return result.strip()

    if not risks:
        return "No contracts are inside a 90-day renewal or notice window."
    return (
        f"{len(risks)} contracts fall inside a 90-day renewal or auto-renew notice window, including "
        f"{len(high)} rated HIGH risk. {len(closing)} of those have a notice deadline closing within 30 "
        "days - missing these windows locks in another renewal term automatically."
    )
