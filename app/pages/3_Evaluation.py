"""Evaluation — how we know the Printers agent is accurate and safe."""

import json

import pandas as pd
import streamlit as st
from components.common import routing_label  # noqa: F401  (bootstraps import path)

from servewell.evaluation.run_eval import eval_path, run_eval, score

st.set_page_config(page_title="Evaluation · ServeWell", page_icon="📊", layout="wide")
st.title("📊 Printers Pilot — Evaluation")
st.caption("Every Printers ticket in the training set run through the full agent (dry run, no ITSM writes) "
           "and compared with the ground-truth labels.")

path = eval_path()
rows = json.loads(path.read_text()) if path.exists() else []

with st.expander("Re-run evaluation (≈ 40 s per ticket on a local 7B model)"):
    if st.button("Run now"):
        bar = st.progress(0.0)
        rows = run_eval(lambda i, n, r: bar.progress(i / n, text=f"{i}/{n} {r['ticket_id']} → {r['final_routing']}"))
        st.rerun()

if not rows:
    st.info("No evaluation results yet — run `uv run python scripts/run_eval.py` or use the button above.")
    st.stop()

s = score(rows)
c = st.columns(5)
c[0].metric("Routing accuracy", f"{s['routing_accuracy']:.0%}", help=f"{s['labelled']} labelled tickets, after policy")
c[1].metric("Escalation recall", f"{s['escalation_recall']:.0%}",
            help="Share of true L2 tickets the agent escalated — the safety-critical number")
c[2].metric("Escalation precision", f"{s['escalation_precision']:.0%}",
            help="Share of agent escalations that were truly L2 — the L2-workload number")
c[3].metric("Grounded steps", f"{s['grounding_rate']:.0%}", help="Steps passing the grounding check")
c[4].metric("Avg time / ticket", f"{s['avg_seconds']}s")
c = st.columns(5)
c[0].metric("Model-only accuracy", f"{s['model_only_accuracy']:.0%}", help="Before policy overrides")
c[1].metric("Retrieval recall@6", f"{s['retrieval_recall@6']:.0%}", help="Labelled relevant docs found in top-6 chunks")
c[2].metric("Human review rate", f"{s['human_review_rate']:.0%}")
c[3].metric("Tickets run", s["tickets_run"])
c[4].metric("Unlabelled chaos tickets", sum(1 for r in rows if not r["label_routing"]))

df = pd.DataFrame(rows)
lab = df[df.label_routing.notna()]
st.subheader("Confusion matrix (labelled tickets)")
st.dataframe(pd.crosstab(lab.label_routing, lab.final_routing, rownames=["label"], colnames=["agent"]),
             width="stretch")

st.subheader("Per-ticket results")
only_err = st.checkbox("Show only mismatches")
view = df.copy()
view["match"] = view.apply(lambda r: "—" if not r.label_routing else ("✅" if r.label_routing == r.final_routing else "❌"), axis=1)
if only_err:
    view = view[view.match == "❌"]
st.dataframe(view[["match", "ticket_id", "chaos_type", "subject", "label_routing", "model_routing", "final_routing",
                   "confidence", "grounded_steps", "steps", "needs_review", "overrides", "seconds"]],
             hide_index=True, width="stretch")

chaos = df[df.chaos_type.notna()]
if len(chaos):
    st.subheader("Chaos tickets (no routing label — judged against the behaviour rubric)")
    for r in chaos.itertuples():
        with st.expander(f"{r.ticket_id} · {r.chaos_type} → {r.final_routing}"):
            st.write(r.subject)
            st.caption(f"Review reasons: {r.review_reasons or 'none'}")
