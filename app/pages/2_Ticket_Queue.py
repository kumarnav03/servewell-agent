"""Ticket Queue & Audit — what the agent wrote to the (simulated) ITSM and every step it took."""

import json

import pandas as pd
import streamlit as st
from components.common import routing_label

from servewell.observability import audit
from servewell.platform import itsm

st.set_page_config(page_title="Ticket Queue · ServeWell", page_icon="📋", layout="wide")
st.title("📋 Ticket Queue & Audit Trail")
st.caption("Simulated ITSM (SQLite) — stands in for ServiceNow / Jira Service Management")

incidents = itsm.list_incidents()
tab_q, tab_a = st.tabs(["Queue", "Audit trail"])

with tab_q:
    if not incidents:
        st.info("No tickets processed yet — run one from the Triage Console.")
    else:
        df = pd.DataFrame(incidents)
        c1, c2, c3 = st.columns(3)
        c1.metric("Tickets triaged", len(df))
        c2.metric("Escalated to L2", int((df["queue"] == "L2 Support").sum()))
        c3.metric("Handled at L1", int(df["queue"].fillna("").str.startswith("L1").sum()))
        st.dataframe(df[["ticket_id", "priority", "subject", "status", "routing", "queue", "confidence", "updated_at"]],
                     hide_index=True, width="stretch")
        pick = st.selectbox("Open ticket", df["ticket_id"])
        row = df[df.ticket_id == pick].iloc[0]
        st.markdown(f"**{row['subject']}** — {routing_label(row['routing'])} · status **{row['status']}**")
        for c in itsm.list_comments(pick):
            who = "👤 to store" if c["visibility"] == "requester" else "🔒 internal"
            with st.container(border=True):
                st.caption(f"{c['created_at']} · {c['author']} · {who}")
                st.markdown(c["body"])

with tab_a:
    rows = audit.read(limit=1000)
    if not rows:
        st.info("Audit log is empty.")
    else:
        df = pd.DataFrame(rows)
        tickets = ["(all)"] + sorted(df["ticket_id"].unique())
        f = st.selectbox("Filter by ticket", tickets)
        if f != "(all)":
            df = df[df.ticket_id == f]
        st.dataframe(df[["ts", "run_id", "ticket_id", "event", "actor", "latency_ms", "detail"]],
                     hide_index=True, width="stretch", height=520)
        st.download_button("Download audit log (JSON)", json.dumps(rows, indent=2), "audit.json")
