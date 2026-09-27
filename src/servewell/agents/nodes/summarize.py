"""Requester message and ticket work note — assembled deterministically from checked content.

Only grounded steps reach the requester, so an ungrounded LLM claim can never be sent to a store.
"""

from servewell.agents.state import AgentState


def _sla_text(state: AgentState) -> str:
    sla = state["enrichment"].sla
    if not sla:
        return "shortly"
    hours = sla.resolution_target_minutes / 60
    return f"within {hours:g} hours" if hours >= 1 else f"within {sla.resolution_target_minutes} minutes"


def requester_message(state: AgentState) -> str:
    t, routing = state["ticket"], state["final_routing"]
    d = state.get("llm_decision")
    name = (t.submitted_by or "there").split()[0]
    intro = d.requester_intro if d else "Thanks for reporting this."
    grounded = [s for s in state.get("steps", []) if s.grounded]

    if routing in ("l1_guided", "l1_self_service") and grounded:
        body = "\n".join(f"{i}. {s.text}" for i, s in enumerate(grounded, 1))
        return (f"Hi {name},\n\n{intro}\n\nPlease try these steps in order:\n{body}\n\n"
                "Reply **fixed** if the printer works again, or **still not working** and we will "
                "escalate it to our specialist team straight away.")
    if routing == "l2_escalation":
        collect = ("\n\nWhile you wait, it helps if you can:\n"
                   + "\n".join(f"- {s.text}" for s in grounded[:3])) if grounded else ""
        return (f"Hi {name},\n\n{intro}\n\nYour issue has been escalated to our specialist team. "
                f"You can expect an update {_sla_text(state)}.{collect}")
    if routing == "needs_clarification":
        qs = "\n".join(f"- {q}" for q in (d.info_needed if d else [])) or "- Which printer and what exactly happens?"
        return f"Hi {name},\n\n{intro}\n\nTo help you quickly, could you tell us:\n{qs}"
    if routing == "non_it":
        return (f"Hi {name},\n\n{intro}\n\nThis doesn't look like an IT systems issue, so IT support "
                "can't resolve it directly. Please contact your Store/Regional Manager or HR, who "
                "can help with this. If there is also a device problem, reply and we'll pick it up.")
    return (f"Hi {name},\n\nThanks for reporting this. A member of the IT support team will "
            f"review your ticket and respond {_sla_text(state)}.")


def work_note(state: AgentState) -> str:
    t, ctx, d = state["ticket"], state["enrichment"], state.get("llm_decision")
    lines = [
        f"**Automated triage — {t.ticket_id}** (run {state['run_id']})",
        f"- Final routing: **{state['final_routing']}**"
        + (f" (model said {d.routing}, confidence {d.confidence:.2f})" if d else ""),
        f"- Human review required: {'YES — ' + '; '.join(state['review_reasons']) if state['needs_review'] else 'no'}",
    ]
    if d:
        lines += [f"- Rationale: {d.rationale}", f"- Root-cause hypothesis: {d.root_cause_hypothesis}"]
        if d.l1_steps_already_tried:
            lines.append("- Already tried: " + "; ".join(d.l1_steps_already_tried))
        if d.escalation_reason and state["final_routing"] == "l2_escalation":
            lines.append(f"- Escalation reason: {d.escalation_reason}")
    for o in state.get("overrides", []):
        lines.append(f"- Policy override `{o.rule}`: {o.before} → {o.after} ({o.reason})")
    if ctx.asset:
        lines.append(f"- Asset: {ctx.asset.asset_id} {ctx.asset.make} {ctx.asset.system_version}, "
                     f"warranty {ctx.asset.warranty_expiry}")
    if ctx.flags:
        lines.append("- Data flags: " + ", ".join(f.code for f in ctx.flags))
    if ctx.sla and ctx.sla.escalate_to_l2_by:
        lines.append(f"- SLA: escalate to L2 by {ctx.sla.escalate_to_l2_by:%Y-%m-%d %H:%M}, "
                     f"resolve by {ctx.sla.resolution_due:%Y-%m-%d %H:%M}")
    cited = sorted({state["chunks"][int(c[1:]) - 1].chunk.doc_path
                    for s in state.get("steps", []) if s.grounded for c in s.citations})
    if cited:
        lines.append("- KB used: " + ", ".join(cited))
    return "\n".join(lines)


def summarize_node(state: AgentState) -> dict:
    return {
        "requester_message": requester_message(state),
        "work_note": work_note(state),
        "trace": [{"node": "summarize", "summary": "Requester message + work note drafted"}],
    }
