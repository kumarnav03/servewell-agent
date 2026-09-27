"""Deterministic policy layer: SOP escalation rules and the autonomy line.

The LLM proposes; policy disposes. Every override is recorded with its reason so the
reviewer (and the audit log) can see exactly why the final routing differs from the model's.
"""

from servewell.config import get_settings
from servewell.models.schemas import (
    EnrichedContext,
    GuidanceStep,
    LLMDecision,
    PolicyOverride,
    ProposedAction,
    Ticket,
)

# Actions the agent may take without a human. Everything else needs approval.
AUTO_ACTIONS = {"post_work_note", "set_routing"}
ALLOWED_AUTOMATIONS = {"restart_print_spooler", "clear_print_queue", "send_test_print"}


def apply_policy(
    ticket: Ticket,
    ctx: EnrichedContext,
    decision: LLMDecision,
    steps: list[GuidanceStep],
    signals: dict,
) -> tuple[str, list[PolicyOverride], bool, list[str]]:
    """Returns (final_routing, overrides, needs_human_review, review_reasons)."""
    s = get_settings()
    routing = decision.routing
    overrides: list[PolicyOverride] = []
    review: list[str] = []

    def override(rule: str, new: str, reason: str):
        nonlocal routing
        if new != routing:
            overrides.append(PolicyOverride(rule=rule, before=routing, after=new, reason=reason))
            routing = new

    flag_codes = {f.code for f in ctx.flags}

    if signals.get("injection"):
        review.append("Possible prompt-injection text in ticket")

    if "UNKNOWN_SYSTEM" in flag_codes and routing in ("l1_guided", "l1_self_service"):
        override("unknown_system", "l2_escalation",
                 "System/version is not in the version matrix — the KB cannot be trusted for it.")

    if signals.get("non_it_terms") and routing != "non_it":
        review.append(f"Non-IT terms present ({', '.join(signals['non_it_terms'])}) but model routed '{routing}'")

    grounded = [st for st in steps if st.grounded]
    if routing in ("l1_guided", "l1_self_service") and not grounded:
        override("no_grounded_steps", "l2_escalation",
                 "Model proposed an L1 fix but none of its steps are supported by the KB.")

    if ticket.priority == "P1" and routing in ("l1_guided", "l1_self_service"):
        review.append("P1 incident — L1 guidance allowed, but a human must confirm")

    if decision.confidence < s.min_triage_confidence:
        review.append(f"Model confidence {decision.confidence:.2f} < {s.min_triage_confidence}")

    if "ASSET_NOT_FOUND" in flag_codes or "STORE_UNKNOWN" in flag_codes:
        review.append("Ticket references an asset/store that is not in the CMDB")

    return routing, overrides, bool(review), review


def propose_actions(
    ticket: Ticket,
    routing: str,
    decision: LLMDecision,
    steps: list[GuidanceStep],
    needs_review: bool,
    supervised: bool = True,
) -> list[ProposedAction]:
    """supervised=True: every message to the store waits for a human (pilot default)."""
    outbound_approval = needs_review or supervised
    actions: list[ProposedAction] = []

    def add(kind, title, payload=None, approval=None):
        requires = approval if approval is not None else kind not in AUTO_ACTIONS
        actions.append(ProposedAction(action_id=f"A{len(actions) + 1}", kind=kind, title=title,
                                      payload=payload or {}, requires_approval=requires))

    add("post_work_note", "Post triage work note to the ticket")
    add("set_routing", f"Set routing to '{routing}' and assign queue",
        {"routing": routing, "queue": queue_for(routing)}, approval=needs_review)

    if routing in ("l1_guided", "l1_self_service"):
        add("send_guidance", "Send grounded step-by-step guidance to the store",
            {"steps": [st.text for st in steps if st.grounded]}, approval=outbound_approval)
        if decision.suggested_automation in ALLOWED_AUTOMATIONS:
            add("run_automation", f"Run pre-approved automation: {decision.suggested_automation}",
                {"automation": decision.suggested_automation, "asset_id": ticket.asset_id})
    elif routing == "l2_escalation":
        add("escalate_l2", "Escalate to L2 Support queue with escalation package",
            {"reason": decision.escalation_reason or decision.rationale})
        if ticket.priority == "P1":
            add("notify_oncall", "Notify on-call (oncall@servewell.in) — P1")
    elif routing == "needs_clarification":
        add("request_clarification", "Ask the store for missing details",
            {"questions": decision.info_needed}, approval=outbound_approval)
    elif routing == "non_it":
        add("redirect_non_it", "Redirect requester to the right team (not IT)", approval=True)
    return actions


def queue_for(routing: str) -> str:
    return {
        "l1_self_service": "L1 Self-Service",
        "l1_guided": "L1 Support",
        "l2_escalation": "L2 Support",
        "non_it": "Redirect (non-IT)",
        "needs_clarification": "L1 Support — awaiting info",
    }.get(routing, "L1 Support")
