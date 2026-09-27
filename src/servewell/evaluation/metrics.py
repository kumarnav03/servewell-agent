"""Evaluation metrics against train_labels.

Phase 2: retrieval — doc-level recall@k vs `relevant_kb_docs`.
(Routing / escalation / grounding metrics are added in Phase 5.)
"""

from collections import defaultdict

import pandas as pd

from servewell.ingest.load_dataset import load_labels, load_train_tickets
from servewell.models.schemas import Ticket
from servewell.platform.retrieval import get_retriever, ticket_query

PILOT_CATEGORIES = {"POS", "Printers"}


def retrieval_eval(k: int = 6, use_category: bool = True) -> tuple[pd.DataFrame, dict]:
    """Per-ticket retrieval results plus aggregate metrics.

    recall@k        share of labelled relevant docs found in the top-k docs
    runbook_recall  same, restricted to runbooks (the docs that carry the fix)
    hit@k           at least one relevant doc in the top-k
    mrr             reciprocal rank of the first relevant doc
    """
    retriever = get_retriever()
    labels = load_labels()
    rows = []
    for raw in load_train_tickets():
        label = labels.get(raw["ticket_id"])
        if not label or not label["relevant_kb_docs"]:
            continue
        t = Ticket(**raw)
        docs = retriever.search_docs(ticket_query(t), t.category if use_category else None, top_k=k)
        relevant = set(label["relevant_kb_docs"])
        runbooks = {d for d in relevant if d.startswith("runbooks/")}
        first = next((i for i, d in enumerate(docs, 1) if d in relevant), None)
        rows.append(
            {
                "ticket_id": t.ticket_id,
                "category": t.category,
                "subject": t.subject,
                "relevant": sorted(relevant),
                "retrieved": docs,
                "recall": len(relevant & set(docs)) / len(relevant),
                "runbook_recall": (len(runbooks & set(docs)) / len(runbooks)) if runbooks else None,
                "hit": first is not None,
                "rr": 1 / first if first else 0.0,
            }
        )
    df = pd.DataFrame(rows)
    return df, summarize(df)


def summarize(df: pd.DataFrame) -> dict:
    def agg(frame):
        return {
            "tickets": len(frame),
            "recall@k": round(frame["recall"].mean(), 3),
            "runbook_recall@k": round(frame["runbook_recall"].dropna().mean(), 3),
            "hit@k": round(frame["hit"].mean(), 3),
            "mrr": round(frame["rr"].mean(), 3),
        }

    out = {"all": agg(df), "pilot (POS+Printers)": agg(df[df.category.isin(PILOT_CATEGORIES)])}
    per_cat = defaultdict(dict)
    for cat, frame in df.groupby("category"):
        per_cat[cat] = agg(frame)
    out["by_category"] = dict(per_cat)
    return out
