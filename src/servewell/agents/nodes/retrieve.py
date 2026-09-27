"""Hybrid KB retrieval for the ticket."""

from servewell.agents.state import AgentState
from servewell.config import get_settings
from servewell.models.schemas import GuardrailResult
from servewell.platform.retrieval import get_retriever


def build_query(state: AgentState) -> str:
    t, ctx = state["ticket"], state["enrichment"]
    parts = [
        "Printers", t.subcategory, state["masked_subject"], state["masked_description"],
        ctx.asset.asset_type if ctx.asset else None, ctx.system,
    ]
    return "\n".join(p for p in parts if p)


def retrieve_node(state: AgentState) -> dict:
    s = get_settings()
    query = build_query(state)
    retriever = get_retriever()
    # No hard category filter: printer fixes also live in POS docs (pos-printer-integration.md)
    chunks = retriever.search(query, category=None, top_k=s.retrieval_top_k)
    top = chunks[0].score if chunks else 0.0
    ok = top >= s.min_retrieval_score
    return {
        "retrieval_query": query,
        "retrieval_mode": retriever.last_mode,
        "chunks": chunks,
        "guardrails": [GuardrailResult(
            name="Retrieval confidence", passed=ok,
            detail=f"Top chunk score {top:.2f} (threshold {s.min_retrieval_score}) via {retriever.last_mode}")],
        "trace": [{"node": "retrieve", "summary": f"{len(chunks)} chunks; top: "
                   + (f"{chunks[0].chunk.doc_path} › {chunks[0].chunk.section}" if chunks else "none")}],
    }
