# ServeWell IT Support Agent — Printers Pilot POC

An agentic L1 triage assistant for **receipt/kitchen printer incidents** at ServeWell Hospitality,
running entirely locally on open-source components and simulating the phData Intelligence Platform.

For each incident, the agent:
1. **Checks the input:** masks PII, scans for prompt injection, flags non-IT intent (e.g. payroll).
2. **Enriches with tools, not the LLM:** store, CMDB asset (validated), SLA clock, version-matrix
   known bugs, ticket history, repeat incidents.
3. **Retrieves** runbook sections with hybrid search (BM25 + `nomic-embed-text`, fused with RRF).
4. **Reasons** with a local LLM (`qwen2.5:7b-instruct`) in one schema-enforced JSON call: a routing
   decision, a confidence score and step-by-step guidance, where every step cites a KB chunk.
5. **Guards the output:** a grounding check on every step; SOP policy overrides (unknown system →
   L2, ungrounded fix → L2); low confidence, P1 or missing CMDB records → human review.
6. **Acts** on a simulated ITSM. Work notes and routing run automatically; messages to the store,
   L2 escalations and automations wait for **human approval** (supervised mode).
7. **Audits** every node, LLM call and action in SQLite.

Tickets outside the Printers category are routed to a human with enrichment attached. A printer
issue filed under another category is recognised and pulled into scope.

## Run it

```bash
cd servewell-agent
uv sync                                   # Python 3.12 + deps into .venv
./scripts/setup_models.sh                 # starts Ollama, pulls qwen2.5:7b-instruct + nomic-embed-text
uv run python scripts/build_index.py      # chunk + embed the KB (~20 s)
uv run streamlit run app/Home.py          # http://localhost:8501
```

Optional: `uv run python scripts/run_eval.py` runs all 35 Printer tickets, about 40 s each.

## App pages

| Page | What it shows |
| --- | --- |
| Home | Flow diagram, environment health, pilot data |
| Triage Console | Choose a dataset ticket, fill in a new-ticket form, or upload JSON → watch each node run → decision, store message, Approve/Reject actions, enrichment, cited KB chunks, guardrails, full trace including the LLM prompt and raw output |
| Ticket Queue | Simulated ITSM queue, comments per ticket, audit trail (downloadable) |
| Evaluation | Routing accuracy, escalation precision/recall, grounding rate, confusion matrix, per-ticket drill-down |

## Layout

```
app/                     Streamlit UI (Home + pages/, components/common.py)
src/servewell/
  config.py              settings (.env), pilot scope, thresholds
  models/schemas.py      Pydantic models incl. the LLM output schema
  platform/              simulated platform services
    data_access.py         DuckDB over stores/assets/SLA/version matrix/tickets + enrichment checks
    retrieval.py           hybrid BM25 + Chroma retriever
    itsm.py, automations.py  simulated ITSM endpoints + allow-listed automations
  ingest/                dataset loader (fixes raw/ vs train/ path), KB chunker, index builder
  agents/                LangGraph graph, nodes/, prompts/ (versioned), Ollama wrapper
  guardrails/            input checks, grounding check, policy / autonomy line
  observability/audit.py append-only audit log
  evaluation/            retrieval metrics, pilot eval harness
storage/                 generated: chroma index, itsm.db, audit.db, eval results (git-ignored)
```

## Known limitations

- Local 7B model: roughly 30–60 s per ticket on an M4 laptop, and weaker reasoning than frontier models.
  The model sits behind one wrapper (`agents/llm.py`), so swapping it is a config change.
- Train labels only cover `l1_guided` and `l2_escalation`. The `non_it`, `needs_clarification`
  and self-service paths are rule- and prompt-driven and are not statistically validated.
- ITSM, notifications and automations are simulated.
