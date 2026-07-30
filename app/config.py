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


def ensure_runtime_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
