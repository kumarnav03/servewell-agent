"""Output guardrail: every guidance step must be supported by a retrieved KB chunk.

Checks per step:
1. It cites at least one chunk label (C1..Cn) that was actually retrieved.
2. Error codes / versions / IPs it mentions appear in the ticket or in the cited chunks
   (catches invented specifics — the most damaging kind of hallucination for a store manager).
3. Lexical support: a minimum share of the step's content words appear in the cited chunks.
Ungrounded steps are removed from what the requester sees and shown to the reviewer.
"""

import re

from servewell.models.schemas import GuidanceStep, LLMStep, RetrievedChunk
from servewell.platform.retrieval import tokenize

SPECIFIC_RE = re.compile(
    r"\b(?:[A-Z]{2,5}-[A-Z]?\d{2,5}|E\d{2,3}|v\d+(?:\.\d+)+|\d{1,3}(?:\.\d{1,3}){3})\b"
)
MIN_SUPPORT = 0.35


def check_steps(
    steps: list[LLMStep], chunks: list[RetrievedChunk], ticket_text: str
) -> list[GuidanceStep]:
    labels = {f"C{i}": rc.chunk for i, rc in enumerate(chunks, 1)}
    checked = []
    for step in steps:
        cites = [c.strip("[] ") for c in step.citations]
        valid = [c for c in cites if c in labels]
        out = GuidanceStep(text=step.text, citations=valid)
        if not valid:
            out.issue = "No valid citation to a retrieved KB chunk"
            checked.append(out)
            continue
        source = " ".join(labels[c].text for c in valid) + " " + ticket_text
        invented = [s for s in SPECIFIC_RE.findall(step.text) if s.lower() not in source.lower()]
        if invented:
            out.issue = f"Mentions specifics not found in KB or ticket: {invented}"
            checked.append(out)
            continue
        words = set(tokenize(step.text))
        support = len(words & set(tokenize(source))) / max(len(words), 1)
        if support < MIN_SUPPORT:
            out.issue = f"Weak support in cited chunks ({support:.0%} word overlap)"
        else:
            out.grounded = True
        checked.append(out)
    return checked


def grounding_rate(steps: list[GuidanceStep]) -> float:
    return sum(s.grounded for s in steps) / len(steps) if steps else 0.0
