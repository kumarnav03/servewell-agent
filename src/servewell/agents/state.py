"""Shared LangGraph state for one ticket run."""

import operator
from typing import Annotated, TypedDict

from servewell.models.schemas import (
    EnrichedContext,
    GuardrailResult,
    GuidanceStep,
    LLMDecision,
    PolicyOverride,
    ProposedAction,
    RetrievedChunk,
    Ticket,
)


class AgentState(TypedDict, total=False):
    run_id: str
    supervised: bool                # True: all outbound messages need human approval
    dry_run: bool                   # evaluation: skip ITSM writes
    raw: dict                       # ticket as received
    ticket: Ticket
    masked_subject: str
    masked_description: str
    signals: dict                   # non-IT terms, injection hits, printer signal
    in_scope: bool
    scope_note: str
    enrichment: EnrichedContext
    retrieval_query: str
    retrieval_mode: str
    chunks: list[RetrievedChunk]
    llm_decision: LLMDecision | None
    llm_meta: dict
    llm_error: str | None
    steps: list[GuidanceStep]
    final_routing: str
    overrides: list[PolicyOverride]
    needs_review: bool
    review_reasons: list[str]
    actions: list[ProposedAction]
    requester_message: str
    work_note: str
    guardrails: Annotated[list[GuardrailResult], operator.add]
    trace: Annotated[list[dict], operator.add]
