"""
Purpose: Progress events emitted by orchestrator nodes as the pipeline runs,
consumed by the FastAPI SSE endpoint so the UI can show each agent lighting up
in real time instead of a single opaque "loading" spinner.

A plain stdlib queue.Queue (not asyncio.Queue) is used deliberately: the graph
itself runs synchronously in a worker thread (agent/LLM calls are blocking
I/O), and queue.Queue is the thread-safe way to hand events back to the async
FastAPI event loop that drains it.
"""

from __future__ import annotations

import json
import queue
import time
from typing import Any, Literal

from pydantic import BaseModel

DONE_SENTINEL = "__PIPELINE_DONE__"

NODE_LABELS = {
    "discovery": "Discovery",
    "extraction": "Contract Extraction",
    "waste": "Waste Detection",
    "benchmark": "Benchmark Analysis",
    "renewal": "Renewal Intelligence",
    "optimization": "Optimization Strategy",
    "critic": "Critic Review",
    "narrator": "Executive Narrator",
}


class AgentEvent(BaseModel):
    node: str
    label: str
    status: Literal["started", "completed", "error"]
    detail: str = ""
    timestamp: float = 0.0

    def to_sse(self) -> str:
        return f"data: {self.model_dump_json()}\n\n"


def new_queue() -> "queue.Queue[Any]":
    return queue.Queue()


def emit(event_queue: "queue.Queue[Any] | None", node: str, status: str, detail: str = "") -> None:
    if event_queue is None:
        return
    event = AgentEvent(node=node, label=NODE_LABELS.get(node, node), status=status,
                        detail=detail, timestamp=time.time())
    event_queue.put(event)


def emit_done(event_queue: "queue.Queue[Any] | None") -> None:
    if event_queue is not None:
        event_queue.put(DONE_SENTINEL)
