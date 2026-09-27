"""Load the ServeWell synthetic dataset from DATA_ROOT.

Note: train_index.csv points at `raw/INC-*.json`, but the package ships the files under
`tickets/train/`. We resolve against both so either layout (and fresh test drops) works.
"""

import csv
import json
from pathlib import Path

from servewell.config import get_settings


def _root() -> Path:
    return get_settings().data_root


def _resolve_ticket_path(filename: str) -> Path | None:
    tickets = _root() / "tickets"
    name = Path(filename).name
    for candidate in (tickets / filename, tickets / "train" / name, tickets / "raw" / name):
        if candidate.exists():
            return candidate
    return None


def load_train_tickets() -> list[dict]:
    out = []
    with open(_root() / "tickets" / "train_index.csv") as f:
        for row in csv.DictReader(f):
            path = _resolve_ticket_path(row["filename"])
            if path:
                ticket = json.loads(path.read_text())
                ticket["_chaos_type"] = row.get("chaos_type") or None
                out.append(ticket)
    return out


def load_labels() -> dict[str, dict]:
    labels = json.loads((_root() / "labels" / "train_labels.json").read_text())
    return {lbl["ticket_id"]: lbl for lbl in labels}


def load_csv(name: str) -> list[dict]:
    with open(_root() / "data" / name) as f:
        return list(csv.DictReader(f))


def list_kb_docs() -> list[Path]:
    kb = _root() / "kb"
    return sorted(p for p in kb.rglob("*") if p.suffix in {".md", ".csv"})
