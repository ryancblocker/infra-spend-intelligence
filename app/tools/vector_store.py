"""
Purpose: Local, persistent semantic search over contract documents (RAG) used by
the extraction agent and the /ask endpoint, so answers cite real contract text
instead of being invented.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app import config
from app.tools.llm_client import embed_texts, embedding_backend

COLLECTION_NAME = "contract_docs"

# Pinned explicitly rather than left to Chroma's default: the relevance floors
# in config are calibrated to this metric's scale, so a silent default change
# would quietly break citation filtering.
VECTOR_SPACE = "l2"

# Contract docs use numbered sections in two styles:
#   "1. TERM AND RENEWAL. ..."   and   "4. Service Level Credits: ..."
SECTION_RE = re.compile(r"^(\d{1,2})\.\s+([A-Z][^\n:.]{2,60})[.:]", re.MULTILINE)


def chunk_document(text: str) -> list[dict]:
    """Split a contract into clause chunks, keeping each heading attached to its
    body so a retrieved chunk is a self-contained clause rather than a fragment.
    Falls back to paragraph splitting for documents without numbered sections."""
    matches = list(SECTION_RE.finditer(text))
    if not matches:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return [{"index": i, "heading": "", "text": p} for i, p in enumerate(paragraphs)]

    chunks: list[dict] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        chunks.append({"index": 0, "heading": "Preamble", "text": preamble})

    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        chunks.append({
            "index": len(chunks),
            "heading": f"{match.group(1)}. {match.group(2).strip()}",
            "text": text[match.start():end].strip(),
        })
    return chunks


def default_floor() -> float:
    """Distances from a real embedding model and from the hashed fallback are
    not on the same scale, so the relevance floor is chosen by backend."""
    return (config.RELEVANCE_FLOOR_EMBED if embedding_backend() == "ollama"
            else config.RELEVANCE_FLOOR_HASHED)


@lru_cache(maxsize=1)
def _client():
    import chromadb

    config.ensure_runtime_dirs()
    return chromadb.PersistentClient(path=str(config.VECTOR_STORE_DIR))


def index_needs_rebuild() -> bool:
    """True if the persisted collection's embedding dimension doesn't match the
    currently active embedding backend. Ollama's nomic-embed-text produces
    768-dim vectors; the offline hashed fallback produces 256-dim vectors
    (`llm_client.EMBED_DIM`). Chroma pins a collection's dimension at
    creation, so switching backends (e.g. testing offline, then installing
    Ollama - or the reverse) without rebuilding raises an opaque
    InvalidArgumentError deep inside a pipeline run instead of failing fast."""
    client = _client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        return True  # no collection yet - not a rebuild, just a first build

    stored_dim = (collection.metadata or {}).get("embedding_dim")
    if stored_dim is None:
        return True  # built before this check existed

    current_dim = len(embed_texts(["dimension probe"])[0])
    return stored_dim != current_dim


def build_index() -> int:
    """(Re)build the contract-document vector index from app/data/contract_docs/."""
    client = _client()
    existing = {c.name for c in client.list_collections()}
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)

    doc_paths = sorted(config.CONTRACT_DOCS_DIR.glob("*.txt"))
    if not doc_paths:
        client.create_collection(COLLECTION_NAME, metadata={"hnsw:space": VECTOR_SPACE})
        return 0

    ids, documents, metadatas = [], [], []
    for path in doc_paths:
        contract_id = path.stem
        for chunk in chunk_document(path.read_text(encoding="utf-8")):
            ids.append(f"{contract_id}::{chunk['index']}")
            documents.append(chunk["text"])
            metadatas.append({
                "contract_id": contract_id,
                "chunk_index": chunk["index"],
                "heading": chunk["heading"],
            })

    embeddings = embed_texts(documents)
    embedding_dim = len(embeddings[0]) if embeddings else None
    collection = client.create_collection(
        COLLECTION_NAME,
        metadata={"hnsw:space": VECTOR_SPACE, "embedding_dim": embedding_dim, "embedding_backend": embedding_backend()},
    )
    collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    return len(doc_paths)


def search(query: str, n_results: int = 5, contract_id: str | None = None,
           max_distance: float | None = None) -> list[dict]:
    """Semantic search over contract clause chunks.

    Returns [{contract_id, chunk_index, heading, text, distance}]. Hits weaker
    than `max_distance` are dropped so a weak match is never cited as the source
    of an extracted term."""
    client = _client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        return []

    floor = default_floor() if max_distance is None else max_distance
    where = {"contract_id": contract_id} if contract_id else None
    query_embedding = embed_texts([query])[0]
    results = collection.query(query_embeddings=[query_embedding], n_results=n_results, where=where)

    hits = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        if floor is not None and dist is not None and dist > floor:
            continue
        hits.append({
            "contract_id": meta.get("contract_id"),
            "chunk_index": meta.get("chunk_index", 0),
            "heading": meta.get("heading", ""),
            "text": doc,
            "distance": dist,
        })
    return hits
