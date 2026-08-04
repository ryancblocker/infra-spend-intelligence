"""
Purpose: Wire the eight agents into a LangGraph StateGraph following the
Orchestrator-Worker + Reflection pattern: Discovery fans out to four
independent workers (Extraction, Waste, Benchmark, Renewal), those join into
Optimization, which is checked by the Critic (reflection) before the Narrator
synthesizes the executive summary.

Progress events are derived from graph.stream(..., stream_mode="updates")
rather than threaded through node config: LangGraph deep-copies config across
parallel branches, so a mutable queue stashed in config silently forks into
per-branch copies the caller never sees. Streaming node outputs as they
complete sidesteps that entirely.
"""

from __future__ import annotations

import queue as queue_module

from langgraph.graph import END, START, StateGraph

from app import config
from app.agents import benchmark, critic, discovery, extraction, narrator, optimization, renewal, waste
from app.orchestrator.events import emit, emit_done
from app.orchestrator.state import PipelineState


def discovery_node(state: PipelineState) -> dict:
    result = discovery.run()
    return {"discovery": result}


def extraction_node(state: PipelineState) -> dict:
    result = extraction.run()
    return {"extracted_contracts": result}


def waste_node(state: PipelineState) -> dict:
    result = waste.run()
    return {"waste_findings": result}


def benchmark_node(state: PipelineState) -> dict:
    findings, narrative = benchmark.run()
    return {"benchmark_findings": findings, "benchmark_narrative": narrative}


def renewal_node(state: PipelineState) -> dict:
    risks, narrative = renewal.run()
    return {"renewal_risks": risks, "renewal_narrative": narrative}


def optimization_node(state: PipelineState) -> dict:
    """Runs in two modes. On the first pass it scores every finding. When the
    critic has routed objections back, it regenerates only the flagged
    judgements and leaves all cost math untouched."""
    requests = state.get("revision_requests") or []
    if requests:
        revised = optimization.revise(state.get("scenarios", []), requests)
        return {
            "scenarios": revised,
            "revision_count": state.get("revision_count", 0) + 1,
            "revision_requests": [],
        }

    all_findings = list(state.get("waste_findings", [])) + list(state.get("benchmark_findings", []))
    return {"scenarios": optimization.run(all_findings), "revision_count": 0,
            "revision_requests": []}


def critic_node(state: PipelineState) -> dict:
    reviewed, flags = critic.run(state.get("scenarios", []))
    return {
        "scenarios": reviewed,
        "critic_flags": flags,
        "revision_requests": critic.build_revision_requests(flags),
    }


def route_after_critic(state: PipelineState) -> str:
    """The reflection loop's gate. Deterministic and hard-capped: the model never
    decides whether to keep going."""
    if state.get("revision_requests") and state.get("revision_count", 0) < config.MAX_REVISIONS:
        return "revise"
    return "done"


def narrator_node(state: PipelineState) -> dict:
    all_findings = list(state.get("waste_findings", [])) + list(state.get("benchmark_findings", []))
    summary = narrator.run(
        state["discovery"], all_findings, state.get("renewal_risks", []),
        state.get("scenarios", []), state.get("critic_flags", []),
    )
    return {"summary": summary}


def build_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("discovery", discovery_node)
    graph.add_node("extraction", extraction_node)
    graph.add_node("waste", waste_node)
    graph.add_node("benchmark", benchmark_node)
    graph.add_node("renewal", renewal_node)
    graph.add_node("optimization", optimization_node)
    graph.add_node("critic", critic_node)
    graph.add_node("narrator", narrator_node)

    graph.add_edge(START, "discovery")
    for worker in ("extraction", "waste", "benchmark", "renewal"):
        graph.add_edge("discovery", worker)
        graph.add_edge(worker, "optimization")
    graph.add_edge("optimization", "critic")
    graph.add_conditional_edges("critic", route_after_critic,
                                {"revise": "optimization", "done": "narrator"})
    graph.add_edge("narrator", END)

    return graph.compile()


_COMPILED_GRAPH = None


def get_graph():
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = build_graph()
    return _COMPILED_GRAPH


def _detail_for(node: str, output: dict) -> str:
    if node == "discovery":
        d = output["discovery"]
        return f"${d.total_annual_spend:,.0f} total annual spend across {d.asset_counts.get('contracts', 0)} contracts"
    if node == "extraction":
        contracts = output["extracted_contracts"]
        sources = sorted({c.extraction_source for c in contracts})
        return f"{len(contracts)} contracts parsed ({', '.join(sources)})"
    if node == "waste":
        return f"{len(output['waste_findings'])} utilization findings"
    if node == "benchmark":
        return f"{len(output['benchmark_findings'])} above-benchmark items"
    if node == "renewal":
        risks = output["renewal_risks"]
        high = sum(1 for r in risks if r.risk == "HIGH")
        return f"{len(risks)} contracts in renewal window ({high} high risk)"
    if node == "optimization":
        return f"{len(output['scenarios'])} recommendations scored"
    if node == "critic":
        return f"{len(output['critic_flags'])} flags raised across {len(output['scenarios'])} recommendations"
    if node == "narrator":
        return f"${output['summary'].total_potential_annual_savings:,.0f} in identified savings"
    return ""


def run_pipeline(event_queue: "queue_module.Queue | None" = None) -> PipelineState:
    """Synchronous full pipeline run. Call via asyncio.to_thread() from async
    callers (e.g. the FastAPI SSE route) so the event loop isn't blocked
    during LLM calls."""
    graph = get_graph()
    final_state: PipelineState = {}
    try:
        for chunk in graph.stream({}, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                final_state.update(node_output)
                emit(event_queue, node_name, "completed", _detail_for(node_name, node_output))
    except Exception as exc:
        # Emitted here (not by the caller) so it lands on the queue before
        # DONE_SENTINEL - a caller reacting to the exception after this
        # function returns would already be too late to order it correctly.
        emit(event_queue, "pipeline", "error", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        emit_done(event_queue)
    return final_state
