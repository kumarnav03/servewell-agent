"""Enrichment via deterministic platform tools (no LLM)."""

from servewell.agents.state import AgentState
from servewell.platform.data_access import get_data_service


def enrich_node(state: AgentState) -> dict:
    ctx = get_data_service().enrich(state["ticket"])
    summary = (
        f"store={'✓' if ctx.store else '✗'} asset={'✓' if ctx.asset else '✗'} "
        f"system={ctx.system} {ctx.version or ''} | flags: {', '.join(f.code for f in ctx.flags) or 'none'}"
    )
    return {"enrichment": ctx, "trace": [{"node": "enrich", "summary": summary}]}
