"""
Purpose: FastAPI application - page routes (server-rendered Jinja2), the SSE
pipeline-run endpoint, and the /api/ask RAG endpoint. No Node/build step: the
frontend is templates + vanilla CSS/JS + vendored Alpine.js/Chart.js.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.requests import Request  # noqa: E402

from app import config, views  # noqa: E402
from app.data import seed_db  # noqa: E402
from app.orchestrator import persistence  # noqa: E402
from app.orchestrator.events import DONE_SENTINEL, new_queue  # noqa: E402
from app.orchestrator.graph import detail_for, run_pipeline  # noqa: E402
from app.orchestrator.state import PipelineState  # noqa: E402
from app.tools import dataset_tools, vector_store  # noqa: E402
from app.tools.llm_client import (  # noqa: E402
    UNTRUSTED_PREAMBLE,
    get_mode,
    plain_complete,
    scan_for_injection,
    wrap_untrusted,
)

app = FastAPI(title="PACT - Portfolio Agentic Contract Tracker")
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
templates.env.filters["money"] = lambda v: f"${v:,.0f}" if v is not None else "N/A"
templates.env.filters["money2"] = lambda v: f"${v:,.2f}" if v is not None else "N/A"

_LAST_RUN: PipelineState = {}
_RUN_IN_PROGRESS = False
# Per-node result lines from the last run, so a page load after the run can
# render the pipeline already complete instead of resetting every node to grey.
_LAST_NODE_DETAILS: dict[str, str] = {}

# Cache-buster for static assets. Without it a browser keeps serving the JS it
# already has, so a fix to the pipeline runner silently does not apply.
ASSET_VERSION = str(int(max(
    (p.stat().st_mtime for p in config.STATIC_DIR.rglob("*") if p.is_file()),
    default=0,
)))


@app.on_event("startup")
def on_startup() -> None:
    global _LAST_RUN
    config.ensure_runtime_dirs()

    if not config.DB_PATH.exists():
        print("[PACT] No database found - seeding from app/data/seed/ on first run...")
        seed_db.build_database()
        try:
            vector_store.build_index()
        except Exception as exc:
            print(f"[PACT] Vector index build skipped: {exc}")

    if config.FRESH_START:
        print("[PACT] PACT_FRESH_START=1 - starting with no prior run loaded.")
    else:
        loaded = persistence.load_run()
        if loaded:
            _LAST_RUN = loaded


PIPELINE_NODES = ("discovery", "extraction", "waste", "benchmark", "renewal",
                  "optimization", "critic", "narrator")


def _record_node_details(state: PipelineState) -> None:
    """Capture each node's result line so the finished pipeline can be re-rendered
    on a later page load."""
    global _LAST_NODE_DETAILS
    details: dict[str, str] = {}
    for node in PIPELINE_NODES:
        try:
            details[node] = detail_for(node, state)
        except Exception:
            details[node] = ""
    _LAST_NODE_DETAILS = details


def _base_context(request: Request) -> dict:
    return {
        "request": request,
        "llm_mode": get_mode(),
        "has_run": bool(_LAST_RUN),
        "summary": _LAST_RUN.get("summary"),
        "asset_version": ASSET_VERSION,
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


AGENT_PREVIEW = [
    ("Discovery", "Aggregates total spend and asset counts across the portfolio."),
    ("Contract Extraction", "Reads contract prose and pulls out renewal terms, fees, SLAs and "
                            "liability caps - retrieving clauses, checking its own gaps, and "
                            "querying again for whatever it is still missing."),
    ("Waste Detection", "Flags underutilized circuits, colocation and licenses, plus unassigned "
                        "or inactive mobile lines."),
    ("Benchmark Analysis", "Compares every rate against 2026 market benchmarks."),
    ("Renewal Intelligence", "Scores renewal risk against notice-period deadlines."),
    ("Optimization Strategy", "Recommends keep, cancel or renegotiate. Dollar figures are computed "
                              "deterministically; the model only supplies judgement."),
    ("Critic Review", "Checks the recommendations against the underlying numbers and sends "
                      "anything that does not hold up back to be redone."),
    ("Executive Narrator", "Synthesizes everything into an executive summary."),
]


# An illustrative portfolio shown on the explainer page, deliberately NOT the
# data loaded in this instance. Real figures are Discovery's output, and showing
# them before the pipeline runs gives away the result the demo is meant to
# reveal. The template labels this as an example in the copy so it can never be
# mistaken for the loaded portfolio.
EXAMPLE_PORTFOLIO = {
    "company": "Northwind Logistics",
    "annual_spend": 8_400_000,
    "contracts": 32,
    "circuits": 61,
    "colo": 24,
    "licenses": 27,
    "mobile_lines": 118,
    "docs": 12,
}


@app.get("/welcome", response_class=HTMLResponse)
def welcome(request: Request):
    """Permanent explainer that doubles as the first-run entry point."""
    ctx = _base_context(request)
    ctx.update({"example": EXAMPLE_PORTFOLIO, "agents": AGENT_PREVIEW})
    return templates.TemplateResponse(request, "welcome.html", ctx)


@app.post("/api/reset")
def api_reset():
    """Clear the current run so the demo can be replayed from zero. Idempotent."""
    global _LAST_RUN, _LAST_NODE_DETAILS
    _LAST_RUN = {}
    # Must clear too, or the pipeline still renders green from the previous run
    # after a reset that is supposed to return everything to zero.
    _LAST_NODE_DETAILS = {}
    persistence.clear_run()
    return {"ok": True, "has_run": False}


@app.get("/", response_class=HTMLResponse)
def mission_control(request: Request):
    # No redirect here. Bouncing / to /welcome whenever no run exists makes the
    # Overview nav link dead after a reset - you click it and land somewhere
    # else. The dashboard renders its own empty state instead, and /welcome is
    # reachable from the nav whenever it is wanted.
    totals = dataset_tools.portfolio_totals()
    ctx = _base_context(request)
    ctx["autostart"] = request.query_params.get("start") == "1"
    ctx["node_details"] = _LAST_NODE_DETAILS
    ctx.update({
        "totals": totals,
        "findings": (list(_LAST_RUN.get("waste_findings", [])) + list(_LAST_RUN.get("benchmark_findings", [])))[:8],
        "top_scenarios": sorted(_LAST_RUN.get("scenarios", []), key=lambda s: s.estimated_annual_savings, reverse=True)[:6],
        "renewal_risks": sorted(_LAST_RUN.get("renewal_risks", []), key=lambda r: r.days_remaining)[:6],
        "critic_flags": _LAST_RUN.get("critic_flags", []),
    })
    return templates.TemplateResponse(request, "mission_control.html", ctx)


@app.get("/contracts", response_class=HTMLResponse)
def contracts_page(request: Request):
    ctx = _base_context(request)
    ctx["contracts"] = views.contracts_list_view(_LAST_RUN)
    return templates.TemplateResponse(request, "contracts.html", ctx)


@app.get("/contracts/{contract_id}", response_class=HTMLResponse)
def contract_detail_page(request: Request, contract_id: str):
    detail = views.contract_detail_view(_LAST_RUN, contract_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Contract {contract_id} not found")
    ctx = _base_context(request)
    ctx.update(detail)
    return templates.TemplateResponse(request, "contract_detail.html", ctx)


@app.get("/findings", response_class=HTMLResponse)
def findings_page(request: Request):
    ctx = _base_context(request)
    ctx.update(views.findings_view(_LAST_RUN))
    return templates.TemplateResponse(request, "findings.html", ctx)


@app.get("/scenarios", response_class=HTMLResponse)
def scenarios_page(request: Request):
    ctx = _base_context(request)
    ctx["scenarios"] = views.scenarios_view(_LAST_RUN)
    return templates.TemplateResponse(request, "scenarios.html", ctx)


@app.get("/ask", response_class=HTMLResponse)
def ask_page(request: Request):
    ctx = _base_context(request)
    return templates.TemplateResponse(request, "ask.html", ctx)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/api/status")
def api_status():
    return {"llm_mode": get_mode(), "has_run": bool(_LAST_RUN),
            "summary": _LAST_RUN["summary"].model_dump(mode="json") if _LAST_RUN.get("summary") else None}


@app.get("/api/run")
async def api_run():
    # One run at a time. Without this, a reconnecting EventSource or a duplicate
    # tab can start unbounded concurrent pipelines - which is exactly what a
    # stale ?start=1 in the URL caused.
    global _RUN_IN_PROGRESS
    if _RUN_IN_PROGRESS:
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress.")
    _RUN_IN_PROGRESS = True

    async def event_stream():
        global _LAST_RUN, _RUN_IN_PROGRESS
        try:
            q = new_queue()
            task = asyncio.create_task(asyncio.to_thread(run_pipeline, q))
            while True:
                item = await asyncio.to_thread(q.get)
                if isinstance(item, str) and item == DONE_SENTINEL:
                    break
                yield item.to_sse()

            final_state = await task
            _LAST_RUN = final_state
            _record_node_details(final_state)
            persistence.save_run(final_state)
            yield f"event: result\ndata: {json.dumps({'ok': True})}\n\n"
        finally:
            # Runs on client disconnect too, so an aborted stream cannot wedge
            # the flag on and lock out every future run.
            _RUN_IN_PROGRESS = False

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


ASK_SYSTEM_PROMPT = (
    "You are PACT, an infrastructure and SaaS spend intelligence assistant. Answer the user's "
    "question using ONLY the contract clause excerpts provided as context. Cite contract IDs in "
    "brackets like [C-0012] when referencing a specific contract. If the context doesn't contain "
    "enough information to answer, say so plainly rather than guessing."
    "\n\n" + UNTRUSTED_PREAMBLE
)


class AskRequest(BaseModel):
    question: str


@app.post("/api/ask")
async def api_ask(payload: AskRequest):
    hits = await asyncio.to_thread(vector_store.search, payload.question, 6)
    mode = get_mode()

    # Retrieved clause text is third-party data, not instructions. Delimit it
    # before it reaches the model, and surface anything that looks like an
    # attempt to steer the agent rather than trusting it silently.
    injection_markers = sorted({m for h in hits for m in scan_for_injection(h["text"])})

    if mode != "offline" and hits:
        context = wrap_untrusted(
            "\n\n".join(f"[{h['contract_id']} {h.get('heading', '')}] {h['text']}" for h in hits)
        )
        answer = await asyncio.to_thread(
            plain_complete, ASK_SYSTEM_PROMPT,
            f"Question: {payload.question}\n\nContext:\n{context}", "ask",
        )
        if not answer:
            answer = _offline_answer(hits)
    else:
        answer = _offline_answer(hits)

    response = {"answer": answer, "sources": sorted({h["contract_id"] for h in hits}), "mode": mode}
    if injection_markers:
        response["warning"] = (
            "Instruction-like text was detected in the retrieved contract excerpts and was "
            f"treated as data, not instructions: {', '.join(injection_markers)}"
        )
    return response


def _offline_answer(hits: list[dict]) -> str:
    if not hits:
        return "No matching contract clauses were found for that question."
    lines = [f"[{h['contract_id']}] {h['text'][:220].strip()}" for h in hits[:4]]
    return ("No LLM is configured (offline mode), so here are the most relevant contract clauses "
            "found by search instead of a synthesized answer:\n\n" + "\n\n".join(lines))
