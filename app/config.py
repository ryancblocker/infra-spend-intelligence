"""
Purpose: Central configuration for PACT - paths, LLM backend selection, and model names.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent

DATA_DIR = APP_DIR / "data"
SEED_DIR = DATA_DIR / "seed"
CONTRACT_DOCS_DIR = DATA_DIR / "contract_docs"

RUNTIME_DIR = BASE_DIR / "runtime"
DB_PATH = RUNTIME_DIR / "pact.db"
VECTOR_STORE_DIR = RUNTIME_DIR / "vector_store"

STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

# --- LLM backend ---
# "auto" probes Ollama first, then Anthropic, then falls back to the offline
# deterministic mode so the app always runs, even with nothing installed.
LLM_MODE = os.environ.get("PACT_LLM_MODE", "auto").strip().lower()

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# qwen3:1.7b, not a larger sibling: this runs on an 8 GB unified-memory Mac,
# where qwen3:8b (~5.2 GB resident) leaves too little for the OS and hangs the
# machine outright. Size up only on a box with real memory headroom.
OLLAMA_CHAT_MODEL = os.environ.get("PACT_OLLAMA_MODEL", "qwen3:1.7b")
OLLAMA_EMBED_MODEL = os.environ.get("PACT_OLLAMA_EMBED_MODEL", "nomic-embed-text")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("PACT_ANTHROPIC_MODEL", "claude-sonnet-5")

# Reference date used for renewal-window math; overridable for reproducible demos.
REFERENCE_DATE = os.environ.get("PACT_REFERENCE_DATE", "")

HIGH_VALUE_THRESHOLD = 50_000
LOW_SAVINGS_THRESHOLD = 10_000

# --- Agent loop controls ---
# Both are hard caps enforced in Python, not left to the model's judgement: a
# small local model cannot reliably decide when it is finished.
MAX_EXTRACTION_ITERS = int(os.environ.get("PACT_MAX_EXTRACTION_ITERS", "3"))
MAX_REVISIONS = int(os.environ.get("PACT_MAX_REVISIONS", "1"))
LLM_TIMEOUT_SECONDS = float(os.environ.get("PACT_LLM_TIMEOUT", "120"))

# --- Retrieval ---
RETRIEVAL_K = int(os.environ.get("PACT_RETRIEVAL_K", "3"))
# Chroma is pinned to squared-L2 (see vector_store.VECTOR_SPACE). On the unit-
# normalized vectors both embedding paths produce, that puts distances on a
# [0, 2] scale where 2.0 means orthogonal - i.e. no shared signal at all.
#
# Measured against C-0007 with hashed embeddings: correct clauses land at
# 1.23-1.48, irrelevant chunks at 2.0. 1.90 keeps every correct match while
# dropping pure noise.
RELEVANCE_FLOOR_HASHED = float(os.environ.get("PACT_RELEVANCE_FLOOR_HASHED", "1.90"))
# nomic-embed-text separates relevant from irrelevant far more sharply, so this
# can be tighter. NOT YET VERIFIED against a real model - confirm during the
# Ollama end-to-end run before trusting it.
RELEVANCE_FLOOR_EMBED = float(os.environ.get("PACT_RELEVANCE_FLOOR_EMBED", "1.50"))

# --- Observability & caching ---
LLM_LOG_PATH = RUNTIME_DIR / "llm_calls.jsonl"
EXTRACTION_CACHE_PATH = RUNTIME_DIR / "extraction_cache.json"
EXTRACTION_CACHE_ENABLED = os.environ.get("PACT_EXTRACTION_CACHE", "1") != "0"

# Skip restoring a persisted run at startup, so the app opens on the welcome
# screen with nothing calculated. Persistence itself stays on - this only
# controls whether a previous run is loaded back in. Useful for demoing the
# full arc from zero.
FRESH_START = os.environ.get("PACT_FRESH_START", "0") == "1"


def ensure_runtime_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
