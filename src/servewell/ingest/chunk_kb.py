"""Split KB markdown into heading-aligned chunks with metadata.

Runbook sections ("Immediate Steps", "Resolution Path B: FoodTech v4.2.x ...") are natural
retrieval units, so we split on H2/H3, keep the heading path as context, merge header-only
stubs into the following section, and cap oversized sections by paragraph.
"""

import csv
import re
from pathlib import Path

from servewell.config import get_settings
from servewell.models.schemas import KBChunk

MIN_WORDS = 40

DOC_TYPES = {"runbooks": "runbook", "faq": "faq", "sop": "sop", "system-specs": "spec"}

# filename prefix / keyword -> ticket category
CATEGORY_KEYS = [
    ("online-orders", "Online Orders"),
    ("pos", "POS"),
    ("foodtech", "POS"),
    ("orbitpos", "POS"),
    ("printer", "Printers"),
    ("epson", "Printers"),
    ("star", "Printers"),
    ("network", "Wi-Fi / Network"),
    ("netlink", "Wi-Fi / Network"),
    ("soft-serve", "Soft Serve"),
    ("creamtech", "Soft Serve"),
    ("frostypro", "Soft Serve"),
    ("kiosk", "Kiosks"),
]


def doc_category(path: Path) -> str:
    stem = path.stem.lower()
    for key, cat in CATEGORY_KEYS:
        if stem.startswith(key):
            return cat
    return "General"


def _split_long(text: str, max_words: int) -> list[str]:
    parts, current, count = [], [], 0
    for para in re.split(r"\n\s*\n", text):
        n = len(para.split())
        if current and count + n > max_words:
            parts.append("\n\n".join(current))
            current, count = [], 0
        current.append(para)
        count += n
    if current:
        parts.append("\n\n".join(current))
    return parts


def chunk_markdown(path: Path, rel: str, max_words: int) -> list[KBChunk]:
    lines = path.read_text().splitlines()
    title, h2, h3 = path.stem, "", ""
    sections: list[tuple[str, list[str]]] = []
    body: list[str] = []
    in_fence = False

    def flush():
        heading = " > ".join(h for h in (h2, h3) if h) or "Introduction"
        if any(line.strip() for line in body):
            sections.append((heading, body.copy()))
        body.clear()

    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else re.match(r"^(#{1,3})\s+(.*)", line)
        if m and len(m.group(1)) == 1 and title == path.stem:
            title = m.group(2).strip()
            continue
        if m and len(m.group(1)) in (2, 3):
            flush()
            if len(m.group(1)) == 2:
                h2, h3 = m.group(2).strip(), ""
            else:
                h3 = m.group(2).strip()
            continue
        if not in_fence and re.fullmatch(r"\s*-{3,}\s*", line):
            continue  # horizontal rule
        body.append(line)
    flush()

    # merge stubs forward so "## L1 Diagnosis Steps" intro text travels with Step 1
    merged: list[tuple[str, str]] = []
    carry_heading, carry = None, ""
    for heading, text_lines in sections:
        text = "\n".join(text_lines).strip()
        if carry:
            text, heading = f"{carry}\n\n{text}", carry_heading or heading
            carry, carry_heading = "", None
        if len(text.split()) < MIN_WORDS:
            carry, carry_heading = text, heading
            continue
        merged.append((heading, text))
    if carry:
        if merged:
            merged[-1] = (merged[-1][0], f"{merged[-1][1]}\n\n{carry}")
        else:
            merged.append((carry_heading or "Introduction", carry))

    doc_type = DOC_TYPES.get(rel.split("/")[0], "other")
    category = doc_category(path)
    chunks = []
    for heading, text in merged:
        for part in _split_long(text, max_words):
            chunks.append(
                KBChunk(
                    chunk_id=f"{rel}#{len(chunks)}",
                    doc_path=rel,
                    doc_type=doc_type,
                    doc_title=title,
                    section=heading,
                    category=category,
                    text=part,
                )
            )
    return chunks


def chunk_version_matrix(path: Path, rel: str) -> list[KBChunk]:
    """One chunk per system so version/bug questions can also be answered from the index."""
    by_system: dict[str, list[str]] = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            by_system.setdefault(row["system"], []).append(
                f"{row['system']} {row['version']} (released {row['release_date']}): known bugs: "
                f"{row['known_bugs']}; patch: {row['patch_available']}; notes: {row['notes'] or '-'}"
            )
    return [
        KBChunk(
            chunk_id=f"{rel}#{i}",
            doc_path=rel,
            doc_type="spec",
            doc_title="System Version Matrix",
            section=system,
            category=doc_category(Path(system.lower().replace(" ", "-"))),
            text="\n".join(rows),
        )
        for i, (system, rows) in enumerate(by_system.items())
    ]


def chunk_kb() -> list[KBChunk]:
    settings = get_settings()
    kb = settings.data_root / "kb"
    chunks: list[KBChunk] = []
    for path in sorted(kb.rglob("*")):
        rel = path.relative_to(kb).as_posix()
        if path.suffix == ".md":
            chunks.extend(chunk_markdown(path, rel, settings.chunk_max_words))
        elif path.name == "version-matrix.csv":
            chunks.extend(chunk_version_matrix(path, rel))
    return chunks


def embedding_text(chunk: KBChunk) -> str:
    return f"{chunk.doc_title} — {chunk.section}\n{chunk.text}"
