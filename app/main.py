"""
Purpose: FastAPI application - page routes (server-rendered Jinja2), the SSE
pipeline-run endpoint, and the /api/ask RAG endpoint. No Node/build step: the
frontend is templates + vanilla CSS/JS + vendored Alpine.js/Chart.js.
"""

from __future__ import annotations

import asyncio
import json
import queue as queue_module
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.templating import Jinja2Templates  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from starlette.requests import Request  # noqa: E402

from app import config, views  # noqa: E402
from app.data import seed_db  # noqa: E402
from app.orchestrator import persistence  # noqa: E402
from app.orchestrator.events import DONE_SENTINEL, emit, emit_done, new_queue  # noqa: E402
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


@app.middleware("http")
async def enforce_upload_size_limit(request: Request, call_next):
    """Reject an obviously oversized upload via Content-Length before
    Starlette's multipart parser ever touches the body.

    A check inside the /api/upload route runs too late to matter: FastAPI
    resolves an `UploadFile` parameter by calling request.form(), which feeds
    the ENTIRE request body through MultiPartParser before the endpoint
    function is even entered. Middleware is the only place in this stack that
    runs before call_next hands the request to routing/parsing, so it is the
    only place this guard can actually stop the body from being buffered.

    Content-Length can be missing or understate the real size, so a missing
    or non-numeric header falls straight through to call_next and lets
    uploads.store()'s post-read byte count remain the real guarantee."""
    if request.method == "POST" and request.url.path == "/api/upload":
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > config.MAX_UPLOAD_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": f"File exceeds the {config.MAX_UPLOAD_BYTES // 1_048_576} MB limit."},
            )
    return await call_next(request)

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))
templates.env.filters["money"] = lambda v: f"${v:,.0f}" if v is not None else "N/A"
templates.env.filters["money2"] = lambda v: f"${v:,.2f}" if v is not None else "N/A"

_LAST_RUN: PipelineState = {}
_RUN_LOCK = threading.Lock()
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

    # The contracts table is derived from the upload manifest, so reconcile the
    # two on every boot, not only when the database is rebuilt. Without this an
    # uploaded row can outlive its manifest entry and become unreachable - shown
    # on /contracts and counted in totals, but with no Remove button and a 404
    # from the remove route.
    try:
        seed_db.rehydrate_uploads()
    except Exception as exc:
        print(f"[PACT] Upload reconciliation skipped: {exc}")

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
    ("Optimization Strategy", "Recommends keep, cancel or renegotiate for every finding. Dollar figures "
                              "are always computed deterministically. The model reasons about only the "
                              "highest-impact findings each run - a cached, capped judgement call - and "
                              "the rest use the same deterministic rule engine; the summary reports the split."),
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
    """Clear the current view so the demo can be replayed from zero. Idempotent.

    Only resets in-memory state - the run stays in history (Run History,
    /api/runs) and a restart still reloads it via persistence.load_run() in
    on_startup(). Reset is for replaying the live demo, not for erasing the
    trend data the history feature exists to keep.
    """
    global _LAST_RUN, _LAST_NODE_DETAILS
    _LAST_RUN = {}
    # Must clear too, or the pipeline still renders green from the previous run
    # after a reset that is supposed to return everything to zero.
    _LAST_NODE_DETAILS = {}
    return {"ok": True, "has_run": False}


class _UploadRemovedDuringProcessing(Exception):
    """Raised when this upload's own manifest entry is gone by the time
    api_upload tries to update it - i.e. the user clicked Remove on this very
    upload (visible on the dashboard as soon as uploads.store() commits, long
    before extraction finishes) while it was still being processed.

    Caught by the same except-block as any other failure in api_upload,
    which discards whatever partial artifacts this attempt produced (index
    chunks, mainly - the manifest entry and file are already gone, removed
    by the user) and reports the upload as not completed. The alternative -
    swallowing this and finishing normally - would silently re-add a
    manifest entry the user just explicitly deleted: the identical bug this
    whole fix exists to prevent, just aimed at the upload's own id instead of
    a different one."""


def _discard_failed_upload(contract_id: str, *possible_paths: Path) -> None:
    """Best-effort cleanup after a failed upload: the file (whichever name it
    currently has), the manifest entry, any index chunks, and any DB row.

    Each step is individually guarded. A failure in cleanup itself must never
    propagate - if it did, it would replace the exception the caller is about
    to report with an unrelated one, masking the actual cause from the user.
    Accepts every filename the upload could plausibly be under (pre- and
    post-rename) because uploads.remove() only unlinks whatever the manifest
    currently claims is the stored filename, and the failure window this
    guards against is exactly a manifest that disagrees with what is really
    on disk."""
    from app.tools import dataset_tools, uploads

    try:
        uploads.remove(contract_id)
    except Exception:
        pass
    try:
        vector_store.remove_document(contract_id)
    except Exception:
        pass
    for candidate in possible_paths:
        try:
            candidate.unlink(missing_ok=True)
        except Exception:
            pass
    try:
        dataset_tools.delete_upload_row(contract_id)
    except Exception:
        pass


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    """Accept a contract document, extract its terms, and register it as U-000N.

    Extraction runs synchronously: the user should learn immediately whether we
    could read their contract, not discover it during the next pipeline run.

    The 10 MB cap is enforced twice: enforce_upload_size_limit (middleware,
    above) rejects an oversized upload via Content-Length before the body is
    parsed at all, and uploads.store() below re-checks the actual byte count
    once read - the real guarantee, since Content-Length can be absent or
    wrong."""
    from app.agents import extraction
    from app.tools import dataset_tools, uploads
    from app.tools.document_loader import UnsupportedDocument, UnsupportedFileType
    from app.tools.uploads import ManifestError, UploadTooLarge

    data = await file.read()
    # Computed once, up front, and reused below both for the DB row's vendor
    # fallback and the response payload - same sanitized name either way,
    # rather than two independent calls that could theoretically drift.
    original_filename = uploads.safe_basename(file.filename or "upload")
    try:
        contract_id, path, text = uploads.store(file.filename or "upload", data)
    except UploadTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except UnsupportedFileType as exc:
        raise HTTPException(status_code=415, detail=exc.reason) from exc
    except UnsupportedDocument as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc
    except ManifestError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"The upload record at {config.UPLOAD_MANIFEST_PATH} is unreadable: {exc}",
        ) from exc

    # Everything from here on is one unit: rename, manifest update,
    # extraction, and the DB row all either land together or none of them do.
    # A failure at any point - including the manifest write right after the
    # rename - rolls the whole upload back, so a crash never leaves the
    # manifest pointing at a filename that no longer exists on disk (which
    # would orphan the file: nothing could resolve it via
    # config.document_path, and remove() would unlink the wrong name).
    #
    # Both manifest writes below go through uploads.update_entry(), which
    # re-reads the manifest immediately before writing and merges only this
    # contract_id's own fields - NOT a `manifest = uploads.read_manifest()`
    # captured once and reused across extraction. Extraction below takes
    # 60-75s against a live model; holding a manifest snapshot across that
    # gap and writing it back afterwards silently reverted every OTHER
    # manifest change made while it ran (e.g. a Remove of a different
    # upload succeeded - file unlinked, DB row deleted - and then got
    # resurrected in the manifest the moment this request finished, which a
    # later reseed would have turned back into a live contracts row). The
    # first write, right after the rename, has only a tiny window before
    # this fix - but the same defect, so it goes through update_entry() too
    # for the same reason, not just for symmetry.
    final_path = path.with_name(f"{contract_id}.txt")
    try:
        path.rename(final_path)
        if not uploads.update_entry(contract_id, {"stored_filename": final_path.name}):
            raise _UploadRemovedDuringProcessing(
                f"upload {contract_id} was removed before it could be finalized"
            )

        # Index BEFORE extracting, not after: the extraction agent works by
        # retrieving clause chunks for this contract_id, so an unindexed
        # document yields zero hits, ends the agentic loop on its first
        # iteration, and silently degrades to the offline regex - which is
        # tuned to the seed generator's phrasing and reads almost nothing off a
        # real contract. Incremental, because build_index() re-embeds every
        # document in the corpus to add one.
        # Both calls below are blocking (an embedding HTTP call, then up to 3
        # agentic LLM iterations at 16-27s each against Ollama) and must not
        # run directly on the event loop - this function is `async def` only
        # because it needs `await file.read()` above, so FastAPI schedules it
        # on the loop itself rather than in Starlette's request threadpool.
        # Without run_in_threadpool here, a single upload freezes every other
        # request (including GET /) for the full duration of extraction -
        # measured live at 61s. run_in_threadpool preserves the exact call
        # signature and exceptions raised below; it only moves where the call
        # runs, not the ordering or error handling around it.
        await run_in_threadpool(vector_store.index_document, contract_id, text)

        # extract_one already applies reconcile_costs internally (Task 3), so
        # no second application is done here - that would just be a
        # confusing no-op. NOTE: a poor extraction (the LLM path producing
        # nothing usable, falling back to the offline regex extractor) is
        # NOT an exception - extract_one handles that internally and still
        # returns a usable record. Rollback below is only for a genuine
        # exception (e.g. the LLM call itself blowing up).
        record = await run_in_threadpool(extraction.extract_one, contract_id, text)
        if not uploads.update_entry(contract_id, {"terms": record.model_dump(mode="json")}):
            # The user removed this exact upload while extraction was still
            # running. See _UploadRemovedDuringProcessing's docstring for why
            # the entry must not be re-added here.
            raise _UploadRemovedDuringProcessing(
                f"upload {contract_id} was removed while it was still processing"
            )
        dataset_tools.upsert_upload_row(record, original_filename)
    except Exception as exc:
        # A failed upload must leave no trace: no orphaned file under either
        # name, no stale manifest entry, no contracts row for an id nothing
        # else can reach.
        _discard_failed_upload(contract_id, path, final_path)
        raise HTTPException(
            status_code=500,
            detail=f"Could not process the uploaded contract; the upload was discarded: {exc}",
        ) from exc

    return {
        "contract_id": contract_id,
        "vendor": record.vendor,
        # The uploader needs to recognise their own file in the list. Vendor is
        # the natural label, but a weak extraction leaves it empty - and a row
        # showing nothing but "U-0023" is unidentifiable to the person who just
        # dragged a file in. The template already falls back to this; the JS
        # that inserts the row live could not, because the payload lacked it.
        "original_filename": original_filename,
        "renewal_date": record.renewal_date,
        "extraction_source": record.extraction_source,
        # The spec keeps a file whose extraction recovered little - but says so,
        # rather than presenting a guess as a reading. See
        # extraction.is_low_confidence for why "any unresolved field" was the
        # wrong test.
        "low_confidence": extraction.is_low_confidence(record),
    }


@app.post("/api/uploads/{contract_id}/remove")
def api_upload_remove(contract_id: str):
    from app.tools import dataset_tools, uploads
    from app.tools.uploads import ManifestError

    try:
        removed = uploads.remove(contract_id)
    except ManifestError as exc:
        # Same policy and same wording as /api/upload: one fault should not
        # report itself two different ways depending on which button was
        # pressed. Without this the user got a raw traceback.
        raise HTTPException(
            status_code=500,
            detail=f"The upload record at {config.UPLOAD_MANIFEST_PATH} is unreadable: {exc}",
        ) from exc

    if not removed:
        raise HTTPException(status_code=404, detail=f"No uploaded contract {contract_id}.")
    dataset_tools.delete_upload_row(contract_id)
    # Drop the contract's clause chunks too, or the index keeps citing a
    # document that no longer exists anywhere else in the system.
    vector_store.remove_document(contract_id)
    return {"removed": True}


def _uploaded_contracts() -> list[dict]:
    """Contracts uploaded via /api/upload, for the dashboard's upload card.

    The manifest is written before extraction runs, so an entry may not have
    a "terms" key yet - the template must tolerate that. A corrupt manifest
    must not take down the whole dashboard either: every other figure on this
    page is still valid, so this degrades to an empty list and logs, the same
    policy seed_db.rehydrate_uploads() uses for a reseed.

    low_confidence is computed here rather than in the template so the row and
    the post-upload status message answer the question the same way, from one
    definition."""
    from app.agents import extraction
    from app.tools import uploads

    try:
        entries = uploads.read_manifest()["entries"].values()
    except uploads.ManifestError as exc:
        print(f"[PACT] Upload list unavailable on dashboard - manifest is corrupt: {exc}")
        return []
    listed = [dict(entry, low_confidence=extraction.is_low_confidence(entry.get("terms")))
              for entry in entries]
    return sorted(listed, key=lambda e: e["contract_id"])


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
    ctx["uploads"] = _uploaded_contracts()
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


@app.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request):
    ctx = _base_context(request)
    ctx["runs"] = persistence.list_runs()
    return templates.TemplateResponse(request, "runs.html", ctx)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail_page(request: Request, run_id: str):
    detail = views.run_detail_view(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    ctx = _base_context(request)
    ctx.update(detail)
    return templates.TemplateResponse(request, "run_detail.html", ctx)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@app.get("/api/status")
def api_status():
    return {"llm_mode": get_mode(), "has_run": bool(_LAST_RUN),
            "summary": _LAST_RUN["summary"].model_dump(mode="json") if _LAST_RUN.get("summary") else None}


@app.get("/api/runs")
def api_runs():
    return {"runs": persistence.list_runs()}


async def _execute_pipeline(q: "queue_module.Queue") -> None:
    """Owns the pipeline's actual lifecycle - runs independently of whichever
    client's SSE connection happens to be watching it. A dropped connection
    (client timeout, closed tab) must not orphan a run mid-flight: real
    compute already spent calling the LLM would be silently wasted, and the
    lock would release while the run kept executing, letting a second run
    start and pile onto the same model instance.

    A pipeline-wide timeout guards the same lock against a genuinely hung
    run (observed for real: a local model slow enough to blow its own
    per-call timeout on every attempt). asyncio.to_thread's underlying
    thread can't actually be killed once it's running, so a timed-out run
    keeps burning CPU in the background - but since nothing here still
    awaits it, its result is simply never touched: no stale save, no lock
    left held.
    """
    global _LAST_RUN
    try:
        final_state = await asyncio.wait_for(
            asyncio.to_thread(run_pipeline, q), timeout=config.PIPELINE_TIMEOUT_SECONDS
        )
        _LAST_RUN = final_state
        _record_node_details(final_state)
        persistence.save_run(final_state)
    except asyncio.TimeoutError:
        # The orphaned run's own DONE_SENTINEL may arrive arbitrarily late
        # (or never) - event_stream() needs its own to stop waiting now.
        emit(q, "pipeline", "error",
             f"Run timed out after {config.PIPELINE_TIMEOUT_SECONDS:.0f}s")
        emit_done(q)
    except Exception:
        # run_pipeline() already emitted its own error event and
        # DONE_SENTINEL (in the correct order) before this exception
        # reached us - nothing left to do but skip the save.
        pass
    finally:
        _RUN_LOCK.release()


@app.get("/api/run")
async def api_run():
    if not _RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A pipeline run is already in progress")

    q = new_queue()
    asyncio.create_task(_execute_pipeline(q))

    async def event_stream():
        ok = True
        while True:
            item = await asyncio.to_thread(q.get)
            if isinstance(item, str) and item == DONE_SENTINEL:
                break
            if item.status == "error":
                ok = False
            yield item.to_sse()
        yield f"event: result\ndata: {json.dumps({'ok': ok})}\n\n"

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
