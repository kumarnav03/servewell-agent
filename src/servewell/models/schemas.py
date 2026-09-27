"""Pydantic models shared across the platform services, agent and UI."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Routing = Literal["l1_self_service", "l1_guided", "l2_escalation", "non_it", "needs_clarification"]
Priority = Literal["P1", "P2", "P3", "P4"]


class HistoryEntry(BaseModel):
    timestamp: str | None = None
    actor: str | None = None
    note: str = ""


class Ticket(BaseModel):
    ticket_id: str
    store_id: str | None = None
    store_name: str | None = None
    submitted_by: str | None = None
    contact_phone: str | None = None
    date_opened: datetime | None = None
    priority: Priority = "P3"
    category: str | None = None
    subcategory: str | None = None
    subject: str = ""
    description: str = ""
    asset_id: str | None = None
    system_version: str | None = None
    tags: list[str] = Field(default_factory=list)
    escalation_flag: bool = False
    related_tickets: list[str] = Field(default_factory=list)
    ticket_history: list[HistoryEntry] = Field(default_factory=list)
    resolution_notes: str | None = None
    status: str = "Open"


class Label(BaseModel):
    ticket_id: str
    correct_routing: Routing
    relevant_kb_docs: list[str] = Field(default_factory=list)
    should_escalate: bool
    escalation_reason: str | None = None
    correct_resolution_summary: str | None = None
    expected_agent_action: str | None = None
    chaos_correct_behavior: str | None = None
    evaluator_notes: str | None = None


class Store(BaseModel):
    store_id: str
    store_name: str
    city: str
    neighborhood: str
    store_type: str
    region_manager: str
    support_phone: str


class Asset(BaseModel):
    asset_id: str
    store_id: str
    asset_type: str
    make: str
    model: str
    system_version: str
    serial_number: str
    install_date: str
    last_service_date: str
    warranty_expiry: str


class KnownIssue(BaseModel):
    system: str
    version: str
    release_date: str
    known_bugs: str
    patch_available: str
    notes: str = ""

    @property
    def has_bug(self) -> bool:
        return self.known_bugs.strip().lower() != "none known"


class SLAStatus(BaseModel):
    priority: str
    category: str
    first_response_minutes: int
    resolution_target_minutes: int
    escalation_to_l2_minutes: int
    first_response_due: datetime | None = None
    resolution_due: datetime | None = None
    escalate_to_l2_by: datetime | None = None


class DataFlag(BaseModel):
    """A data-quality or consistency issue found during enrichment."""

    code: str
    severity: Literal["info", "warning", "critical"]
    message: str


class EnrichedContext(BaseModel):
    store: Store | None = None
    asset: Asset | None = None
    sla: SLAStatus | None = None
    system: str | None = None
    version: str | None = None
    known_issue: KnownIssue | None = None
    system_known: bool = False
    history_summary: list[str] = Field(default_factory=list)
    l1_steps_attempted: int = 0
    related_tickets: list[dict] = Field(default_factory=list)
    similar_tickets: list[dict] = Field(default_factory=list)
    flags: list[DataFlag] = Field(default_factory=list)


class KBChunk(BaseModel):
    chunk_id: str
    doc_path: str  # relative to kb/, e.g. "runbooks/printer-offline.md"
    doc_type: str  # runbook | faq | sop | spec
    doc_title: str
    section: str
    category: str
    text: str


class RetrievedChunk(BaseModel):
    chunk: KBChunk
    score: float  # fused RRF score, normalised 0..1
    bm25_rank: int | None = None
    dense_rank: int | None = None
    dense_similarity: float | None = None


# --- agent outputs ---------------------------------------------------------------------

AutomationName = Literal["none", "restart_print_spooler", "clear_print_queue", "send_test_print"]


class LLMStep(BaseModel):
    text: str
    citations: list[str]  # e.g. ["C1", "C3"]


class GuidanceStep(LLMStep):
    grounded: bool = False  # set by the grounding guardrail, never by the LLM
    issue: str | None = None


class LLMDecision(BaseModel):
    """Exact JSON shape the LLM must return (enforced via Ollama structured output)."""

    routing: Routing
    confidence: float = Field(ge=0, le=1)
    is_printer_issue: bool
    rationale: str
    root_cause_hypothesis: str
    l1_steps_already_tried: list[str]
    steps: list[LLMStep]
    info_needed: list[str]
    escalation_reason: str | None
    suggested_automation: AutomationName
    requester_intro: str


class PolicyOverride(BaseModel):
    rule: str
    before: str
    after: str
    reason: str


class GuardrailResult(BaseModel):
    name: str
    passed: bool
    detail: str


class ProposedAction(BaseModel):
    action_id: str
    kind: Literal[
        "post_work_note", "set_routing", "send_guidance", "escalate_l2", "notify_oncall",
        "run_automation", "request_clarification", "redirect_non_it",
    ]
    title: str
    payload: dict = Field(default_factory=dict)
    requires_approval: bool
    status: Literal["proposed", "executed", "approved", "rejected", "blocked"] = "proposed"
