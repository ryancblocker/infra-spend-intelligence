"""
Purpose: Build page-specific view models by combining the portfolio database
(dataset_tools) with the last completed pipeline run (PipelineState). Keeps
main.py route handlers thin and keeps "how do I join a contract to its
findings" logic in one place.
"""

from __future__ import annotations

from app.orchestrator import persistence
from app.orchestrator.state import PipelineState
from app.tools import dataset_tools


def contracts_list_view(state: PipelineState) -> list[dict]:
    extracted_by_id = {c.contract_id: c for c in state.get("extracted_contracts", [])}
    renewal_by_id = {r.contract_id: r for r in state.get("renewal_risks", [])}
    findings = list(state.get("waste_findings", [])) + list(state.get("benchmark_findings", []))

    finding_counts: dict[str, int] = {}
    finding_savings: dict[str, float] = {}
    for f in findings:
        if not f.contract_id:
            continue
        finding_counts[f.contract_id] = finding_counts.get(f.contract_id, 0) + 1
        finding_savings[f.contract_id] = finding_savings.get(f.contract_id, 0) + f.estimated_annual_savings

    rows = []
    for c in dataset_tools.fetch_contracts():
        cid = c["contract_id"]
        extracted = extracted_by_id.get(cid)
        renewal = renewal_by_id.get(cid)
        rows.append({
            **c,
            "risk_level": extracted.risk_level if extracted else "Unknown",
            "renewal_risk": renewal.risk if renewal else "LOW",
            "days_remaining": renewal.days_remaining if renewal else None,
            "finding_count": finding_counts.get(cid, 0),
            "finding_savings": round(finding_savings.get(cid, 0), 2),
        })
    return rows


def contract_detail_view(state: PipelineState, contract_id: str) -> dict | None:
    contract = dataset_tools.fetch_contract(contract_id)
    if not contract:
        return None

    extracted = next((c for c in state.get("extracted_contracts", []) if c.contract_id == contract_id), None)
    renewal = next((r for r in state.get("renewal_risks", []) if r.contract_id == contract_id), None)

    findings = [f for f in list(state.get("waste_findings", [])) + list(state.get("benchmark_findings", []))
                if f.contract_id == contract_id]
    scenarios = [s for s in state.get("scenarios", []) if s.contract_id == contract_id]

    doc_path = None
    from app import config
    candidate = config.CONTRACT_DOCS_DIR / f"{contract_id}.txt"
    source_text = candidate.read_text(encoding="utf-8") if candidate.exists() else None

    return {
        "contract": contract,
        "assets": dataset_tools.fetch_child_assets(contract_id),
        "extracted": extracted,
        "renewal": renewal,
        "findings": findings,
        "scenarios": scenarios,
        "source_text": source_text,
    }


def findings_view(state: PipelineState) -> dict:
    findings = list(state.get("waste_findings", [])) + list(state.get("benchmark_findings", []))
    by_category: dict[str, dict] = {}
    for f in findings:
        bucket = by_category.setdefault(f.category, {"count": 0, "annual_savings": 0.0})
        bucket["count"] += 1
        bucket["annual_savings"] += f.estimated_annual_savings

    category_rows = sorted(
        [{"category": k, **v} for k, v in by_category.items()],
        key=lambda r: r["annual_savings"], reverse=True,
    )
    findings_sorted = sorted(findings, key=lambda f: f.estimated_annual_savings, reverse=True)
    return {"findings": findings_sorted, "category_rows": category_rows}


def scenarios_view(state: PipelineState) -> list:
    return sorted(state.get("scenarios", []), key=lambda s: s.estimated_annual_savings, reverse=True)


def run_detail_view(run_id: str) -> dict | None:
    state = persistence.load_run(run_id)
    if state is None:
        return None
    return {
        "run_id": run_id,
        "summary": state.get("summary"),
        "top_scenarios": sorted(state.get("scenarios", []), key=lambda s: s.estimated_annual_savings, reverse=True)[:10],
        "renewal_risks": sorted(state.get("renewal_risks", []), key=lambda r: r.days_remaining)[:10],
        "critic_flags": state.get("critic_flags", []),
    }
