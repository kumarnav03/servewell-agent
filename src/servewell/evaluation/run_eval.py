"""Batch-run the agent over every Printers ticket and score it against train_labels."""

import json
import time

from servewell.agents.graph import run_ticket
from servewell.config import get_settings
from servewell.ingest.load_dataset import load_labels, load_train_tickets


def eval_path():
    return get_settings().storage_dir / "eval_printers.json"


def run_eval(progress=None) -> list[dict]:
    pilot = get_settings().pilot_category
    labels = load_labels()
    tickets = [t for t in load_train_tickets() if t["category"] == pilot]
    rows = []
    for i, raw in enumerate(tickets, 1):
        started = time.time()
        s = run_ticket(raw, dry_run=True)
        label = labels.get(raw["ticket_id"], {})
        d = s.get("llm_decision")
        cited = {s["chunks"][int(c[1:]) - 1].chunk.doc_path for st in s["steps"] for c in st.citations}
        retrieved = {rc.chunk.doc_path for rc in s["chunks"]}
        relevant = set(label.get("relevant_kb_docs", []))
        rows.append({
            "ticket_id": raw["ticket_id"],
            "subject": raw["subject"],
            "chaos_type": raw.get("_chaos_type"),
            "label_routing": label.get("correct_routing"),
            "model_routing": d.routing if d else None,
            "final_routing": s["final_routing"],
            "confidence": d.confidence if d else None,
            "needs_review": s["needs_review"],
            "review_reasons": s["review_reasons"],
            "overrides": [o.rule for o in s["overrides"]],
            "steps": len(s["steps"]),
            "grounded_steps": sum(st.grounded for st in s["steps"]),
            "retrieval_recall": (len(relevant & retrieved) / len(relevant)) if relevant else None,
            "cited_relevant": bool(relevant & cited) if relevant else None,
            "seconds": round(time.time() - started, 1),
            "chaos_correct_behavior": label.get("chaos_correct_behavior"),
        })
        eval_path().write_text(json.dumps(rows, indent=2, default=str))
        if progress:
            progress(i, len(tickets), rows[-1])
    return rows


def score(rows: list[dict]) -> dict:
    labelled = [r for r in rows if r["label_routing"]]
    if not labelled:
        return {}
    correct = [r for r in labelled if r["final_routing"] == r["label_routing"]]
    esc_true = [r for r in labelled if r["label_routing"] == "l2_escalation"]
    esc_pred = [r for r in labelled if r["final_routing"] == "l2_escalation"]
    tp = [r for r in esc_pred if r["label_routing"] == "l2_escalation"]
    steps = sum(r["steps"] for r in rows)
    return {
        "tickets_run": len(rows),
        "labelled": len(labelled),
        "routing_accuracy": round(len(correct) / len(labelled), 3),
        "model_only_accuracy": round(sum(r["model_routing"] == r["label_routing"] for r in labelled) / len(labelled), 3),
        "escalation_recall": round(len(tp) / len(esc_true), 3) if esc_true else None,
        "escalation_precision": round(len(tp) / len(esc_pred), 3) if esc_pred else None,
        "grounding_rate": round(sum(r["grounded_steps"] for r in rows) / steps, 3) if steps else None,
        "retrieval_recall@6": round(sum(r["retrieval_recall"] for r in labelled if r["retrieval_recall"] is not None)
                                    / len(labelled), 3),
        "human_review_rate": round(sum(r["needs_review"] for r in rows) / len(rows), 3),
        "avg_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1),
    }


if __name__ == "__main__":
    rows = run_eval(lambda i, n, r: print(f"[{i}/{n}] {r['ticket_id']} label={r['label_routing']} "
                                          f"final={r['final_routing']} {r['seconds']}s", flush=True))
    print(json.dumps(score(rows), indent=2))
