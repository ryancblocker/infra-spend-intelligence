"""
Purpose: Main Streamlit entry point for Infra Spend Intelligence with one-click pipeline execution and executive reporting.
Inputs: orchestrator.run_pipeline and JSON outputs under outputs/.
Outputs: Interactive dashboard with pipeline status, KPIs, findings, recommendations, and optional intelligence views.
Assigned Team Member: RYAN
Dependencies: streamlit, pandas, json, pathlib.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


# Ensure project root is importable when app is launched from ui/.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator import run_pipeline  # noqa: E402


OUTPUTS_DIR = ROOT_DIR / "outputs"

st.set_page_config(page_title="Infra Spend Intelligence", layout="wide")
st.title("Infra Spend Intelligence")
st.caption("Agentic Infrastructure Contract & Spend Optimization Platform")


def load_json(path: Path, default: Any = None) -> Any:
    """
    Safely loads a JSON output file.
    If missing or invalid, returns default and shows a dashboard warning.
    """
    if default is None:
        default = {}

    if not path.exists():
        st.warning(f"Missing output file: {path.name}")
        return default

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - UI safety
        st.warning(f"Invalid JSON in {path.name}: {exc}")
        return default


# Pipeline trigger
if st.button("Run Pipeline", type="primary"):
    with st.spinner("Running Infra Spend Intelligence agent pipeline..."):
        summary = run_pipeline()
        st.session_state["pipeline_summary"] = summary

    if summary.get("pipeline_status") == "success":
        st.success("Pipeline completed.")
    else:
        st.warning("Pipeline completed with warnings or failures.")


# Reload JSON outputs each render so UI reflects latest pipeline run.
discovery = load_json(OUTPUTS_DIR / "discovery_output.json", default={})
waste = load_json(OUTPUTS_DIR / "waste_findings.json", default={})
contract_intel = load_json(OUTPUTS_DIR / "contract_intelligence_output.json", default={})
renewal = load_json(OUTPUTS_DIR / "renewal_intelligence_output.json", default={})
scenario = load_json(OUTPUTS_DIR / "scenario_comparison_output.json", default={})
financial = load_json(OUTPUTS_DIR / "financial_optimization_output.json", default={})
executive = load_json(OUTPUTS_DIR / "executive_summary.json", default={})


# Executive Overview
st.subheader("Executive Overview")


def as_metric(value: Any, money: bool = False) -> str:
    if value is None:
        return "N/A"
    try:
        numeric = float(value)
        if money:
            return f"${numeric:,.0f}"
        if numeric.is_integer():
            return f"{int(numeric)}"
        return f"{numeric:,.2f}"
    except Exception:
        return str(value)


total_spend = discovery.get("total_annual_spend") if isinstance(discovery, dict) else None
total_savings = (
    financial.get("total_identified_annual_savings")
    if isinstance(financial, dict)
    else None
)
if total_savings in (None, 0):
    total_savings = waste.get("total_potential_annual_savings") if isinstance(waste, dict) else None

number_of_findings = waste.get("number_of_findings") if isinstance(waste, dict) else None
high_priority_findings = waste.get("high_priority_findings") if isinstance(waste, dict) else None
contracts_analyzed = contract_intel.get("total_contracts_parsed") if isinstance(contract_intel, dict) else None

recommendations_count = None
if isinstance(financial, dict):
    recs = financial.get("recommendations", [])
    if isinstance(recs, list):
        recommendations_count = len(recs)

col1, col2, col3 = st.columns(3)
col4, col5, col6 = st.columns(3)

col1.metric("Total Annual Spend", as_metric(total_spend, money=True))
col2.metric("Total Identified Annual Savings", as_metric(total_savings, money=True))
col3.metric("Number of Waste Findings", as_metric(number_of_findings))
col4.metric("High Priority Findings", as_metric(high_priority_findings))
col5.metric("Number of Contracts Analyzed", as_metric(contracts_analyzed))
col6.metric("Number of Recommendations", as_metric(recommendations_count))


# Agent Pipeline Status
st.subheader("Agent Pipeline Status")
pipeline_summary = st.session_state.get("pipeline_summary")

if pipeline_summary:
    st.write(f"Pipeline status: {pipeline_summary.get('pipeline_status', 'N/A')}")
    st.write(f"Timestamp: {pipeline_summary.get('timestamp', 'N/A')}")

    completed_agents = pipeline_summary.get("agents_run", [])
    skipped_agents = pipeline_summary.get("agents_skipped", [])
    failed_agents = pipeline_summary.get("agents_failed", [])

    if completed_agents:
        st.success("Completed Agents")
        for agent in completed_agents:
            st.write(f"- {agent}")

    if skipped_agents:
        st.warning("Skipped Agents")
        for agent in skipped_agents:
            st.write(f"- {agent}")

    if failed_agents:
        st.error("Failed Agents")
        for agent in failed_agents:
            st.write(f"- {agent}")
else:
    st.info("No pipeline run summary in this session yet. Click Run Pipeline.")


# Top Recommendations
st.subheader("Top Recommendations")
recommendation_rows = []
if isinstance(financial, dict):
    recommendation_rows = financial.get("top_recommendations") or financial.get("recommendations") or []

if recommendation_rows:
    rec_df = pd.DataFrame(recommendation_rows)
    expected_columns = [
        "recommendation_id",
        "category",
        "issue",
        "recommended_action",
        "estimated_annual_savings",
        "risk_level",
        "confidence",
        "business_rationale",
    ]
    for col in expected_columns:
        if col not in rec_df.columns:
            rec_df[col] = "N/A"

    st.dataframe(rec_df[expected_columns], use_container_width=True)
else:
    st.info("No recommendations available in financial_optimization_output.json.")


# Savings / Waste Findings
st.subheader("Savings and Waste Findings")
if isinstance(waste, dict) and waste:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(
        "Total Potential Annual Savings",
        as_metric(waste.get("total_potential_annual_savings"), money=True),
    )
    m2.metric(
        "Total Potential Monthly Savings",
        as_metric(waste.get("total_potential_monthly_savings"), money=True),
    )
    m3.metric("Number of Findings", as_metric(waste.get("number_of_findings")))
    m4.metric("High Priority Findings", as_metric(waste.get("high_priority_findings")))

    findings = waste.get("findings", [])
    if findings:
        findings_df = pd.DataFrame(findings)
        finding_cols = [
            "finding_id",
            "category",
            "asset_id",
            "issue",
            "current_monthly_cost",
            "estimated_annual_savings",
            "recommended_action",
            "priority",
        ]
        for col in finding_cols:
            if col not in findings_df.columns:
                findings_df[col] = "N/A"

        st.dataframe(findings_df[finding_cols], use_container_width=True)
    else:
        st.info("No detailed findings present in waste_findings.json.")
else:
    st.info("Waste Detection Agent output not available yet.")


# Optional Contract Intelligence Section
with st.expander("Contract Intelligence Findings"):
    contracts = contract_intel.get("contracts", []) if isinstance(contract_intel, dict) else []
    if contracts:
        contracts_df = pd.DataFrame(contracts)
        contract_cols = [
            "contract_id",
            "vendor",
            "category",
            "auto_renew",
            "renewal_date",
            "notice_period_days",
            "termination_fee",
            "annual_escalator",
            "minimum_commitment",
            "risk_level",
            "clause_summary",
        ]
        for col in contract_cols:
            if col not in contracts_df.columns:
                contracts_df[col] = "N/A"

        st.dataframe(contracts_df[contract_cols], use_container_width=True)
    else:
        st.info("Contract Intelligence Agent output not available yet.")


# Optional Scenario Section
st.subheader("Keep vs Cancel vs Renegotiate Scenarios")
scenario_rows = scenario.get("scenario_results", []) if isinstance(scenario, dict) else []
if scenario_rows:
    scenario_df = pd.DataFrame(scenario_rows)

    # Normalize to requested display fields with robust fallbacks.
    if "contract_id" not in scenario_df.columns:
        scenario_df["contract_id"] = scenario_df.get("contract", "N/A")
    if "vendor" not in scenario_df.columns:
        scenario_df["vendor"] = "N/A"
    if "rationale" not in scenario_df.columns:
        scenario_df["rationale"] = scenario_df.get("issue", "N/A")

    scenario_cols = [
        "contract_id",
        "vendor",
        "keep_cost",
        "cancel_cost",
        "renegotiate_cost",
        "projected_savings",
        "recommendation",
        "rationale",
    ]
    for col in scenario_cols:
        if col not in scenario_df.columns:
            scenario_df[col] = "N/A"

    st.dataframe(scenario_df[scenario_cols], use_container_width=True)
else:
    st.info("Scenario Comparison Agent output not available yet.")


# Optional executive narrative panel for demo flow.
if isinstance(executive, dict) and executive:
    st.subheader("Executive Narrative")
    st.write(executive.get("executive_summary", "N/A"))
