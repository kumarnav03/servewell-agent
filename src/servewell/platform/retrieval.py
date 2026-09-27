"""Simulated platform 'RAG' service: hybrid BM25 + dense retrieval over KB chunks.

- BM25 catches exact tokens (error codes like ERR-4521, versions like v4.2.1, model numbers).
- Dense (nomic-embed-text in Chroma) catches paraphrases ("won't turn on" ~ "startup failure").
- Reciprocal Rank Fusion merges both without needing comparable score scales.
- A soft category prior favours the ticket's category (plus General SOPs) without hard-filtering,
  so miscategorised tickets can still reach the right domain.
If Ollama is unavailable, the retriever degrades to BM25-only and says so.
"""

import json
import re
from functools import lru_cache

import chromadb
from rank_bm25 import BM25Okapi

from servewell.config import get_settings
from servewell.ingest.build_index import COLLECTION, chunks_path, embed_query
from servewell.ingest.chunk_kb import embedding_text
from servewell.models.schemas import KBChunk, RetrievedChunk

RRF_K = 60
CANDIDATES = 40
OFF_CATEGORY_WEIGHT = 0.6

STOPWORDS = set(
    "a an and are as at be but by can do does for from has have i if in is it its my not of on or "
    "our so that the this to was we were what when with you your me it's won't can't please".split()
)


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+(?:[-.][a-z0-9]+)*", text.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


class HybridRetriever:
    def __init__(self):
        s = get_settings()
        with open(chunks_path()) as f:
            self.chunks = [KBChunk.model_validate_json(line) for line in f]
        self.by_id = {c.chunk_id: c for c in self.chunks}
        self.bm25 = BM25Okapi([tokenize(embedding_text(c)) for c in self.chunks])
        self.collection = chromadb.PersistentClient(path=str(s.chroma_dir)).get_collection(COLLECTION)
        self.last_mode = "hybrid"

    def _bm25_ranks(self, query: str) -> dict[str, int]:
        scores = self.bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:CANDIDATES]
        return {self.chunks[i].chunk_id: r for r, i in enumerate(order, 1) if scores[i] > 0}

    def _dense_ranks(self, query: str) -> tuple[dict[str, int], dict[str, float]]:
        res = self.collection.query(query_embeddings=[embed_query(query)], n_results=CANDIDATES)
        ids, dists = res["ids"][0], res["distances"][0]
        return {cid: r for r, cid in enumerate(ids, 1)}, {cid: 1 - d for cid, d in zip(ids, dists)}

    def search(
        self,
        query: str,
        category: str | None = None,
        top_k: int | None = None,
        doc_types: set[str] | None = None,
    ) -> list[RetrievedChunk]:
        top_k = top_k or get_settings().retrieval_top_k
        bm25 = self._bm25_ranks(query)
        try:
            dense, sims = self._dense_ranks(query)
            self.last_mode = "hybrid"
        except Exception:
            dense, sims = {}, {}
            self.last_mode = "bm25-only (embedding service unavailable)"

        max_rrf = (2 if dense else 1) / (RRF_K + 1)
        fused = []
        for cid in set(bm25) | set(dense):
            chunk = self.by_id[cid]
            if doc_types and chunk.doc_type not in doc_types:
                continue
            rrf = sum(1 / (RRF_K + ranks[cid]) for ranks in (bm25, dense) if cid in ranks)
            if category and chunk.category not in (category, "General"):
                rrf *= OFF_CATEGORY_WEIGHT
            fused.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=round(rrf / max_rrf, 4),
                    bm25_rank=bm25.get(cid),
                    dense_rank=dense.get(cid),
                    dense_similarity=round(sims[cid], 4) if cid in sims else None,
                )
            )
        fused.sort(key=lambda r: r.score, reverse=True)
        return fused[:top_k]

    def search_docs(self, query: str, category: str | None = None, top_k: int = 6) -> list[str]:
        """Doc-level ranking (best chunk per doc) — used for evaluation against relevant_kb_docs."""
        docs: list[str] = []
        for r in self.search(query, category, top_k=CANDIDATES):
            if r.chunk.doc_path not in docs:
                docs.append(r.chunk.doc_path)
        return docs[:top_k]


def ticket_query(ticket) -> str:
    """Retrieval query built from the ticket fields that carry symptom signal."""
    parts = [ticket.category, ticket.subcategory, ticket.subject, ticket.description, ticket.system_version]
    return "\n".join(p for p in parts if p)


def index_exists() -> bool:
    s = get_settings()
    return chunks_path().exists() and s.chroma_dir.exists()


@lru_cache
def get_retriever() -> HybridRetriever:
    return HybridRetriever()


def index_meta() -> dict | None:
    p = get_settings().storage_dir / "index_meta.json"
    return json.loads(p.read_text()) if p.exists() else None
