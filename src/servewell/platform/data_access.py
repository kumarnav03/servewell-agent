"""Simulated platform 'structured data' service.

DuckDB tables over the dataset CSVs and ticket JSON stand in for the Intelligence Platform's
governed tables (stores, assets/CMDB, SLA matrix, version matrix, ITSM ticket history).
Everything here is deterministic — no LLM — so enrichment facts are always trustworthy.
"""

from datetime import datetime, timedelta
from functools import lru_cache

import duckdb
import pandas as pd

from servewell.config import get_settings
from servewell.ingest.load_dataset import load_train_tickets
from servewell.models.schemas import (
    Asset,
    DataFlag,
    EnrichedContext,
    KnownIssue,
    SLAStatus,
    Store,
    Ticket,
)

# Asset type(s) we expect a ticket in each category to reference.
EXPECTED_ASSET_TYPES = {
    "POS": {"POS Terminal"},
    "Printers": {"Receipt Printer"},
    "Wi-Fi / Network": {"Network Router"},
    "Soft Serve": {"Soft Serve Machine"},
    "Kiosks": {"Self-Order Kiosk"},
    "Online Orders": {"POS Terminal", "Receipt Printer", "Network Router"},
}

MIN_DESCRIPTION_WORDS = 12


def split_system_version(system_version: str | None) -> tuple[str | None, str | None]:
    """'FoodTech POS v4.2.1' -> ('FoodTech POS', 'v4.2.1'); 'StarMC Print v2 v3.0' -> ('StarMC Print v2', 'v3.0')."""
    if not system_version or " " not in system_version.strip():
        return (system_version or None), None
    system, version = system_version.strip().rsplit(" ", 1)
    return system, version


class DataService:
    def __init__(self):
        root = get_settings().data_root
        self.con = duckdb.connect()
        self.con.execute(f"CREATE TABLE stores AS SELECT * FROM read_csv('{root}/data/stores.csv', all_varchar=true)")
        self.con.execute(f"CREATE TABLE assets AS SELECT * FROM read_csv('{root}/data/assets.csv', all_varchar=true)")
        self.con.execute(f"CREATE TABLE sla AS SELECT * FROM read_csv('{root}/data/sla_matrix.csv')")
        self.con.execute(
            f"CREATE TABLE versions AS SELECT * FROM read_csv('{root}/kb/system-specs/version-matrix.csv', all_varchar=true)"
        )
        tickets = pd.DataFrame(
            [
                {
                    "ticket_id": t["ticket_id"],
                    "store_id": t.get("store_id"),
                    "asset_id": t.get("asset_id"),
                    "category": t.get("category"),
                    "subcategory": t.get("subcategory"),
                    "priority": t.get("priority"),
                    "subject": t.get("subject"),
                    "status": t.get("status"),
                    "date_opened": t.get("date_opened"),
                    "resolution_notes": t.get("resolution_notes"),
                }
                for t in load_train_tickets()
            ]
        )
        self.con.register("tickets_df", tickets)
        self.con.execute("CREATE TABLE tickets AS SELECT * FROM tickets_df")

    def _one(self, sql: str, params: list) -> dict | None:
        df = self.con.execute(sql, params).df()
        return None if df.empty else df.iloc[0].to_dict()

    # --- lookups -------------------------------------------------------------------------

    def get_store(self, store_id: str | None) -> Store | None:
        row = self._one("SELECT * FROM stores WHERE store_id = ?", [store_id])
        return Store(**row) if row else None

    def get_asset(self, asset_id: str | None) -> Asset | None:
        row = self._one("SELECT * FROM assets WHERE asset_id = ?", [asset_id])
        return Asset(**row) if row else None

    def store_assets(self, store_id: str) -> list[Asset]:
        df = self.con.execute("SELECT * FROM assets WHERE store_id = ?", [store_id]).df()
        return [Asset(**r) for r in df.to_dict("records")]

    def get_sla(self, priority: str, category: str | None, opened: datetime | None) -> SLAStatus | None:
        row = self._one(
            "SELECT * FROM sla WHERE priority = ? AND category = ?", [priority, category]
        ) or self._one("SELECT * FROM sla WHERE priority = ? AND category = 'General'", [priority])
        if not row:
            return None
        sla = SLAStatus(**{k: (int(v) if k.endswith("minutes") else v) for k, v in row.items()})
        if opened:
            sla.first_response_due = opened + timedelta(minutes=sla.first_response_minutes)
            sla.resolution_due = opened + timedelta(minutes=sla.resolution_target_minutes)
            sla.escalate_to_l2_by = opened + timedelta(minutes=sla.escalation_to_l2_minutes)
        return sla

    def known_issue(self, system: str | None, version: str | None) -> KnownIssue | None:
        row = self._one("SELECT * FROM versions WHERE system = ? AND version = ?", [system, version])
        return KnownIssue(**{k: (v or "") for k, v in row.items()}) if row else None

    def system_known(self, system: str | None) -> bool:
        return bool(self._one("SELECT 1 FROM versions WHERE system = ?", [system]))

    def get_ticket_summary(self, ticket_id: str) -> dict | None:
        return self._one("SELECT * FROM tickets WHERE ticket_id = ?", [ticket_id])

    def similar_tickets(self, ticket: Ticket, limit: int = 5) -> list[dict]:
        """Other tickets at the same store for the same asset or category (repeat-incident signal)."""
        df = self.con.execute(
            """
            SELECT ticket_id, date_opened, priority, category, subcategory, subject, status,
                   (asset_id = ?) AS same_asset
            FROM tickets
            WHERE ticket_id <> ? AND store_id = ? AND (asset_id = ? OR category = ?)
            ORDER BY same_asset DESC, date_opened DESC
            LIMIT ?
            """,
            [ticket.asset_id, ticket.ticket_id, ticket.store_id, ticket.asset_id, ticket.category, limit],
        ).df()
        return df.to_dict("records")

    # --- enrichment ----------------------------------------------------------------------

    def enrich(self, ticket: Ticket) -> EnrichedContext:
        ctx = EnrichedContext()
        flags = ctx.flags

        ctx.store = self.get_store(ticket.store_id)
        if not ctx.store:
            flags.append(DataFlag(code="STORE_UNKNOWN", severity="critical",
                                  message=f"Store '{ticket.store_id}' is not in the store master."))
        elif ticket.store_name and ticket.store_name != ctx.store.store_name:
            flags.append(DataFlag(code="STORE_NAME_MISMATCH", severity="warning",
                                  message=f"Ticket says '{ticket.store_name}', store master says '{ctx.store.store_name}'."))

        ctx.asset = self.get_asset(ticket.asset_id)
        if ticket.asset_id and not ctx.asset:
            flags.append(DataFlag(code="ASSET_NOT_FOUND", severity="warning",
                                  message=f"Asset '{ticket.asset_id}' does not exist in the CMDB."))
        elif not ticket.asset_id:
            flags.append(DataFlag(code="ASSET_MISSING", severity="info", message="No asset on the ticket."))
        if ctx.asset:
            if ticket.store_id and ctx.asset.store_id != ticket.store_id:
                flags.append(DataFlag(code="ASSET_STORE_MISMATCH", severity="warning",
                                      message=f"Asset belongs to {ctx.asset.store_id}, ticket is from {ticket.store_id}."))
            expected = EXPECTED_ASSET_TYPES.get(ticket.category or "")
            if expected and ctx.asset.asset_type not in expected:
                flags.append(DataFlag(code="ASSET_CATEGORY_MISMATCH", severity="warning",
                                      message=f"'{ticket.category}' ticket references a {ctx.asset.asset_type}."))
            if ticket.system_version and ctx.asset.system_version != ticket.system_version:
                flags.append(DataFlag(code="VERSION_MISMATCH", severity="warning",
                                      message=f"Ticket says '{ticket.system_version}', CMDB says '{ctx.asset.system_version}'."))

        # Prefer the CMDB version (source of truth) over what the requester typed.
        system_version = ctx.asset.system_version if ctx.asset else ticket.system_version
        ctx.system, ctx.version = split_system_version(system_version)
        ctx.system_known = self.system_known(ctx.system)
        stated_system, _ = split_system_version(ticket.system_version)
        for sys_name, label in ((ctx.system, system_version), (stated_system, ticket.system_version)):
            if sys_name and not self.system_known(sys_name):
                flags.append(DataFlag(code="UNKNOWN_SYSTEM", severity="critical",
                                      message=f"'{label}' is not in the version matrix — no supported KB coverage."))
                ctx.system_known = False
                break
        ctx.known_issue = self.known_issue(ctx.system, ctx.version)
        if ctx.known_issue and ctx.known_issue.has_bug:
            flags.append(DataFlag(code="KNOWN_BUG", severity="info",
                                  message=f"{ctx.system} {ctx.version}: {ctx.known_issue.known_bugs} "
                                          f"(patch: {ctx.known_issue.patch_available})."))

        ctx.sla = self.get_sla(ticket.priority, ticket.category, ticket.date_opened)

        for h in ticket.ticket_history:
            ctx.history_summary.append(f"[{h.timestamp or '?'}] {h.actor or 'Unknown'}: {h.note}")
            if h.actor and h.actor.startswith("L1"):
                ctx.l1_steps_attempted += 1
        if ctx.l1_steps_attempted:
            flags.append(DataFlag(code="L1_ALREADY_ATTEMPTED", severity="info",
                                  message=f"{ctx.l1_steps_attempted} prior L1 troubleshooting entries on this ticket."))
        if ticket.escalation_flag:
            flags.append(DataFlag(code="ESCALATION_FLAG_SET", severity="info",
                                  message="Ticket was already flagged for escalation by the submitter/L1."))

        ctx.related_tickets = [r for r in (self.get_ticket_summary(t) for t in ticket.related_tickets) if r]
        ctx.similar_tickets = self.similar_tickets(ticket)
        if any(s["same_asset"] for s in ctx.similar_tickets):
            flags.append(DataFlag(code="REPEAT_INCIDENT", severity="info",
                                  message="Other tickets exist for this same asset — possible recurring fault."))

        words = len(f"{ticket.subject} {ticket.description}".split())
        if words < MIN_DESCRIPTION_WORDS:
            flags.append(DataFlag(code="SPARSE_DESCRIPTION", severity="warning",
                                  message=f"Only {words} words of description — may need clarification."))
        return ctx


@lru_cache
def get_data_service() -> DataService:
    return DataService()
