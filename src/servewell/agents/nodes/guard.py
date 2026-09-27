"""Output guardrails + policy: grounding check, SOP overrides, autonomy line, action proposal."""

from servewell.agents.state import AgentState
from servewell.guardrails.grounding import check_steps, grounding_rate
from servewell.guardrails.policy import apply_policy, propose_actions
from servewell.models.schemas import GuardrailResult, LLMDecision, PolicyOverride, ProposedAction


def guard_node(state: AgentState) -> dict:
    t = state["ticket"]
    decision: LLMDecision | None = state.get("llm_decision")

    if decision is None:  # LLM unavailable -> fail safe
        fallback = LLMDecision(
            routing="l2_escalation", confidence=0.0, is_printer_issue=True,
            rationale="LLM unavailable — routed to a human with enrichment attached.",
            root_cause_hypothesis="unknown", l1_steps_already_tried=[], steps=[], info_needed=[],
            escalation_reason="Automated triage unavailable", suggested_automation="none",
            requester_intro="Thanks for reporting this — a support engineer will pick it up shortly.",
        )
        actions = propose_actions(t, "l2_escalation", fallback, [], needs_review=True)
        return {
            "llm_decision": fallback, "steps": [], "final_routing": "l2_escalation", "overrides": [
                PolicyOverride(rule="llm_unavailable", before="-", after="l2_escalation",
                               reason=state.get("llm_error") or "LLM error")],
            "needs_review": True, "review_reasons": ["LLM unavailable"], "actions": actions,
            "guardrails": [GuardrailResult(name="LLM availability", passed=False, detail=state.get("llm_error", ""))],
            "trace": [{"node": "output_guard", "summary": "Fail-safe: human review"}],
        }

    ticket_text = f"{t.subject} {t.description} {' '.join(state['enrichment'].history_summary)}"
    steps = check_steps(decision.steps, state["chunks"], ticket_text)
    rate = grounding_rate(steps)
    routing, overrides, needs_review, reasons = apply_policy(
        t, state["enrichment"], decision, steps, state["signals"])
    actions = propose_actions(t, routing, decision, steps, needs_review, state.get("supervised", True))

    results = [
        GuardrailResult(name="Grounding check", passed=(rate == 1.0 or not steps),
                        detail=f"{sum(s.grounded for s in steps)}/{len(steps)} steps grounded in cited KB chunks"),
        GuardrailResult(name="Confidence threshold", passed=not any("confidence" in r for r in reasons),
                        detail=f"Model confidence {decision.confidence:.2f}"),
        GuardrailResult(name="SOP policy", passed=not overrides,
                        detail="; ".join(f"{o.rule}: {o.before}→{o.after}" for o in overrides) or "No overrides"),
    ]
    return {
        "steps": steps, "final_routing": routing, "overrides": overrides,
        "needs_review": needs_review, "review_reasons": reasons, "actions": actions,
        "guardrails": results,
        "trace": [{"node": "output_guard",
                   "summary": f"final={routing} grounded={rate:.0%} review={'yes' if needs_review else 'no'}"}],
    }


def out_of_scope_node(state: AgentState) -> dict:
    return {
        "final_routing": "out_of_scope", "needs_review": True,
        "review_reasons": [state["scope_note"]], "steps": [], "overrides": [], "chunks": [],
        "actions": [
            ProposedAction(action_id="A1", kind="post_work_note", title="Post enrichment note to the ticket",
                           requires_approval=False),
            ProposedAction(action_id="A2", kind="set_routing", title="Assign to human L1 queue (outside pilot)",
                           payload={"routing": "out_of_scope", "queue": "L1 Support (manual)"},
                           requires_approval=False),
        ],
        "trace": [{"node": "out_of_scope", "summary": "Skipped LLM — routed to human L1 with enrichment"}],
    }
