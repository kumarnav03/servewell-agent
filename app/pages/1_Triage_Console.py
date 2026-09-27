"""Triage Console — submit a ticket, watch the agent work, approve or reject its actions."""

import json

import pandas as pd
import streamlit as st
from components.common import SEVERITY_ICON, routing_label, ticket_card

from servewell.agents.graph import stream_ticket
from servewell.agents.nodes.act import execute_action, reject_action
from servewell.config import get_settings
from servewell.ingest.load_dataset import load_csv, load_labels, load_train_tickets
from servewell.platform.retrieval import index_exists

st.set_page_config(page_title="Triage Console · ServeWell", page_icon="🖨️", layout="wide")
settings = get_settings()

NODE_LABELS = {
    "intake": "📥 Reading the ticket",
    "input_guard": "🛡️ Input safety checks (PII, injection, non-IT)",
    "scope_check": "🎯 Pilot scope check",
    "enrich": "🔎 Looking up store, asset, SLA, known bugs & history",
    "retrieve": "📚 Searching runbooks & knowledge base",
    "llm_triage": "🧠 Reasoning with local LLM",
    "output_guard": "✅ Grounding & policy checks",
    "out_of_scope": "↪️ Outside pilot — handing to a human",
    "summarize": "✍️ Drafting store message & work note",
    "act": "⚙️ Updating the ticket (auto-allowed actions only)",
}


@st.cache_data
def dataset():
    return load_train_tickets(), load_labels()


@st.cache_data
def reference():
    return load_csv("stores.csv"), load_csv("assets.csv")


if not index_exists():
    st.error("Knowledge-base index not built. Run `uv run python scripts/build_index.py` first.")
    st.stop()

# ---------------------------------------------------------------- sidebar: ticket source
with st.sidebar:
    st.header("Incoming ticket")
    source = st.radio("Source", ["Dataset ticket", "New ticket (form)", "Upload JSON"], label_visibility="collapsed")
    st.divider()
    supervised = st.toggle("Supervised mode", value=True,
                           help="On: every message to the store waits for human approval. "
                                "Off: grounded, confident guidance is sent automatically.")
    reviewer = st.text_input("Reviewer name (for approvals)", value="L1 Analyst")

tickets, labels = dataset()
raw: dict | None = None

if source == "Dataset ticket":
    show_all = st.sidebar.checkbox("Include non-Printer tickets", value=False,
                                   help="Shows how the agent handles tickets outside the pilot scope.")
    pool = [t for t in tickets if show_all or t["category"] == settings.pilot_category]
    options = {f"{t['ticket_id']} · {t['priority']} · {t['subject'][:60]}": t for t in pool}
    choice = st.sidebar.selectbox(f"Ticket ({len(pool)})", list(options))
    raw = options[choice]

elif source == "New ticket (form)":
    stores, assets = reference()
    store_names = {f"{s['store_id']} · {s['store_name']}": s for s in stores}
    with st.sidebar:
        store = store_names[st.selectbox("Store", list(store_names))]
        printers = [a for a in assets if a["store_id"] == store["store_id"] and a["asset_type"] == "Receipt Printer"]
        asset_opts = {f"{a['asset_id']} · {a['make']}": a for a in printers}
        asset_key = st.selectbox("Printer", list(asset_opts) + ["(unknown / not listed)"])
        asset = asset_opts.get(asset_key)
        priority = st.select_slider("Priority", ["P1", "P2", "P3", "P4"], value="P3")
        submitted_by = st.text_input("Your name", "Store Manager")
    subject = st.text_input("Subject", placeholder="e.g. Receipt printer printing blank bills")
    description = st.text_area("Describe the problem", height=120,
                               placeholder="What happens, since when, what have you already tried?")
    tried = st.text_area("Troubleshooting already done by L1 (optional, one per line)", height=70)
    if subject or description:
        raw = {
            "store_id": store["store_id"], "store_name": store["store_name"], "submitted_by": submitted_by,
            "priority": priority, "category": "Printers", "subject": subject, "description": description,
            "asset_id": asset["asset_id"] if asset else None,
            "system_version": asset["system_version"] if asset else None,
            "ticket_history": [{"actor": "L1 Agent", "note": line} for line in tried.splitlines() if line.strip()],
        }

else:
    up = st.sidebar.file_uploader("Ticket JSON (single ticket or a list)", type="json")
    if up:
        data = json.load(up)
        items = data if isinstance(data, list) else [data]
        pick = st.sidebar.selectbox("Ticket", range(len(items)),
                                    format_func=lambda i: f"{items[i].get('ticket_id', 'NEW')} · {items[i].get('subject', '')[:50]}")
        raw = items[pick]

# ---------------------------------------------------------------- main: ticket + run
st.title("🖨️ Printer Triage Console")
st.caption(f"Pilot scope: **{settings.pilot_category}** · model `{settings.llm_model}` (local, Ollama) · "
           f"{'🔒 supervised' if supervised else '⚡ autonomous within policy'}")

if not raw:
    st.info("Fill in the ticket form or upload a JSON ticket to begin.")
    st.stop()

with st.container(border=True):
    ticket_card(raw)

label = labels.get(raw.get("ticket_id", ""))
run_key = f"{raw.get('ticket_id')}|{raw.get('subject')}|{supervised}"

if st.button("▶ Run triage agent", type="primary", width="stretch"):
    with st.status("Agent working…", expanded=True) as status:
        final = None
        for node, update, state in stream_ticket(raw, supervised=supervised):
            summary = " | ".join(e["summary"] for e in (update or {}).get("trace", []))
            ms = sum(e.get("ms", 0) for e in (update or {}).get("trace", []))
            status.write(f"{NODE_LABELS.get(node, node)} — {summary}" + (f"  `{ms/1000:.1f}s`" if ms > 300 else ""))
            final = state
        status.update(label="Agent finished", state="complete", expanded=False)
    st.session_state["run"] = final
    st.session_state["run_key"] = run_key

run = st.session_state.get("run")
if not run or st.session_state.get("run_key") != run_key:
    st.stop()

# ---------------------------------------------------------------- results header
d = run.get("llm_decision")
steps = run.get("steps", [])
grounded = sum(s.grounded for s in steps)

st.subheader("Decision")
c1, c2, c3, c4 = st.columns([2.2, 1, 1, 1])
c1.markdown(f"### {routing_label(run['final_routing'])}")
c2.metric("Model confidence", f"{d.confidence:.0%}" if d and run["final_routing"] != "out_of_scope" else "—")
c3.metric("Grounded steps", f"{grounded}/{len(steps)}" if steps else "—")
c4.metric("LLM time", f"{run.get('llm_meta', {}).get('latency_ms', 0)/1000:.1f}s" if run.get("llm_meta", {}).get("latency_ms") else "—")

if run.get("needs_review"):
    st.warning("**Human review required** — " + "; ".join(run["review_reasons"]))
for o in run.get("overrides", []):
    st.info(f"**Policy override `{o.rule}`:** model said `{o.before}` → final `{o.after}`. {o.reason}")
if label:
    match = label["correct_routing"] == run["final_routing"]
    st.caption(f"{'✅' if match else '❌'} Ground-truth label (evaluation only): `{label['correct_routing']}`")

tabs = st.tabs(["📨 Store message & actions", "🧠 Reasoning & steps", "🔎 Enrichment",
                "📚 Knowledge used", "🛡️ Guardrails", "🧾 Trace & audit"])

# ---------------------------------------------------------------- tab: message + actions
with tabs[0]:
    left, right = st.columns([1.3, 1])
    with left:
        st.markdown("**Message to the store** (only grounded steps are included)")
        with st.container(border=True):
            st.markdown(run["requester_message"])
    with right:
        st.markdown("**Actions**")
        for a in run["actions"]:
            with st.container(border=True):
                badge = {"executed": "✅ executed automatically", "approved": f"✅ approved",
                         "rejected": "🚫 rejected", "blocked": "⛔ blocked",
                         "proposed": "⏳ awaiting approval" if a.requires_approval else "…"}[a.status]
                st.markdown(f"**{a.title}**  \n{badge}" + ("  · 🔒 needs approval" if a.requires_approval else "  · auto-allowed"))
                if a.payload:
                    with st.expander("Details"):
                        st.json(a.payload)
                if a.status == "proposed" and a.requires_approval:
                    b1, b2 = st.columns(2)
                    if b1.button("Approve", key=f"ap_{run['run_id']}_{a.action_id}", type="primary",
                                 width="stretch", disabled=run.get("dry_run", False)):
                        st.session_state["flash"] = execute_action(run, a.action_id, approver=reviewer)
                        st.rerun()
                    if b2.button("Reject", key=f"rj_{run['run_id']}_{a.action_id}", width="stretch"):
                        reject_action(run, a.action_id, approver=reviewer)
                        st.rerun()
        if msg := st.session_state.pop("flash", None):
            st.success(msg)

# ---------------------------------------------------------------- tab: reasoning
with tabs[1]:
    if not d or run["final_routing"] == "out_of_scope":
        st.write("No LLM reasoning for this ticket (outside pilot scope or LLM unavailable).")
    else:
        st.markdown(f"**Rationale:** {d.rationale}")
        st.markdown(f"**Root-cause hypothesis:** {d.root_cause_hypothesis}")
        if d.l1_steps_already_tried:
            st.markdown("**Already tried (from ticket/history):**\n" + "\n".join(f"- {x}" for x in d.l1_steps_already_tried))
        if d.escalation_reason and run["final_routing"] == "l2_escalation":
            st.markdown(f"**Escalation reason:** {d.escalation_reason}")
        if d.info_needed:
            st.markdown("**Information needed:**\n" + "\n".join(f"- {x}" for x in d.info_needed))
        st.markdown("**Proposed steps and grounding check**")
        for i, s in enumerate(steps, 1):
            icon = "✅" if s.grounded else "❌"
            cites = ", ".join(s.citations) or "no citation"
            st.markdown(f"{icon} **{i}.** {s.text}  \n<small>cites {cites}"
                        + (f" — ⚠️ {s.issue} (removed from store message)" if s.issue else "") + "</small>",
                        unsafe_allow_html=True)

# ---------------------------------------------------------------- tab: enrichment
with tabs[2]:
    ctx = run["enrichment"]
    a, b = st.columns(2)
    with a:
        st.markdown("**Store**")
        st.json(ctx.store.model_dump() if ctx.store else {"error": "store not found"}, expanded=False)
        st.markdown("**Asset (CMDB)**")
        st.json(ctx.asset.model_dump() if ctx.asset else {"error": "asset not found"}, expanded=False)
    with b:
        st.markdown("**SLA clock**")
        if ctx.sla:
            st.dataframe(pd.DataFrame([
                ["First response", f"{ctx.sla.first_response_minutes} min", ctx.sla.first_response_due],
                ["Escalate to L2", f"{ctx.sla.escalation_to_l2_minutes} min", ctx.sla.escalate_to_l2_by],
                ["Resolve", f"{ctx.sla.resolution_target_minutes} min", ctx.sla.resolution_due],
            ], columns=["Target", "Within", "Due"]), hide_index=True, width="stretch")
        st.markdown("**Version matrix**")
        if ctx.known_issue:
            st.write(f"{ctx.known_issue.system} {ctx.known_issue.version}: known bugs — *{ctx.known_issue.known_bugs}*; "
                     f"patch — *{ctx.known_issue.patch_available}*")
        else:
            st.write("No version-matrix entry.")
    st.markdown("**Data-quality & context flags**")
    for f in ctx.flags or []:
        st.markdown(f"{SEVERITY_ICON[f.severity]} `{f.code}` — {f.message}")
    if not ctx.flags:
        st.write("None")
    if ctx.similar_tickets:
        st.markdown("**Other tickets at this store (same asset first)**")
        st.dataframe(pd.DataFrame(ctx.similar_tickets), hide_index=True, width="stretch")

# ---------------------------------------------------------------- tab: knowledge
with tabs[3]:
    chunks = run.get("chunks", [])
    if not chunks:
        st.write("No retrieval for this ticket.")
    else:
        cited = {c for s in steps if s.grounded for c in s.citations}
        st.caption(f"Hybrid retrieval ({run.get('retrieval_mode')}) — BM25 + nomic-embed, fused with RRF")
        with st.expander("Retrieval query"):
            st.code(run["retrieval_query"])
        for i, rc in enumerate(chunks, 1):
            tag = "📌 cited" if f"C{i}" in cited else ""
            with st.expander(f"C{i} · {rc.score:.2f} · {rc.chunk.doc_path} › {rc.chunk.section} {tag}"):
                st.caption(f"BM25 rank {rc.bm25_rank or '—'} · dense rank {rc.dense_rank or '—'} · "
                           f"cosine {rc.dense_similarity if rc.dense_similarity is not None else '—'}")
                st.markdown(rc.chunk.text)
        if label:
            st.caption("Ground-truth relevant docs: " + ", ".join(f"`{x}`" for x in label["relevant_kb_docs"]))

# ---------------------------------------------------------------- tab: guardrails
with tabs[4]:
    st.dataframe(pd.DataFrame([{"Check": g.name, "Result": "✅ pass" if g.passed else "⚠️ flag", "Detail": g.detail}
                               for g in run.get("guardrails", [])]), hide_index=True, width="stretch")
    st.caption("Autonomy line: work notes and routing run automatically; messages to the store, escalations, "
               "automations and non-IT redirects wait for a human in supervised mode or whenever review is required.")

# ---------------------------------------------------------------- tab: trace
with tabs[5]:
    st.markdown(f"**Run** `{run['run_id']}`")
    st.dataframe(pd.DataFrame([{"Step": NODE_LABELS.get(e["node"], e["node"]), "ms": e.get("ms", 0),
                                "Summary": e["summary"]} for e in run["trace"]]),
                 hide_index=True, width="stretch")
    st.markdown("**Ticket work note**")
    with st.container(border=True):
        st.markdown(run["work_note"])
    meta = run.get("llm_meta") or {}
    if meta.get("user_message"):
        with st.expander(f"LLM input (prompt `{meta.get('prompt_version', '-')}`, "
                         f"{meta.get('prompt_tokens', '?')} prompt tokens)"):
            st.code(meta["user_message"], language="markdown")
    if meta.get("raw"):
        with st.expander(f"LLM raw output ({meta.get('output_tokens', '?')} tokens)"):
            st.code(meta["raw"], language="json")
