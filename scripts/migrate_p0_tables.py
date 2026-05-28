#!/usr/bin/env python3
"""Create P0 tables for guardians, pickup controls, billing, and waitlist."""

import os
import sys
import requests

API_KEY = os.getenv("GRIST_API_KEY")
DOC_ID = os.getenv("GRIST_DOC_ID")
BASE_URL = os.getenv("GRIST_BASE_URL", "http://127.0.0.1:8096")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def api(method: str, path: str, data: dict | None = None) -> dict | None:
    url = f"{BASE_URL}/api/docs/{DOC_ID}{path}"
    kwargs = {"headers": HEADERS, "timeout": 20}
    if data is not None:
        kwargs["json"] = data
    try:
        response = requests.request(method, url, **kwargs)
    except requests.RequestException as exc:
        print(f"ERROR {method} {path}: {exc}")
        return None
    if response.status_code >= 400:
        print(f"ERROR {method} {path}: {response.status_code} {response.text[:300]}")
        return None
    if not response.text:
        return {}
    return response.json()


def existing_table_names() -> set[str]:
    result = api("GET", "/tables")
    if not result:
        return set()
    names: set[str] = set()
    for table in result.get("tables", []):
        for key in ("id", "tableId", "name"):
            value = table.get(key)
            if value:
                names.add(str(value))
    return names


def create_table_if_missing(table_name: str, columns: list[dict], known: set[str]) -> None:
    if table_name in known:
        print(f"SKIP {table_name} (already exists)")
        return
    print(f"CREATE {table_name}")
    payload = {"tables": [{"id": table_name, "tableId": table_name, "columns": columns}]}
    result = api("POST", "/tables", payload)
    if result:
        print(f"  OK {table_name}")


def existing_column_ids(table_name: str) -> set[str]:
    """Return existing column ids for a table."""
    result = api("GET", f"/tables/{table_name}/columns")
    if not result:
        return set()
    ids: set[str] = set()
    for col in result.get("columns", []):
        col_id = col.get("id")
        if col_id:
            ids.add(str(col_id))
    return ids


def add_missing_columns(table_name: str, columns: list[dict]) -> None:
    """Create missing columns on an existing table."""
    existing = existing_column_ids(table_name)
    if not existing:
        return
    missing = [col for col in columns if str(col.get("id")) not in existing]
    if not missing:
        return
    print(f"ADD COLUMNS {table_name}: {', '.join(str(c.get('id')) for c in missing)}")
    payload = {"columns": missing}
    result = api("POST", f"/tables/{table_name}/columns", payload)
    if result is not None:
        print(f"  OK added {len(missing)} columns to {table_name}")


def main() -> int:
    if not API_KEY or not DOC_ID:
        print("ERROR: GRIST_API_KEY and GRIST_DOC_ID must be set")
        return 1

    tables = {
        "Guardians": [
            {"id": "first_name", "type": "Text"},
            {"id": "last_name", "type": "Text"},
            {"id": "phone", "type": "Text"},
            {"id": "email", "type": "Text"},
            {"id": "telegram_chat_id", "type": "Text"},
            {"id": "gov_id_last4", "type": "Text"},
            {"id": "is_primary", "type": "Bool"},
            {"id": "is_emergency_contact", "type": "Bool"},
        ],
        "Child_Guardians": [
            {"id": "child", "type": "Ref:Children"},
            {"id": "guardian", "type": "Ref:Guardians"},
            {"id": "legal_status", "type": "Text"},
            {"id": "pickup_allowed", "type": "Bool"},
            {"id": "pickup_password", "type": "Text"},
            {"id": "court_order_url", "type": "Text"},
            {"id": "notes", "type": "Text"},
        ],
        "Pickup_Events": [
            {"id": "child", "type": "Ref:Children"},
            {"id": "requested_by_guardian", "type": "Ref:Guardians"},
            {"id": "approved", "type": "Bool"},
            {"id": "approved_by_staff", "type": "Ref:Staff"},
            {"id": "method", "type": "Text"},
            {"id": "timestamp", "type": "DateTime"},
            {"id": "denial_reason", "type": "Text"},
            {"id": "denial_code", "type": "Text"},
            {"id": "override_used", "type": "Bool"},
            {"id": "override_reason", "type": "Text"},
            {"id": "override_approved_by", "type": "Ref:Staff"},
        ],
        "Billing_Accounts": [
            {"id": "child", "type": "Ref:Children"},
            {"id": "account_status", "type": "Text"},
            {"id": "billing_cycle", "type": "Text"},
            {"id": "autopay_enabled", "type": "Bool"},
            {"id": "autopay_token_ref", "type": "Text"},
            {"id": "late_fee_policy", "type": "Text"},
            {"id": "subsidy_program", "type": "Text"},
        ],
        "Billing_Account_Parties": [
            {"id": "account", "type": "Ref:Billing_Accounts"},
            {"id": "guardian", "type": "Ref:Guardians"},
            {"id": "payer_label", "type": "Text"},
            {"id": "share_pct", "type": "Numeric"},
            {"id": "fixed_amount", "type": "Numeric"},
            {"id": "priority", "type": "Numeric"},
            {"id": "auto_debit", "type": "Bool"},
            {"id": "status", "type": "Text"},
            {"id": "notes", "type": "Text"},
        ],
        "Invoices": [
            {"id": "account", "type": "Ref:Billing_Accounts"},
            {"id": "period_start", "type": "Date"},
            {"id": "period_end", "type": "Date"},
            {"id": "due_date", "type": "Date"},
            {"id": "subtotal", "type": "Numeric"},
            {"id": "subsidy_credit", "type": "Numeric"},
            {"id": "late_fees", "type": "Numeric"},
            {"id": "total_due", "type": "Numeric"},
            {"id": "status", "type": "Text"},
        ],
        "Payments": [
            {"id": "invoice", "type": "Ref:Invoices"},
            {"id": "amount", "type": "Numeric"},
            {"id": "paid_at", "type": "DateTime"},
            {"id": "method", "type": "Text"},
            {"id": "txn_ref", "type": "Text"},
            {"id": "status", "type": "Text"},
        ],
        "Waitlist": [
            {"id": "child_first_name", "type": "Text"},
            {"id": "child_last_name", "type": "Text"},
            {"id": "dob", "type": "Date"},
            {"id": "desired_start_date", "type": "Date"},
            {"id": "desired_schedule", "type": "Text"},
            {"id": "room_pref", "type": "Text"},
            {"id": "status", "type": "Text"},
            {"id": "priority_score", "type": "Numeric"},
            {"id": "source", "type": "Text"},
            {"id": "last_contact_at", "type": "DateTime"},
            {"id": "tour_date", "type": "DateTime"},
            {"id": "follow_up_sla_hours", "type": "Numeric"},
            {"id": "next_follow_up_at", "type": "DateTime"},
            {"id": "conversion_score", "type": "Numeric"},
            {"id": "retention_risk_score", "type": "Numeric"},
            {"id": "lost_reason", "type": "Text"},
            {"id": "automation_last_action", "type": "Text"},
            {"id": "automation_last_action_at", "type": "DateTime"},
            {"id": "automation_escalated", "type": "Bool"},
            {"id": "automation_escalated_at", "type": "DateTime"},
            {"id": "automation_escalation_reason", "type": "Text"},
            {"id": "automation_nudge_sent_at", "type": "DateTime"},
        ],
        "Subsidy_Claims": [
            {"id": "claim_month", "type": "Text"},
            {"id": "child", "type": "Ref:Children"},
            {"id": "program", "type": "Text"},
            {"id": "expected_amount", "type": "Numeric"},
            {"id": "received_amount", "type": "Numeric"},
            {"id": "variance", "type": "Numeric"},
            {"id": "status", "type": "Text"},
            {"id": "submitted_at", "type": "DateTime"},
            {"id": "paid_at", "type": "DateTime"},
            {"id": "notes", "type": "Text"},
        ],
        "Autopay_Attempts": [
            {"id": "invoice", "type": "Ref:Invoices"},
            {"id": "party", "type": "Ref:Billing_Account_Parties"},
            {"id": "amount", "type": "Numeric"},
            {"id": "attempted_at", "type": "DateTime"},
            {"id": "status", "type": "Text"},
            {"id": "processor_ref", "type": "Text"},
            {"id": "error_code", "type": "Text"},
            {"id": "error_message", "type": "Text"},
        ],
        "Medication_Logs": [
            {"id": "child", "type": "Ref:Children"},
            {"id": "medication_name", "type": "Text"},
            {"id": "dosage", "type": "Text"},
            {"id": "administered", "type": "Bool"},
            {"id": "administered_at", "type": "DateTime"},
            {"id": "administered_by", "type": "Ref:Staff"},
            {"id": "reason", "type": "Text"},
            {"id": "notes", "type": "Text"},
        ],
        "Sanitation_Checks": [
            {"id": "check_area", "type": "Text"},
            {"id": "check_item", "type": "Text"},
            {"id": "status", "type": "Text"},
            {"id": "checked_at", "type": "DateTime"},
            {"id": "checked_by", "type": "Ref:Staff"},
            {"id": "notes", "type": "Text"},
        ],
        "Sleep_Safety_Checks": [
            {"id": "child", "type": "Ref:Children"},
            {"id": "status", "type": "Text"},
            {"id": "check_time", "type": "DateTime"},
            {"id": "checked_by", "type": "Ref:Staff"},
            {"id": "notes", "type": "Text"},
        ],
        "Regulatory_Rules": [
            {"id": "rule_key", "type": "Text"},
            {"id": "version", "type": "Text"},
            {"id": "category", "type": "Text"},
            {"id": "jurisdiction", "type": "Text"},
            {"id": "title", "type": "Text"},
            {"id": "rule_text", "type": "Text"},
            {"id": "summary", "type": "Text"},
            {"id": "keywords", "type": "Text"},
            {"id": "source_url", "type": "Text"},
            {"id": "source_document", "type": "Text"},
            {"id": "effective_date", "type": "Date"},
            {"id": "active", "type": "Bool"},
            {"id": "ingested_at", "type": "DateTime"},
            {"id": "supersedes_version", "type": "Text"},
            {"id": "ingest_batch_id", "type": "Text"},
        ],
        "Regulatory_Risk_Assessments": [
            {"id": "assessed_at", "type": "DateTime"},
            {"id": "jurisdiction", "type": "Text"},
            {"id": "category", "type": "Text"},
            {"id": "status", "type": "Text"},
            {"id": "risk_score", "type": "Numeric"},
            {"id": "risk_level", "type": "Text"},
            {"id": "rule_keys", "type": "Text"},
            {"id": "findings", "type": "Text"},
            {"id": "recommended_actions", "type": "Text"},
        ],
        "Workflow_Heartbeat": [
            {"id": "workflow_key", "type": "Text"},
            {"id": "workflow_name", "type": "Text"},
            {"id": "last_status", "type": "Text"},
            {"id": "last_run_at", "type": "DateTime"},
            {"id": "last_success_at", "type": "DateTime"},
            {"id": "last_error", "type": "Text"},
            {"id": "updated_at", "type": "DateTime"},
        ],
        "Marketing_Leads": [
            {"id": "family_name", "type": "Text"},
            {"id": "email", "type": "Text"},
            {"id": "phone", "type": "Text"},
            {"id": "child_age_group", "type": "Text"},
            {"id": "channel", "type": "Text"},
            {"id": "campaign", "type": "Text"},
            {"id": "status", "type": "Text"},
            {"id": "inquiry_date", "type": "DateTime"},
            {"id": "notes", "type": "Text"},
        ],
        "Review_Requests": [
            {"id": "family_name", "type": "Text"},
            {"id": "platform", "type": "Text"},
            {"id": "status", "type": "Text"},
            {"id": "rating", "type": "Numeric"},
            {"id": "requested_at", "type": "DateTime"},
            {"id": "received_at", "type": "DateTime"},
            {"id": "review_url", "type": "Text"},
            {"id": "notes", "type": "Text"},
        ],
        "Insurance_Policies": [
            {"id": "policy_type", "type": "Text"},
            {"id": "carrier", "type": "Text"},
            {"id": "policy_number", "type": "Text"},
            {"id": "coverage_amount", "type": "Numeric"},
            {"id": "effective_date", "type": "Date"},
            {"id": "expiration_date", "type": "Date"},
            {"id": "status", "type": "Text"},
            {"id": "renewal_contact", "type": "Text"},
            {"id": "notes", "type": "Text"},
        ],
        "Competitor_Snapshots": [
            {"id": "competitor_name", "type": "Text"},
            {"id": "location", "type": "Text"},
            {"id": "tuition_band", "type": "Text"},
            {"id": "capacity_estimate", "type": "Numeric"},
            {"id": "waitlist_estimate", "type": "Numeric"},
            {"id": "source_url", "type": "Text"},
            {"id": "captured_at", "type": "DateTime"},
            {"id": "notes", "type": "Text"},
        ],
        "Marketing_Channel_Spend": [
            {"id": "channel", "type": "Text"},
            {"id": "campaign", "type": "Text"},
            {"id": "period_month", "type": "Text"},
            {"id": "spend_amount", "type": "Numeric"},
            {"id": "currency", "type": "Text"},
            {"id": "clicks", "type": "Numeric"},
            {"id": "impressions", "type": "Numeric"},
            {"id": "notes", "type": "Text"},
        ],
    }

    known = existing_table_names()
    if not known:
        print("WARN: could not list existing tables; will still attempt creates")

    for table_name, columns in tables.items():
        create_table_if_missing(table_name, columns, known)
        add_missing_columns(table_name, columns)

    print("DONE P0 table migration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
