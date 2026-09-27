"""ServeWell IT Support Agent — Printers pilot: overview and environment health."""

from collections import Counter

import httpx
import pandas as pd
import streamlit as st
from components.common import SRC  # noqa: F401  (bootstraps import path)

from servewell.config import get_settings
from servewell.ingest.load_dataset import list_kb_docs, load_labels, load_train_tickets
from servewell.platform.retrieval import index_exists, index_meta

st.set_page_config(page_title="ServeWell IT Support Agent", page_icon="🛠️", layout="wide")
settings = get_settings()


@st.cache_data
def data():
    tickets = load_train_tickets()
    return tickets, load_labels(), list_kb_docs()


def ollama_models() -> list[str] | None:
    try:
        return [m["name"] for m in httpx.get(f"{settings.ollama_host}/api/tags", timeout=2).json()["models"]]
    except Exception:
        return None


st.title("🛠️ ServeWell IT Support Agent")
st.markdown(
    f"**Pilot: {settings.pilot_category}** — an AI agent that triages receipt/kitchen printer incidents, "
    "looks up the store, device and SLA, finds the right runbook steps, and either guides the store to a fix "
    "or packages the ticket for L2, with every step checked, approved where needed, and logged."
)
st.page_link("pages/1_Triage_Console.py", label="Open the Triage Console →", icon="🖨️")

st.subheader("How a ticket flows")
st.graphviz_chart("""
digraph {
  rankdir=LR; node [shape=box style="rounded,filled" fillcolor="#eef3fb" fontname="Helvetica" fontsize=11];
  intake [label="📥 Ticket in"]; guard1 [label="🛡️ Input checks\\nPII · injection · non-IT"];
  enrich [label="🔎 Enrich (tools)\\nstore · asset · SLA\\nknown bugs · history"];
  rag [label="📚 Retrieve\\nrunbooks (hybrid)"]; llm [label="🧠 Local LLM\\nroute + cited steps"];
  guard2 [label="✅ Grounding &\\npolicy checks" fillcolor="#e8f5e9"];
  human [label="👤 Human approval" shape=diamond fillcolor="#fff4e5"];
  act [label="⚙️ Ticket updated\\nstore messaged / L2"];
  intake -> guard1 -> enrich -> rag -> llm -> guard2 -> human -> act;
  guard2 -> act [label="auto-allowed" fontsize=9 style=dashed];
}
""", width="stretch")

st.subheader("Environment health")
models = ollama_models()
checks = {
    "Dataset": settings.data_root.exists(),
    "Ollama running": models is not None,
    "LLM pulled": bool(models) and any(m.startswith(settings.llm_model) for m in models),
    "Embeddings pulled": bool(models) and any(m.startswith(settings.embed_model) for m in models),
    "KB index built": index_exists(),
}
for col, (name, ok) in zip(st.columns(len(checks)), checks.items()):
    col.metric(name, "✅" if ok else "❌")
if not all(checks.values()):
    st.warning("Setup incomplete — see README (`./scripts/setup_models.sh`, `scripts/build_index.py`).")
if not checks["Dataset"]:
    st.stop()

tickets, labels, kb_docs = data()
pilot = [t for t in tickets if t["category"] == settings.pilot_category]
meta = index_meta() or {}
st.subheader("Pilot data")
c = st.columns(5)
c[0].metric("Printer tickets", len(pilot))
c[1].metric("Labelled", sum(t["ticket_id"] in labels for t in pilot))
c[2].metric("Chaos (edge-case) tickets", sum(bool(t["_chaos_type"]) for t in pilot))
c[3].metric("KB documents", len(kb_docs))
c[4].metric("KB chunks indexed", meta.get("chunks", "—"))

left, right = st.columns(2)
with left:
    st.markdown("**Printer tickets by subcategory**")
    st.bar_chart(pd.Series(Counter(t["subcategory"] for t in pilot)).sort_values(), horizontal=True)
with right:
    st.markdown("**Ground-truth routing (Printers)**")
    st.bar_chart(pd.Series(Counter(labels[t["ticket_id"]]["correct_routing"] for t in pilot if t["ticket_id"] in labels)))
