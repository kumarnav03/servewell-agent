"""Shared UI helpers: import path bootstrap, badges and ticket rendering."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st  # noqa: E402

ROUTING_STYLE = {
    "l1_self_service": ("🟢", "L1 Self-service", "green"),
    "l1_guided": ("🟢", "L1 Guided resolution", "green"),
    "l2_escalation": ("🟠", "Escalate to L2", "orange"),
    "needs_clarification": ("🔵", "Needs clarification", "blue"),
    "non_it": ("⚪", "Not an IT issue — redirect", "gray"),
    "out_of_scope": ("⚪", "Outside Printers pilot — human L1", "gray"),
}
PRIORITY_COLOR = {"P1": "red", "P2": "orange", "P3": "blue", "P4": "gray"}
SEVERITY_ICON = {"critical": "🔴", "warning": "🟠", "info": "🔵"}


def routing_label(routing: str | None) -> str:
    icon, text, color = ROUTING_STYLE.get(routing or "", ("❔", routing or "—", "gray"))
    return f":{color}[{icon} **{text}**]"


def ticket_card(t: dict) -> None:
    pri = t.get("priority") or "P3"
    st.markdown(
        f"#### {t.get('subject') or '(no subject)'}\n"
        f":{PRIORITY_COLOR.get(pri, 'gray')}-badge[{pri}] :gray-badge[{t.get('category') or '—'} / "
        f"{t.get('subcategory') or '—'}] :gray-badge[{t.get('ticket_id', 'NEW')}] "
        f":gray-badge[{t.get('store_name') or t.get('store_id') or 'unknown store'}] "
        f":gray-badge[asset {t.get('asset_id') or '—'}]"
    )
    st.write(t.get("description") or "")
    meta = []
    if t.get("submitted_by"):
        meta.append(f"Submitted by **{t['submitted_by']}**")
    if t.get("date_opened"):
        meta.append(f"opened {str(t['date_opened'])[:16].replace('T', ' ')}")
    if t.get("system_version"):
        meta.append(f"system `{t['system_version']}`")
    if t.get("escalation_flag"):
        meta.append("⚑ pre-flagged for escalation")
    st.caption(" · ".join(meta))
    history = t.get("ticket_history") or []
    if history:
        with st.expander(f"Ticket history ({len(history)} entries)"):
            for h in history:
                st.markdown(f"- `{str(h.get('timestamp', ''))[:16]}` **{h.get('actor', '')}** — {h.get('note', '')}")
