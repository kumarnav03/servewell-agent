"""Intake, input guardrails and pilot-scope check."""

from datetime import datetime

from servewell.agents.state import AgentState
from servewell.config import get_settings
from servewell.guardrails.input_checks import run_input_checks
from servewell.models.schemas import GuardrailResult, Ticket


def normalise(raw: dict) -> Ticket:
    data = {k: v for k, v in raw.items() if v not in ("", None) and not k.startswith("_")}
    data.setdefault("ticket_id", f"NEW-{datetime.now():%H%M%S}")
    data.setdefault("date_opened", datetime.now().astimezone().isoformat(timespec="minutes"))
    return Ticket(**data)


def intake_node(state: AgentState) -> dict:
    ticket = normalise(state["raw"])
    return {"ticket": ticket, "trace": [{"node": "intake", "summary": f"Parsed {ticket.ticket_id}"}]}


def input_guard_node(state: AgentState) -> dict:
    t = state["ticket"]
    subj, desc, results, signals = run_input_checks(t.subject, t.description)
    return {
        "masked_subject": subj,
        "masked_description": desc,
        "signals": signals,
        "guardrails": results,
        "trace": [{"node": "input_guard", "summary": "; ".join(f"{r.name}: {r.detail}" for r in results)}],
    }


def scope_node(state: AgentState) -> dict:
    """Pilot handles Printers only. A printer issue filed under another category is pulled in."""
    pilot = get_settings().pilot_category
    t = state["ticket"]
    signal = state["signals"]["printer_signal"]
    if t.category == pilot:
        in_scope, note = True, f"Category '{pilot}' — in pilot scope"
    elif signal >= 2:
        in_scope, note = True, (f"Filed as '{t.category}' but text is clearly about a printer "
                                f"({signal} printer terms) — handled as {pilot}")
    else:
        in_scope, note = False, f"Category '{t.category}' is outside the {pilot} pilot — routed to human L1"
    return {
        "in_scope": in_scope,
        "scope_note": note,
        "guardrails": [GuardrailResult(name="Pilot scope", passed=in_scope, detail=note)],
        "trace": [{"node": "scope_check", "summary": note}],
    }
