"""
Purpose: Visualize renewal deadlines, auto-renew risks, and required review actions.
Inputs: outputs/renewal_intelligence_output.json.
Outputs: Streamlit risk table and deadline-oriented alerts.
Assigned Team Member: RYAN
Dependencies: streamlit, json, pathlib.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
RENEWAL_FILE = BASE_DIR / "outputs" / "renewal_intelligence_output.json"

st.markdown(
    """
<style>
.main { background: linear-gradient(180deg, #f4f8ff 0%, #ffffff 34%); }
.hero-mini {
    padding: 0.95rem 1.1rem;
    border-radius: 14px;
    background: radial-gradient(circle at 6% 8%, #a5d8ff 0%, transparent 26%),
                            radial-gradient(circle at 95% 12%, #d0bfff 0%, transparent 26%),
                            linear-gradient(130deg, #2a6f97 0%, #5a67d8 70%);
    color: #fff;
    margin-bottom: 0.9rem;
}
div[data-testid="stDataFrame"],
div[data-testid="stDataEditor"] {
    border: 1px solid #dbe7ff;
    border-radius: 14px;
    overflow: hidden;
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
<div class="hero-mini"><strong>Renewal Risks</strong><br/>Contracts requiring near-term commercial action.</div>
""",
    unsafe_allow_html=True,
)

if RENEWAL_FILE.exists():
    payload = json.loads(RENEWAL_FILE.read_text(encoding="utf-8"))
    st.caption(f"Reference Date: {payload.get('reference_date', 'N/A')}")
    summary = payload.get("summary", {})
    c1, c2, c3 = st.columns(3)
    c1.metric("High-Risk Contracts", f"{int(summary.get('high_risk_contracts', 0))}")
    c2.metric("Renewing in 60 Days", f"{int(summary.get('contracts_renewing_within_60_days', 0))}")
    c3.metric("Notice Windows Closing", f"{int(summary.get('contracts_with_notice_windows_closing', 0))}")

    risks = payload.get("renewal_risks", [])
    if risks:
        df = pd.DataFrame(risks)
        cols = ["contract_id", "renewal_date", "notice_deadline", "days_remaining", "risk", "recommended_action"]
        for col in cols:
            if col not in df.columns:
                df[col] = "N/A"
        st.data_editor(
            df[cols].sort_values(by="days_remaining"),
            width="stretch",
            hide_index=True,
            disabled=True,
            column_config={
                "contract_id": "Contract",
                "renewal_date": "Renewal Date",
                "notice_deadline": "Notice Deadline",
                "days_remaining": st.column_config.NumberColumn("Days Remaining", format="%d"),
                "risk": "Risk",
                "recommended_action": "Recommended Action",
            },
        )
    else:
        st.info("No renewal risks were identified in current output.")
else:
    st.warning("renewal_intelligence_output.json not found. Run renewal_intelligence_agent.py first.")
