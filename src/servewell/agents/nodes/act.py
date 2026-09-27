"""Execute actions against the simulated ITSM / automations. Every call is audited.

Auto-allowed actions run inside the graph; approval-gated ones run only when a human clicks
Approve in the UI (execute_action with approver set).
"""

from servewell.agents.state import AgentState
from servewell.observability import audit
from servewell.platform import itsm
from servewell.platform.automations import run_automation
from servewell.platform.itsm import dumps


def execute_action(state: AgentState, action_id: str, approver: str | None = None) -> str:
    t = state["ticket"]
    action = next(a for a in state["actions"] if a.action_id == action_id)
    if action.requires_approval and not approver:
        action.status = "blocked"
        audit.log(state["run_id"], t.ticket_id, "action_blocked", action.model_dump())
        return "Blocked: approval required"

    p = action.payload
    if action.kind == "post_work_note":
        itsm.post_comment(t.ticket_id, state["work_note"])
        result = "Work note posted"
    elif action.kind == "set_routing":
        itsm.upsert_incident(t, status="Triaged", routing=p["routing"], queue=p["queue"],
                             confidence=state["llm_decision"].confidence if state.get("llm_decision") else None)
        result = f"Routed to {p['queue']}"
    elif action.kind in ("send_guidance", "request_clarification", "redirect_non_it"):
        itsm.post_comment(t.ticket_id, state["requester_message"], visibility="requester")
        itsm.set_status(t.ticket_id, "Awaiting Store" if action.kind != "redirect_non_it" else "Resolved — Redirected")
        result = "Message sent to requester"
    elif action.kind == "escalate_l2":
        itsm.upsert_incident(t, status="Escalated", routing="l2_escalation", queue="L2 Support")
        itsm.post_comment(t.ticket_id, f"Escalated to L2. Reason: {p.get('reason')}\n\n{state['work_note']}")
        itsm.post_comment(t.ticket_id, state["requester_message"], visibility="requester")
        result = "Escalated to L2 Support (notification to it-l2@servewell.in simulated)"
    elif action.kind == "notify_oncall":
        result = "On-call notified (oncall@servewell.in — simulated)"
        itsm.post_comment(t.ticket_id, result)
    elif action.kind == "run_automation":
        out = run_automation(p["automation"], p.get("asset_id"))
        itsm.post_comment(t.ticket_id, f"Automation {p['automation']}: {out['message']}")
        result = out["message"]
    else:
        result = "Unknown action"

    action.status = "approved" if approver else "executed"
    audit.log(state["run_id"], t.ticket_id, f"action:{action.kind}",
              {"action": action.model_dump(), "result": result}, actor=approver or "agent")
    return result


def reject_action(state: AgentState, action_id: str, approver: str) -> None:
    action = next(a for a in state["actions"] if a.action_id == action_id)
    action.status = "rejected"
    audit.log(state["run_id"], state["ticket"].ticket_id, f"action_rejected:{action.kind}",
              action.model_dump(), actor=approver)


def act_node(state: AgentState) -> dict:
    if state.get("dry_run"):
        return {"trace": [{"node": "act", "summary": "dry run — no ITSM writes"}]}
    itsm.upsert_incident(state["ticket"], status="Open")
    done = [f"{a.action_id} {execute_action(state, a.action_id)}"
            for a in state["actions"] if not a.requires_approval]
    pending = sum(a.requires_approval for a in state["actions"])
    return {"actions": state["actions"],
            "trace": [{"node": "act", "summary": f"auto-executed: {done or 'none'}; awaiting approval: {pending}"}]}


__all__ = ["act_node", "execute_action", "reject_action", "dumps"]
