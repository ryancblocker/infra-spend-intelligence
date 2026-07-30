"""
Purpose: Extract structured clause data (renewal terms, fees, SLA, liability cap,
MFN/price-protection presence) from unstructured contract prose. This is the
agent that most justifies an LLM over regex: app/data/contract_docs/*.txt are
full legal/commercial paragraphs, not key:value stubs, and the mix of clauses
present varies per contract. The offline fallback still works (regex tuned to
the generator's phrasing) but the LLM path handles phrasing variation gracefully
in a way regex cannot.
"""

from __future__ import annotations

import re

from app import config
from app.agents.schemas import ExtractedContract
from app.tools.llm_client import chat_structured, get_mode

EXTRACTION_SYSTEM_PROMPT = (
    "You are a contract analyst. Extract structured terms from the commercial contract text "
    "provided. Only use information present in the text - do not invent values. If a field is "
    "not present, leave it empty/false/null as appropriate. Set risk_level to High if the "
    "contract auto-renews AND has a notice period of 90+ days AND a termination fee of 15%+; "
    "Medium if two of those three conditions hold; otherwise Low. risk_rationale should be one "
    "sentence citing the specific terms that drove the risk level."
)


def run() -> list[ExtractedContract]:
    results = []
    for path in sorted(config.CONTRACT_DOCS_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        contract_id = path.stem
        extracted = _extract_llm(contract_id, text) if get_mode() != "offline" else None
        if extracted is None:
            extracted = _extract_offline(contract_id, text)
        results.append(extracted)
    return results


def _extract_llm(contract_id: str, text: str) -> ExtractedContract | None:
    result = chat_structured(
        system=EXTRACTION_SYSTEM_PROMPT,
        user=f"Contract text:\n\n{text}",
        schema=ExtractedContract,
    )
    if result is None:
        return None
    result.contract_id = contract_id
    result.extraction_source = get_mode()
    return result


def _extract_offline(contract_id: str, text: str) -> ExtractedContract:
    vendor = _search(text, r"VENDOR:\s*(.+)")
    category = _search(text, r"CATEGORY:\s*(.+)")
    end_date = _search(text, r"continues through (\d{4}-\d{2}-\d{2})")
    auto_renew = "automatically renew" in text.lower()
    notice_match = re.search(r"(?:non-renewal|expiration)[^.]*?at least (\d+) days", text, re.IGNORECASE)
    notice_days = int(notice_match.group(1)) if notice_match else None
    fee_match = re.search(r"termination fee equal to (\d+(?:\.\d+)?)%", text, re.IGNORECASE)
    termination_fee_pct = float(fee_match.group(1)) if fee_match else None
    esc_match = re.search(r"Annual Escalator of (\d+(?:\.\d+)?)%", text, re.IGNORECASE)
    escalator_pct = float(esc_match.group(1)) if esc_match else None
    minimum_commitment = _search(text, r"covering (.+?)\.\s")
    sla_summary = _search(text, r"Service Level Credits:\s*(.+)")
    liability_summary = _search(text, r"Limitation of Liability:\s*(.+)")
    has_mfn = "most favored pricing" in text.lower()
    has_price_protection = "price protection" in text.lower()

    risk_level, risk_rationale = _offline_risk(auto_renew, notice_days, termination_fee_pct, escalator_pct)

    return ExtractedContract(
        contract_id=contract_id,
        vendor=vendor,
        category=category,
        auto_renew=auto_renew,
        renewal_date=end_date,
        notice_period_days=notice_days,
        termination_fee_pct=termination_fee_pct,
        annual_escalator_pct=escalator_pct,
        minimum_commitment=minimum_commitment,
        sla_summary=sla_summary,
        liability_cap_summary=liability_summary,
        has_mfn_clause=has_mfn,
        has_price_protection_clause=has_price_protection,
        risk_level=risk_level,
        risk_rationale=risk_rationale,
        extraction_source="offline",
    )


def _search(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _offline_risk(auto_renew: bool, notice_days: int | None, fee_pct: float | None,
                   esc_pct: float | None) -> tuple[str, str]:
    conditions = []
    if auto_renew:
        conditions.append("auto-renews")
    if notice_days and notice_days >= 90:
        conditions.append(f"{notice_days}-day notice period")
    if fee_pct and fee_pct >= 15:
        conditions.append(f"{fee_pct:.0f}% termination fee")

    if len(conditions) >= 3:
        level = "High"
    elif len(conditions) == 2:
        level = "Medium"
    else:
        level = "Low"

    rationale = f"Driven by: {', '.join(conditions)}." if conditions else "No high-risk terms detected."
    return level, rationale
