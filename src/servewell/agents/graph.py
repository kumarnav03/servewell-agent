"""LangGraph wiring for the Printers pilot.

intake → input_guard → scope_check ─┬─(in scope)→ enrich → retrieve → llm_triage → output_guard → summarize → act → END
                                     └─(out of scope)→ enrich → out_of_scope → summarize → act → END

Approval-gated actions are left 'proposed' by `act`; the UI executes them after a human approves.
"""

import time
import uuid
from functools import lru_cache, wraps

from langgraph.graph import END, START, StateGraph

from servewell.agents.nodes.act import act_node
from servewell.agents.nodes.enrich import enrich_node
from servewell.agents.nodes.guard import guard_node, out_of_scope_node
from servewell.agents.nodes.intake import input_guard_node, intake_node, scope_node
from servewell.agents.nodes.retrieve import retrieve_node
from servewell.agents.nodes.summarize import summarize_node
from servewell.agents.nodes.triage import triage_node
from servewell.agents.state import AgentState
from servewell.observability import audit


def traced(name: str, fn):
    """Time each node, stamp it on the trace entry and write it to the audit log."""

    @wraps(fn)
    def wrapper(state: AgentState) -> dict:
        started = time.time()
        update = fn(state)
        ms = int((time.time() - started) * 1000)
        for entry in update.get("trace", []):
            entry.setdefault("ms", ms)
        ticket = update.get("ticket") or state.get("ticket")
        audit.log(state["run_id"], ticket.ticket_id if ticket else "?", f"node:{name}",
                  {"summary": " | ".join(e["summary"] for e in update.get("trace", []))}, latency_ms=ms)
        return update

    return wrapper


def after_enrich(state: AgentState) -> str:
    return "retrieve" if state["in_scope"] else "out_of_scope"


@lru_cache
def build_graph():
    g = StateGraph(AgentState)
    nodes = {
        "intake": intake_node, "input_guard": input_guard_node, "scope_check": scope_node,
        "enrich": enrich_node, "retrieve": retrieve_node, "llm_triage": triage_node,
        "output_guard": guard_node, "out_of_scope": out_of_scope_node,
        "summarize": summarize_node, "act": act_node,
    }
    for name, fn in nodes.items():
        g.add_node(name, traced(name, fn))
    g.add_edge(START, "intake")
    g.add_edge("intake", "input_guard")
    g.add_edge("input_guard", "scope_check")
    g.add_edge("scope_check", "enrich")
    g.add_conditional_edges("enrich", after_enrich, {"retrieve": "retrieve", "out_of_scope": "out_of_scope"})
    g.add_edge("retrieve", "llm_triage")
    g.add_edge("llm_triage", "output_guard")
    g.add_edge("output_guard", "summarize")
    g.add_edge("out_of_scope", "summarize")
    g.add_edge("summarize", "act")
    g.add_edge("act", END)
    return g.compile()


def initial_state(raw: dict, supervised: bool = True, dry_run: bool = False) -> AgentState:
    return {"run_id": uuid.uuid4().hex[:8], "raw": raw, "supervised": supervised, "dry_run": dry_run,
            "guardrails": [], "trace": []}


def run_ticket(raw: dict, supervised: bool = True, dry_run: bool = False) -> AgentState:
    return build_graph().invoke(initial_state(raw, supervised, dry_run))


def stream_ticket(raw: dict, supervised: bool = True):
    """Yields (node_name, partial_update, accumulated_state) for live UI progress."""
    state = initial_state(raw, supervised)
    for chunk in build_graph().stream(state, stream_mode="updates"):
        for node, update in chunk.items():
            for key, value in (update or {}).items():
                if key in ("guardrails", "trace"):
                    state[key] = state.get(key, []) + value
                else:
                    state[key] = value
            yield node, update, state
