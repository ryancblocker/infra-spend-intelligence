"""
Purpose: Local, persistent semantic search over contract documents (RAG) used by
the extraction agent and the /ask endpoint, so answers cite real contract text
instead of being invented.
"""

from __future__ import annotations

from functools import lru_cache

from app import config
from app.tools.llm_client import embed_texts

COLLECTION_NAME = "contract_docs"


@lru_cache(maxsize=1)
def _client():
    import chromadb

    config.ensure_runtime_dirs()
    return chromadb.PersistentClient(path=str(config.VECTOR_STORE_DIR))


def build_index() -> int:
    """(Re)build the contract-document vector index from app/data/contract_docs/."""
    client = _client()
    existing = {c.name for c in client.list_collections()}
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(COLLECTION_NAME)

    doc_paths = sorted(config.CONTRACT_DOCS_DIR.glob("*.txt"))
    if not doc_paths:
        return 0

    ids, documents, metadatas = [], [], []
    for path in doc_paths:
        contract_id = path.stem
        text = path.read_text(encoding="utf-8")
        for idx, chunk in enumerate(p for p in text.split("\n\n") if p.strip()):
            ids.append(f"{contract_id}::{idx}")
            documents.append(chunk)
            metadatas.append({"contract_id": contract_id, "chunk_index": idx})

    embeddings = embed_texts(documents)
    collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    return len(doc_paths)


def search(query: str, n_results: int = 5, contract_id: str | None = None) -> list[dict]:
    """Semantic search over contract clause chunks. Returns [{contract_id, text, distance}]."""
    client = _client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        return []

    where = {"contract_id": contract_id} if contract_id else None
    query_embedding = embed_texts([query])[0]
    results = collection.query(query_embeddings=[query_embedding], n_results=n_results, where=where)

    hits = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        hits.append({"contract_id": meta.get("contract_id"), "text": doc, "distance": dist})
    return hits
