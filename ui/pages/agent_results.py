"""
Purpose: Provide a consolidated viewer for all agent output artifacts.
Inputs: JSON files in outputs/.
Outputs: Streamlit expandable sections for each agent payload.
Assigned Team Member: RYAN
Dependencies: streamlit, json, pathlib.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "outputs"
FILES = [
    "discovery_output.json",
    "waste_findings.json",
    "contract_intelligence_output.json",
    "renewal_intelligence_output.json",
    "financial_optimization_output.json",
    "scenario_comparison_output.json",
]

st.markdown(
    """
<style>
.main { background: linear-gradient(180deg, #f4f8ff 0%, #ffffff 34%); }
.hero-mini {
    padding: 0.95rem 1.1rem;
    border-radius: 14px;
    background: radial-gradient(circle at 6% 8%, #d0bfff 0%, transparent 26%),
                            radial-gradient(circle at 95% 12%, #74c0fc 0%, transparent 26%),
                            linear-gradient(130deg, #3b3f8c 0%, #5a67d8 70%);
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
<div class="hero-mini"><strong>Agent Results</strong><br/>Pipeline artifact health and payload transparency.</div>
""",
    unsafe_allow_html=True,
)


def render_payload_widget(payload: object) -> None:
    """Render payloads as structured widgets for cleaner readability."""
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict):
            st.data_editor(pd.DataFrame(payload), width="stretch", hide_index=True, disabled=True)
        else:
            st.data_editor(pd.DataFrame({"value": payload}), width="stretch", hide_index=True, disabled=True)
        return

    if isinstance(payload, dict):
        if payload and all(not isinstance(v, (dict, list)) for v in payload.values()):
            rows = [{"field": k, "value": v} for k, v in payload.items()]
            st.data_editor(pd.DataFrame(rows), width="stretch", hide_index=True, disabled=True)
            return

        rows = []
        for key, value in payload.items():
            item_count = len(value) if isinstance(value, (list, dict)) else ""
            preview = str(value)
            if len(preview) > 90:
                preview = preview[:90] + "..."
            rows.append({"key": key, "type": type(value).__name__, "items": item_count, "preview": preview})
        st.data_editor(pd.DataFrame(rows), width="stretch", hide_index=True, disabled=True)
        return

    st.write(payload)

rows = []
for name in FILES:
    path = OUTPUT_DIR / name
    exists = path.exists()
    size_kb = round(path.stat().st_size / 1024, 2) if exists else 0
    rows.append({"output_file": name, "status": "Ready" if exists else "Missing", "size_kb": size_kb})

st.data_editor(
    pd.DataFrame(rows),
    width="stretch",
    hide_index=True,
    disabled=True,
    column_config={
        "output_file": "Output File",
        "status": "Status",
        "size_kb": st.column_config.NumberColumn("Size (KB)", format="%.2f"),
    },
)

st.caption("Expand any artifact below to inspect payload details in structured widgets.")
for name in FILES:
    path = OUTPUT_DIR / name
    with st.expander(name, expanded=False):
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            render_payload_widget(payload)
        else:
            st.warning(f"Missing file: {name}")
