"""
Purpose: Main client-facing Streamlit entry point for Infra Spend Intelligence.
Inputs: orchestrator.run_pipeline and JSON outputs under outputs/.
Outputs: Modern, widget-driven executive dashboard with pipeline trigger and decision-ready summaries.
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

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator import run_pipeline  # noqa: E402


OUTPUTS_DIR = ROOT_DIR / "outputs"
st.set_page_config(page_title="Infra Spend Intelligence", layout="wide")

st.markdown(
    """
<style>
.main { background: linear-gradient(180deg, #f4f8ff 0%, #ffffff 34%); }
.hero {
  padding: 1.2rem 1.3rem;
  border-radius: 16px;
  background: radial-gradient(circle at 5% 5%, #74c0fc 0%, transparent 28%),
                            radial-gradient(circle at 95% 15%, #d0bfff 0%, transparent 25%),
                            linear-gradient(130deg, #124e78 0%, #3f37c9 72%);
  color: #ffffff;
  margin-bottom: 1rem;
    box-shadow: 0 10px 26px rgba(63, 55, 201, 0.28);
}
.hero h1 { margin: 0; font-size: 1.85rem; }
.hero p { margin: 0.45rem 0 0 0; font-size: 1rem; }
.note {
  margin-top: 0.7rem;
  padding: 0.8rem;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.22);
}
.kpi-card {
  border: 1px solid #e1edf6;
  background: #ffffff;
  border-radius: 12px;
  padding: 0.7rem;
}
.small { color: #3f5b6b; font-size: 0.92rem; }

.stTabs [data-baseweb="tab-list"] {
    gap: 0.45rem;
    background: #e9efff;
    border-radius: 999px;
    padding: 0.35rem;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 999px;
    background: #dbe7ff;
    color: #22415f;
    font-weight: 600;
    border: none;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    background: linear-gradient(120deg, #1f7a8c 0%, #5a67d8 100%);
    color: #ffffff;
}
.stTabs [data-baseweb="tab-highlight"] {
    display: none;
}

div[data-testid="stDataFrame"],
div[data-testid="stDataEditor"] {
    border: 1px solid #dbe7ff;
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 4px 16px rgba(69, 90, 150, 0.08);
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] ul {
    gap: 0.35rem;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {
    border-radius: 10px;
    margin: 0.1rem 0;
    border: 1px solid #d6e3ff;
    background: linear-gradient(120deg, #edf4ff 0%, #e9ecff 100%);
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a span {
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-weight: 700;
    color: #23436a;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
    border-color: #9ab6ff;
    background: linear-gradient(120deg, #dbe9ff 0%, #dfe2ff 100%);
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {
    border-color: #637cff;
    background: linear-gradient(120deg, #2a6f97 0%, #5a67d8 100%);
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] span {
    color: #ffffff;
}
</style>
""",
    unsafe_allow_html=True,
)


def load_json(path: Path, default: Any = None) -> Any:
    """Safely loads a JSON output file and returns default when missing/invalid."""
    if default is None:
        default = {}
    if not path.exists():
        st.session_state.setdefault("app_warnings", []).append(f"Missing output file: {path.name}")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - demo-safe behavior
        st.session_state.setdefault("app_warnings", []).append(f"Invalid JSON in {path.name}: {exc}")
        return default


def money(value: Any) -> str:
    try:
        return f"${float(value):,.0f}"
    except Exception:
        return "N/A"


def num(value: Any) -> str:
    try:
        n = float(value)
        return f"{int(n)}" if n.is_integer() else f"{n:,.2f}"
    except Exception:
        return "N/A"


def safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return fallback


st.session_state["app_warnings"] = []

st.markdown(
    """
<div class="hero">
    <h1>Infrastructure Spend Intelligence Platform</h1>
  <p>
        Contract and utilization intelligence that highlights waste, renewal risk, and fastest savings actions.
  </p>
</div>
""",
    unsafe_allow_html=True,
)

# Sidebar controls to make the page interactive and demo-friendly.
with st.sidebar:
    st.markdown("## View Controls")
    top_n = st.slider("Top rows to show", min_value=5, max_value=30, value=10, step=1)
    priority_filter = st.multiselect(
        "Finding priority",
        options=["High", "Medium", "Low"],
        default=["High", "Medium", "Low"],
    )
    risk_filter = st.multiselect(
        "Renewal risk filter",
        options=["HIGH", "MEDIUM", "LOW"],
        default=["HIGH", "MEDIUM", "LOW"],
    )
    hide_low_savings = st.toggle("Hide low savings (<$10k)", value=True)
    show_pipeline_block = st.toggle("Show pipeline status block", value=True)

act_col, msg_col = st.columns([1, 3])
with act_col:
    if st.button("Run Pipeline", type="primary", width="stretch"):
        with st.spinner("Running Infra Spend Intelligence pipeline..."):
            summary = run_pipeline()
            st.session_state["pipeline_summary"] = summary
        if summary.get("pipeline_status") == "success":
            st.success("Pipeline completed")
        else:
            st.warning("Pipeline completed with warnings")
with msg_col:
    st.markdown('<p class="small">Run pipeline to refresh outputs and update insights instantly.</p>', unsafe_allow_html=True)

# Reload data every render.
discovery = load_json(OUTPUTS_DIR / "discovery_output.json", {})
waste = load_json(OUTPUTS_DIR / "waste_findings.json", {})
renewal = load_json(OUTPUTS_DIR / "renewal_intelligence_output.json", {})
financial = load_json(OUTPUTS_DIR / "financial_optimization_output.json", {})
executive = load_json(OUTPUTS_DIR / "executive_summary.json", {})

if st.session_state.get("app_warnings"):
    with st.expander("Data Warnings", expanded=False):
        for item in st.session_state["app_warnings"]:
            st.warning(item)

# Executive cards (first page: only key info)
annual_spend = discovery.get("total_annual_spend") if isinstance(discovery, dict) else None
annual_savings = financial.get("total_identified_annual_savings") if isinstance(financial, dict) else None
if not annual_savings and isinstance(waste, dict):
    annual_savings = waste.get("total_potential_annual_savings")
findings = waste.get("number_of_findings") if isinstance(waste, dict) else None
high_priority = waste.get("high_priority_findings") if isinstance(waste, dict) else None
renewal_summary = renewal.get("summary", {}) if isinstance(renewal, dict) else {}
contracts_at_risk = renewal_summary.get("high_risk_contracts")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Annual Spend", money(annual_spend) if annual_spend else "N/A")
k2.metric("Potential Savings", money(annual_savings) if annual_savings else "N/A")
k3.metric("Waste Findings", num(findings) if findings is not None else "N/A")
k4.metric("Contracts at Risk", num(contracts_at_risk) if contracts_at_risk is not None else "N/A")

if isinstance(executive, dict) and executive.get("executive_summary"):
    st.subheader("Executive Summary")
    st.write(executive.get("executive_summary"))

# Widget-based sections
opportunity_tab, risk_tab, trend_tab = st.tabs(["Top Opportunities", "Renewal Risks", "Waste Findings"])

with opportunity_tab:
    rec_rows = financial.get("top_recommendations") or financial.get("recommendations") or []
    if rec_rows:
        rec_df = pd.DataFrame(rec_rows)
        for col in ["recommended_action", "estimated_annual_savings", "risk_level", "confidence", "category"]:
            if col not in rec_df.columns:
                rec_df[col] = "N/A"

        if hide_low_savings and "estimated_annual_savings" in rec_df.columns:
            rec_df = rec_df[pd.to_numeric(rec_df["estimated_annual_savings"], errors="coerce").fillna(0) >= 10000]

        if "risk_level" in rec_df.columns:
            rec_df = rec_df[rec_df["risk_level"].astype(str).str.title().isin(priority_filter)]

        if rec_df.empty:
            st.info("No recommendations match current filters.")
        else:
            view_cols = ["recommended_action", "category", "estimated_annual_savings", "risk_level", "confidence"]
            st.data_editor(
                rec_df[view_cols].head(top_n),
                width="stretch",
                hide_index=True,
                disabled=True,
                column_config={
                    "recommended_action": "Recommended Action",
                    "category": "Category",
                    "estimated_annual_savings": st.column_config.NumberColumn("Annual Savings", format="$%d"),
                    "risk_level": "Priority",
                    "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                },
            )
    else:
        st.info("No recommendation data available yet.")

with risk_tab:
    risk_rows = renewal.get("renewal_risks", []) if isinstance(renewal, dict) else []
    if risk_rows:
        rdf = pd.DataFrame(risk_rows)
        for col in ["contract_id", "days_remaining", "risk", "recommended_action", "renewal_date"]:
            if col not in rdf.columns:
                rdf[col] = "N/A"

        rdf = rdf[rdf["risk"].astype(str).str.upper().isin(risk_filter)] if "risk" in rdf.columns else rdf

        if rdf.empty:
            st.info("No renewal risks match current filters.")
        else:
            risk_cols = ["contract_id", "renewal_date", "days_remaining", "risk", "recommended_action"]
            st.data_editor(
                rdf[risk_cols].sort_values(by="days_remaining").head(top_n),
                width="stretch",
                hide_index=True,
                disabled=True,
                column_config={
                    "contract_id": "Contract",
                    "renewal_date": "Renewal Date",
                    "days_remaining": st.column_config.NumberColumn("Days Remaining", format="%d"),
                    "risk": "Risk",
                    "recommended_action": "Recommended Action",
                },
            )
    else:
        st.info("Renewal risk output not available yet.")

with trend_tab:
    find_rows = waste.get("findings", []) if isinstance(waste, dict) else []
    if find_rows:
        fdf = pd.DataFrame(find_rows)
        for col in ["category", "estimated_annual_savings", "priority"]:
            if col not in fdf.columns:
                fdf[col] = "N/A"

        if "priority" in fdf.columns:
            fdf = fdf[fdf["priority"].astype(str).str.title().isin(priority_filter)]
        if hide_low_savings and "estimated_annual_savings" in fdf.columns:
            fdf = fdf[pd.to_numeric(fdf["estimated_annual_savings"], errors="coerce").fillna(0) >= 10000]

        if fdf.empty:
            st.info("No waste findings match current filters.")
        else:
            chart_df = (
                fdf.assign(estimated_annual_savings=pd.to_numeric(fdf["estimated_annual_savings"], errors="coerce").fillna(0))
                .groupby("category", as_index=False)["estimated_annual_savings"]
                .sum()
                .sort_values(by="estimated_annual_savings", ascending=False)
                .head(10)
            )
            st.bar_chart(chart_df.set_index("category"))

            detail_cols = ["finding_id", "category", "asset_id", "estimated_annual_savings", "recommended_action", "priority"]
            for col in detail_cols:
                if col not in fdf.columns:
                    fdf[col] = "N/A"
            st.data_editor(
                fdf[detail_cols].sort_values(by="estimated_annual_savings", ascending=False).head(top_n),
                width="stretch",
                hide_index=True,
                disabled=True,
                column_config={
                    "finding_id": "Finding",
                    "category": "Category",
                    "asset_id": "Asset",
                    "estimated_annual_savings": st.column_config.NumberColumn("Annual Savings", format="$%d"),
                    "recommended_action": "Recommended Action",
                    "priority": "Priority",
                },
            )
    else:
        st.info("Waste findings are not available yet.")

if show_pipeline_block:
    with st.expander("Pipeline Status", expanded=False):
        ps = st.session_state.get("pipeline_summary")
        if ps:
            st.write(f"Status: {ps.get('pipeline_status', 'N/A')}")
            st.write(f"Timestamp: {ps.get('timestamp', 'N/A')}")
            st.write(f"Outputs generated: {safe_int(len(ps.get('output_files_generated', [])))}")
            if ps.get("agents_run"):
                st.success("Completed: " + ", ".join(ps.get("agents_run", [])))
            if ps.get("agents_skipped"):
                st.warning("Skipped: " + ", ".join(ps.get("agents_skipped", [])))
            if ps.get("agents_failed"):
                st.error("Failed: " + ", ".join(ps.get("agents_failed", [])))
        else:
            st.info("No pipeline run yet in this session.")
