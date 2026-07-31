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
OLLAMA_CHAT_MODEL = os.environ.get("PACT_OLLAMA_MODEL", "qwen3:8b")
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
# Distances from nomic-embed-text and from the hashed fallback are not on the
# same scale, so the floor is chosen by whichever embedding path produced the
# vector. See vector_store.default_floor().
RELEVANCE_FLOOR_EMBED = float(os.environ.get("PACT_RELEVANCE_FLOOR_EMBED", "0.75"))
RELEVANCE_FLOOR_HASHED = float(os.environ.get("PACT_RELEVANCE_FLOOR_HASHED", "0.95"))

# --- Observability & caching ---
LLM_LOG_PATH = RUNTIME_DIR / "llm_calls.jsonl"
EXTRACTION_CACHE_PATH = RUNTIME_DIR / "extraction_cache.json"
EXTRACTION_CACHE_ENABLED = os.environ.get("PACT_EXTRACTION_CACHE", "1") != "0"


def ensure_runtime_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
