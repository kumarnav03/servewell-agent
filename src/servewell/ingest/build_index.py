"""Chunk the KB, embed with Ollama, and persist to Chroma (+ a JSONL copy for BM25)."""

import json
import shutil
import time

import chromadb
import ollama

from servewell.config import get_settings
from servewell.ingest.chunk_kb import chunk_kb, embedding_text

COLLECTION = "servewell_kb"
BATCH = 32


def chunks_path():
    return get_settings().storage_dir / "chunks.jsonl"


def embed_documents(texts: list[str]) -> list[list[float]]:
    s = get_settings()
    client = ollama.Client(host=s.ollama_host)
    # nomic-embed-text expects task prefixes
    resp = client.embed(model=s.embed_model, keep_alive="60m", input=[f"search_document: {t}" for t in texts])
    return resp["embeddings"]


def embed_query(text: str) -> list[float]:
    s = get_settings()
    client = ollama.Client(host=s.ollama_host)
    return client.embed(model=s.embed_model, keep_alive="60m", input=[f"search_query: {text}"])["embeddings"][0]


def build_index(progress=print) -> dict:
    s = get_settings()
    started = time.time()
    chunks = chunk_kb()
    progress(f"Chunked KB into {len(chunks)} chunks")

    s.storage_dir.mkdir(parents=True, exist_ok=True)
    with open(chunks_path(), "w") as f:
        for c in chunks:
            f.write(c.model_dump_json() + "\n")

    if s.chroma_dir.exists():
        shutil.rmtree(s.chroma_dir)
    client = chromadb.PersistentClient(path=str(s.chroma_dir))
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i : i + BATCH]
        col.add(
            ids=[c.chunk_id for c in batch],
            embeddings=embed_documents([embedding_text(c) for c in batch]),
            documents=[c.text for c in batch],
            metadatas=[
                {"doc_path": c.doc_path, "doc_type": c.doc_type, "category": c.category}
                for c in batch
            ],
        )
        progress(f"Embedded {min(i + BATCH, len(chunks))}/{len(chunks)}")

    stats = {
        "chunks": len(chunks),
        "docs": len({c.doc_path for c in chunks}),
        "seconds": round(time.time() - started, 1),
        "embed_model": s.embed_model,
    }
    (s.storage_dir / "index_meta.json").write_text(json.dumps(stats, indent=2))
    return stats
