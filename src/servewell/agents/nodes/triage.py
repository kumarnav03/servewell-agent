"""The single LLM step: triage + grounded resolution plan in one structured call.

One call (instead of separate triage/resolve calls) halves latency on a local 7B model; the
deterministic guard/policy node afterwards is what makes the output safe.
"""

from servewell.agents.llm import chat_structured, load_prompt
from servewell.agents.state import AgentState
from servewell.models.schemas import LLMDecision

PROMPT_VERSION = "triage_resolve_v1"
MAX_CHUNK_WORDS = 300


def _facts(state: AgentState) -> str:
    t, ctx = state["ticket"], state["enrichment"]
    lines = [
        f"Priority: {t.priority}",
        f"Store: {ctx.store.store_name} ({ctx.store.store_type})" if ctx.store else f"Store: {t.store_id} (NOT in store master)",
        (f"Asset: {ctx.asset.asset_id} — {ctx.asset.asset_type}, {ctx.asset.make} {ctx.asset.model}, "
         f"{ctx.asset.system_version}, warranty until {ctx.asset.warranty_expiry}") if ctx.asset
        else f"Asset: {t.asset_id or 'none given'} (NOT found in CMDB)",
        f"System version on ticket: {t.system_version or 'not given'}",
    ]
    if ctx.known_issue:
        lines.append(f"Version matrix: known bugs = {ctx.known_issue.known_bugs}; patch = {ctx.known_issue.patch_available}")
    if ctx.sla and ctx.sla.escalate_to_l2_by:
        lines.append(f"SLA: first response {ctx.sla.first_response_minutes} min, escalate to L2 within "
                     f"{ctx.sla.escalation_to_l2_minutes} min")
    lines.append("Pre-flagged for escalation by submitter/L1: yes" if t.escalation_flag else "Pre-flagged for escalation: no")
    if ctx.flags:
        lines.append("Data checks: " + "; ".join(f"{f.code}: {f.message}" for f in ctx.flags))
    if ctx.history_summary:
        lines.append("Ticket history:\n" + "\n".join(f"  - {h}" for h in ctx.history_summary))
    else:
        lines.append("Ticket history: none (no troubleshooting recorded yet)")
    return "\n".join(lines)


def _excerpts(state: AgentState) -> str:
    out = []
    for i, rc in enumerate(state["chunks"], 1):
        words = rc.chunk.text.split()
        text = " ".join(words[:MAX_CHUNK_WORDS]) + (" …" if len(words) > MAX_CHUNK_WORDS else "")
        out.append(f"[C{i}] {rc.chunk.doc_path} › {rc.chunk.section}\n{text}")
    return "\n\n".join(out)


def build_user_message(state: AgentState) -> str:
    t = state["ticket"]
    return (
        f"# Incident {t.ticket_id}\n"
        f"Category/subcategory as filed: {t.category} / {t.subcategory}\n"
        f"Subject: {state['masked_subject']}\n"
        f"Description: {state['masked_description']}\n\n"
        f"# Verified facts (from ServeWell systems)\n{_facts(state)}\n\n"
        f"# Knowledge-base excerpts\n{_excerpts(state)}\n\n"
        "Return the JSON decision."
    )


def triage_node(state: AgentState) -> dict:
    user = build_user_message(state)
    try:
        decision, meta = chat_structured(load_prompt(PROMPT_VERSION), user, LLMDecision)
        meta.update(prompt_version=PROMPT_VERSION, user_message=user)
        summary = f"routing={decision.routing} conf={decision.confidence:.2f} steps={len(decision.steps)} ({meta['latency_ms']/1000:.1f}s)"
        return {"llm_decision": decision, "llm_meta": meta, "llm_error": None,
                "trace": [{"node": "llm_triage", "summary": summary, "ms": meta["latency_ms"]}]}
    except Exception as e:  # LLM down or unparseable twice -> fail safe to a human
        return {"llm_decision": None, "llm_meta": {"user_message": user}, "llm_error": str(e),
                "trace": [{"node": "llm_triage", "summary": f"LLM failed: {e}"}]}
