#!/usr/bin/env python3
"""Backfill canonical enum/date/number values for legacy Grist rows (P1-10)."""

import os
import sys
from datetime import datetime

import requests

API_KEY = os.getenv("GRIST_API_KEY")
DOC_ID = os.getenv("GRIST_DOC_ID")
BASE_URL = os.getenv("GRIST_BASE_URL", "http://127.0.0.1:8096")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
API_ERRORS = 0


STATUS_RULES: list[dict] = [
    {"table": "Billing_Account_Parties", "field": "status", "allowed": {"active", "inactive", "paused"}, "aliases": {"in-active": "inactive"}},
    {"table": "Invoices", "field": "status", "allowed": {"draft", "issued", "partial", "paid", "void"}, "aliases": {"partially_paid": "partial", "partially paid": "partial", "open": "issued"}},
    {"table": "Payments", "field": "status", "allowed": {"posted", "pending", "failed", "void"}, "aliases": {"success": "posted", "succeeded": "posted"}},
    {"table": "Subsidy_Claims", "field": "status", "allowed": {"submitted", "paid", "variance"}, "aliases": {"partial": "variance", "reconciled": "paid"}},
    {"table": "Sanitation_Checks", "field": "status", "allowed": {"completed", "issue", "skipped"}, "aliases": {"done": "completed"}},
    {"table": "Sleep_Safety_Checks", "field": "status", "allowed": {"safe", "attention", "incident"}, "aliases": {"alert": "attention"}},
    {
        "table": "Waitlist",
        "field": "status",
        "allowed": {"new", "contacted", "tour_scheduled", "offered", "enrolled", "lost"},
        "aliases": {"tour scheduled": "tour_scheduled", "tour-scheduled": "tour_scheduled"},
    },
    {
        "table": "Regulatory_Risk_Assessments",
        "field": "status",
        "allowed": {"open", "in_progress", "resolved", "closed"},
        "aliases": {"in progress": "in_progress", "in-progress": "in_progress"},
    },
    {
        "table": "Workflow_Heartbeat",
        "field": "last_status",
        "allowed": {"success", "error", "running", "unknown"},
        "aliases": {"ok": "success", "failed": "error"},
    },
]

NUMERIC_RULES: list[dict] = [
    {"table": "Billing_Account_Parties", "fields": {"share_pct": 0.0, "fixed_amount": 0.0, "priority": None}},
    {"table": "Invoices", "fields": {"subtotal": 0.0, "subsidy_credit": None, "late_fees": 0.0, "total_due": 0.0}},
    {"table": "Payments", "fields": {"amount": 0.01}},
    {"table": "Subsidy_Claims", "fields": {"expected_amount": 0.0, "received_amount": None, "variance": None}},
    {"table": "Autopay_Attempts", "fields": {"amount": 0.0}},
    {"table": "Waitlist", "fields": {"priority_score": None, "follow_up_sla_hours": 0.0, "conversion_score": None, "retention_risk_score": None}},
    {"table": "Regulatory_Risk_Assessments", "fields": {"risk_score": None}},
]

DATE_RULES: list[dict] = [
    {"table": "Invoices", "fields": ["period_start", "period_end", "due_date"]},
    {"table": "Waitlist", "fields": ["desired_start_date"]},
]

DATETIME_RULES: list[dict] = [
    {"table": "Pickup_Events", "fields": ["timestamp"]},
    {"table": "Payments", "fields": ["paid_at"]},
    {"table": "Subsidy_Claims", "fields": ["submitted_at", "paid_at"]},
    {"table": "Medication_Logs", "fields": ["administered_at"]},
    {"table": "Sanitation_Checks", "fields": ["checked_at"]},
    {"table": "Sleep_Safety_Checks", "fields": ["check_time"]},
    {"table": "Waitlist", "fields": ["last_contact_at", "tour_date", "next_follow_up_at", "automation_last_action_at", "automation_escalated_at", "automation_nudge_sent_at"]},
    {"table": "Regulatory_Rules", "fields": ["effective_date", "ingested_at"]},
    {"table": "Regulatory_Risk_Assessments", "fields": ["assessed_at"]},
    {"table": "Workflow_Heartbeat", "fields": ["last_run_at", "last_success_at", "updated_at"]},
    {"table": "Autopay_Attempts", "fields": ["attempted_at"]},
]


def api(method: str, path: str, data: dict | None = None) -> dict | None:
    """Call Grist API and return JSON payload on success."""
    global API_ERRORS
    url = f"{BASE_URL}/api/docs/{DOC_ID}{path}"
    kwargs = {"headers": HEADERS, "timeout": 30}
    if data is not None:
        kwargs["json"] = data
    try:
        response = requests.request(method, url, **kwargs)
    except requests.RequestException as exc:
        API_ERRORS += 1
        print(f"ERROR {method} {path}: {exc}")
        return None
    if response.status_code >= 400:
        API_ERRORS += 1
        print(f"ERROR {method} {path}: {response.status_code} {response.text[:300]}")
        return None
    if not response.text:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def fetch_records(table: str) -> list[dict]:
    """Read all records for a table."""
    result = api("GET", f"/tables/{table}/records")
    if not result:
        return []
    return result.get("records", [])


def patch_records(table: str, updates: list[dict], apply_changes: bool) -> bool:
    """Patch rows, or print dry-run preview."""
    if not updates:
        return True
    if not apply_changes:
        print(f"DRY-RUN {table}: {len(updates)} row(s) would be patched")
        return True
    payload = {"records": updates}
    result = api("PATCH", f"/tables/{table}/records", payload)
    return result is not None


def parse_date(raw) -> str | None:
    """Return canonical YYYY-MM-DD date string."""
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass
    dt = parse_datetime(text)
    if dt:
        return dt[:10]
    return None


def parse_datetime(raw) -> str | None:
    """Return canonical ISO datetime string (seconds precision)."""
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.isoformat(timespec="seconds")


def parse_number(raw) -> float | None:
    """Normalize numeric input into float, or None if invalid."""
    if raw in (None, ""):
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_status(raw, allowed: set[str], aliases: dict[str, str]) -> str | None:
    """Normalize status text to canonical enum value."""
    if raw in (None, ""):
        return None
    key = str(raw).strip().lower().replace("-", "_")
    key = aliases.get(key, key)
    if key in allowed:
        return key
    return None


def run_status_backfill(apply_changes: bool) -> tuple[int, int]:
    """Canonicalize enum-like status fields."""
    patched = 0
    invalid = 0
    for rule in STATUS_RULES:
        table = str(rule["table"])
        field = str(rule["field"])
        allowed = set(rule["allowed"])  # type: ignore[arg-type]
        aliases = dict(rule["aliases"])  # type: ignore[arg-type]
        updates: list[dict] = []
        records = fetch_records(table)
        for row in records:
            row_id = row.get("id")
            current = row.get("fields", {}).get(field)
            if current in (None, ""):
                continue
            normalized = normalize_status(current, allowed, aliases)
            if normalized is None:
                invalid += 1
                print(f"WARN {table}#{row_id} invalid {field}={current!r}")
                continue
            if str(current) != normalized:
                updates.append({"id": row_id, "fields": {field: normalized}})
        if patch_records(table, updates, apply_changes):
            patched += len(updates)
    return patched, invalid


def run_numeric_backfill(apply_changes: bool) -> tuple[int, int]:
    """Canonicalize numeric fields and flag invalid values."""
    patched = 0
    invalid = 0
    for rule in NUMERIC_RULES:
        table = str(rule["table"])
        field_mins: dict = dict(rule["fields"])  # type: ignore[arg-type]
        records = fetch_records(table)
        updates: list[dict] = []
        for row in records:
            row_id = row.get("id")
            row_fields = row.get("fields", {})
            patch: dict[str, float] = {}
            for field, min_value in field_mins.items():
                current = row_fields.get(field)
                if current in (None, ""):
                    continue
                normalized = parse_number(current)
                if normalized is None:
                    invalid += 1
                    print(f"WARN {table}#{row_id} invalid {field}={current!r}")
                    continue
                if min_value is not None and normalized < float(min_value):
                    invalid += 1
                    print(f"WARN {table}#{row_id} out-of-range {field}={current!r} (< {min_value})")
                    continue
                if isinstance(current, str) or float(current) != normalized:
                    patch[field] = normalized
            if patch:
                updates.append({"id": row_id, "fields": patch})
        if patch_records(table, updates, apply_changes):
            patched += len(updates)
    return patched, invalid


def run_date_backfill(apply_changes: bool) -> tuple[int, int]:
    """Canonicalize date fields and flag invalid values."""
    patched = 0
    invalid = 0
    for rule in DATE_RULES:
        table = str(rule["table"])
        fields = list(rule["fields"])  # type: ignore[arg-type]
        records = fetch_records(table)
        updates: list[dict] = []
        for row in records:
            row_id = row.get("id")
            row_fields = row.get("fields", {})
            patch: dict[str, str] = {}
            for field in fields:
                current = row_fields.get(field)
                if current in (None, ""):
                    continue
                normalized = parse_date(current)
                if not normalized:
                    invalid += 1
                    print(f"WARN {table}#{row_id} invalid {field}={current!r}")
                    continue
                if str(current) != normalized:
                    patch[field] = normalized
            if patch:
                updates.append({"id": row_id, "fields": patch})
        if patch_records(table, updates, apply_changes):
            patched += len(updates)
    return patched, invalid


def run_datetime_backfill(apply_changes: bool) -> tuple[int, int]:
    """Canonicalize datetime fields and flag invalid values."""
    patched = 0
    invalid = 0
    for rule in DATETIME_RULES:
        table = str(rule["table"])
        fields = list(rule["fields"])  # type: ignore[arg-type]
        records = fetch_records(table)
        updates: list[dict] = []
        for row in records:
            row_id = row.get("id")
            row_fields = row.get("fields", {})
            patch: dict[str, str] = {}
            for field in fields:
                current = row_fields.get(field)
                if current in (None, ""):
                    continue
                normalized = parse_datetime(current)
                if not normalized:
                    invalid += 1
                    print(f"WARN {table}#{row_id} invalid {field}={current!r}")
                    continue
                if str(current) != normalized:
                    patch[field] = normalized
            if patch:
                updates.append({"id": row_id, "fields": patch})
        if patch_records(table, updates, apply_changes):
            patched += len(updates)
    return patched, invalid


def main() -> int:
    if not API_KEY or not DOC_ID:
        print("ERROR: GRIST_API_KEY and GRIST_DOC_ID must be set")
        return 1
    apply_changes = "--apply" in sys.argv
    mode = "APPLY" if apply_changes else "DRY-RUN"
    print(f"P1-10 normalization backfill mode: {mode}")
    status_patched, status_invalid = run_status_backfill(apply_changes)
    num_patched, num_invalid = run_numeric_backfill(apply_changes)
    date_patched, date_invalid = run_date_backfill(apply_changes)
    dt_patched, dt_invalid = run_datetime_backfill(apply_changes)
    total_patched = status_patched + num_patched + date_patched + dt_patched
    total_invalid = status_invalid + num_invalid + date_invalid + dt_invalid
    print(
        "SUMMARY patched_rows=%s invalid_values=%s details(status=%s,number=%s,date=%s,datetime=%s)"
        % (
            total_patched,
            total_invalid,
            status_patched,
            num_patched,
            date_patched,
            dt_patched,
        )
    )
    if not apply_changes:
        print("Run with --apply to persist updates.")
    if API_ERRORS > 0:
        print(f"FAILED api_errors={API_ERRORS}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
