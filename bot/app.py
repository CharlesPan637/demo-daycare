"""Daycare Telegram Bot — Flask API + Telegram polling bridge."""

import logging
import math
import os
import re
import threading
import time
import uuid
import hashlib
import json
from functools import wraps
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any

import requests
from flask import Flask, request, jsonify, g, make_response

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Shared secret for API authentication (n8n webhooks, external callers).
# Requests must include header  X-API-Key: <value>
API_KEY = os.getenv("API_KEY", "")
API_KEY_NEXT = os.getenv("API_KEY_NEXT", "").strip()
API_KEY_NEXT_ACTIVE_UNTIL = os.getenv("API_KEY_NEXT_ACTIVE_UNTIL", "").strip()
PUBLIC_ROUTES = {"health", "openapi_spec"}  # endpoint names that skip auth
INSECURE_DEMO_MODE = os.getenv("INSECURE_DEMO_MODE", "").strip().lower() in {"1", "true", "yes"}
IDEMPOTENCY_ENABLED = os.getenv("IDEMPOTENCY_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
try:
    IDEMPOTENCY_TTL_SECONDS = max(60, int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400")))
except ValueError:
    IDEMPOTENCY_TTL_SECONDS = 86400
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").strip().lower() in {"1", "true", "yes"}
try:
    RATE_LIMIT_PER_WINDOW = max(1, int(os.getenv("RATE_LIMIT_PER_WINDOW", "120")))
except ValueError:
    RATE_LIMIT_PER_WINDOW = 120
try:
    RATE_LIMIT_WINDOW_SECONDS = max(1, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")))
except ValueError:
    RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_STORE: dict[str, list[float]] = {}


def _default_error_code(status_code: int) -> str:
    """Map HTTP status to stable error code label."""
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "unprocessable_entity"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "internal_error"
    return "request_failed"


def _normalize_error_payload(payload, status_code: int, request_id: str) -> dict:
    """Normalize any error payload into a consistent envelope."""
    try:
        default_message = HTTPStatus(status_code).phrase
    except ValueError:
        default_message = "Request failed"
    error_code = _default_error_code(status_code)
    message = default_message
    details = None

    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            error_code = str(err.get("code", error_code))
            message = str(err.get("message") or err.get("detail") or message)
            if "details" in err:
                details = err.get("details")
        elif isinstance(err, str) and err.strip():
            message = err.strip()
        elif isinstance(payload.get("message"), str) and payload.get("message", "").strip():
            message = str(payload.get("message")).strip()
        if details is None and "details" in payload:
            details = payload.get("details")

    envelope = {
        "error": {
            "code": error_code,
            "message": message,
            "request_id": request_id,
        }
    }
    if details is not None:
        envelope["error"]["details"] = details
    return envelope


def _parse_env_iso_datetime(value: str) -> datetime | None:
    """Parse env datetime values in ISO format (supports trailing Z)."""
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _is_next_api_key_active(now_utc: datetime | None = None) -> bool:
    """Return whether API_KEY_NEXT is currently accepted."""
    if not API_KEY_NEXT:
        return False
    if not API_KEY_NEXT_ACTIVE_UNTIL:
        return True
    active_until = _parse_env_iso_datetime(API_KEY_NEXT_ACTIVE_UNTIL)
    if not active_until:
        logger.error("API_KEY_NEXT_ACTIVE_UNTIL is invalid: %r", API_KEY_NEXT_ACTIVE_UNTIL)
        return False
    now_utc = now_utc or datetime.utcnow()
    if active_until.tzinfo is not None:
        # Compare in the same timezone when the configured timestamp is offset-aware.
        now_utc = now_utc.replace(tzinfo=active_until.tzinfo)
    return now_utc <= active_until


@app.before_request
def _init_request_context():
    """Initialize request ID and timing metadata for all requests."""
    incoming_request_id = request.headers.get("X-Request-Id", "").strip()
    g.request_id = incoming_request_id or uuid.uuid4().hex
    g.request_started_at = time.time()
    return None


@app.before_request
def _require_api_key():
    """Reject unauthenticated requests on all non-public routes."""
    if request.endpoint in PUBLIC_ROUTES:
        return None
    if not API_KEY:
        if INSECURE_DEMO_MODE:
            return None
        return jsonify({"error": "server_misconfigured", "detail": "API_KEY is not configured"}), 503
    token = request.headers.get("X-API-Key", "")
    if token == API_KEY:
        return None
    if token == API_KEY_NEXT and _is_next_api_key_active():
        return None
    if token == API_KEY_NEXT and API_KEY_NEXT:
        return jsonify({
            "error": {
                "code": "unauthorized",
                "message": "next API key rotation window expired",
            }
        }), 401
    return jsonify({"error": "unauthorized"}), 401


@app.before_request
def _enforce_rate_limit():
    """Apply per-API-key throttling for protected routes."""
    if not RATE_LIMIT_ENABLED:
        return None
    if request.endpoint in PUBLIC_ROUTES:
        return None
    token = request.headers.get("X-API-Key", "").strip()
    if not token:
        return None

    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    key_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    with _RATE_LIMIT_LOCK:
        history = _RATE_LIMIT_STORE.get(key_hash, [])
        history = [ts for ts in history if ts >= window_start]
        if len(history) >= RATE_LIMIT_PER_WINDOW:
            retry_after_seconds = max(1, int(history[0] + RATE_LIMIT_WINDOW_SECONDS - now))
            _RATE_LIMIT_STORE[key_hash] = history
            logger.warning(
                "rate_limit_exceeded key_hash=%s route=%s method=%s limit=%s window_seconds=%s retry_after=%s",
                key_hash,
                request.path,
                request.method,
                RATE_LIMIT_PER_WINDOW,
                RATE_LIMIT_WINDOW_SECONDS,
                retry_after_seconds,
            )
            response = jsonify({
                "error": {
                    "code": "rate_limited",
                    "message": "rate limit exceeded",
                    "details": {
                        "retry_after_seconds": retry_after_seconds,
                        "limit": RATE_LIMIT_PER_WINDOW,
                        "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
                    },
                }
            })
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after_seconds)
            return response
        history.append(now)
        _RATE_LIMIT_STORE[key_hash] = history
    return None


@app.before_request
def _validate_request_payload():
    """Validate JSON payloads for selected write routes using schema map."""
    if request.method not in {"POST", "PATCH", "PUT"}:
        return None
    if not request.url_rule:
        return None
    rule = request.url_rule.rule
    schema = REQUEST_VALIDATION_SCHEMAS.get((request.method, rule))
    if not schema:
        return None
    data = request.get_json(silent=True)
    if data is None:
        return _validation_error_response([{"field": "body", "message": "must be valid JSON object"}])
    if not isinstance(data, dict):
        return _validation_error_response([{"field": "body", "message": "must be a JSON object"}])
    errors = _validate_json_against_schema(data, schema, path="body")
    errors.extend(_extra_validation_errors(rule, data))
    if errors:
        return _validation_error_response(errors)
    return None


@app.after_request
def _attach_request_metadata(response):
    """Attach request ID header and normalize all non-2xx errors."""
    request_id = getattr(g, "request_id", "")
    response.headers["X-Request-Id"] = request_id

    if response.status_code >= 400:
        payload = response.get_json(silent=True)
        normalized = _normalize_error_payload(payload, response.status_code, request_id)
        normalized_response = jsonify(normalized)
        normalized_response.status_code = response.status_code
        normalized_response.headers["X-Request-Id"] = request_id
        if response.headers.get("Retry-After"):
            normalized_response.headers["Retry-After"] = response.headers.get("Retry-After")
        response = normalized_response

    started = getattr(g, "request_started_at", None)
    duration_ms = int((time.time() - started) * 1000) if isinstance(started, (int, float)) else -1
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%s",
        request_id,
        request.method,
        request.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.route("/openapi.json", methods=["GET"])
def openapi_spec():
    """Return OpenAPI specification for the current API surface."""
    global _OPENAPI_CACHE
    if _OPENAPI_CACHE is None:
        _OPENAPI_CACHE = _build_openapi_spec()
    return jsonify(_OPENAPI_CACHE)


# --- Grist integration ---
GRIST_AVAILABLE = False
try:
    from grist_client import (  # noqa: E402
        get_children,
        find_child,
        find_child_by_id,
        get_daily_report,
        get_milestones,
        get_activities,
        log_attendance,
        add_milestone,
        get_child_field,
        child_id,
        get_parent_chat_id,
        set_parent_link,
        get_staff_availability,
        find_substitutes,
        get_room_ratios,
        get_subsidies,
        get_urgent_subsidies,
        create_subsidy_claim,
        get_subsidy_claims,
        update_subsidy_claim,
        get_enrollment_history,
        get_incidents,
        get_health_summary,
        get_health_history,
        get_vaccine_summary,
        get_portfolio_moments,
        get_monthly_book,
        get_all_monthly_books,
        add_portfolio_moment,
        schedule_meeting,
        get_meetings,
        get_parent_meetings,
        get_all_parent_chat_ids,
        create_announcement,
        get_announcements,
        log_menu_item,
        get_daily_menu,
        add_menu_comment,
        get_menu_comments,
        set_daily_activity,
        get_daily_schedule,
        add_contingency_teacher,
        get_contingency_teachers,
        find_contingency_teachers,
        create_guardian,
        link_child_guardian,
        get_child_guardian_links,
        get_guardian_by_id,
        get_child_guardians,
        update_child_guardian_link,
        get_pickup_events,
        add_pickup_event,
        create_billing_account,
        get_billing_accounts,
        create_billing_account_party,
        get_billing_account_parties,
        update_billing_account_party,
        create_autopay_attempt,
        get_autopay_attempts,
        create_invoices,
        get_invoices,
        get_invoice,
        add_payment,
        get_payments,
        update_invoice,
        get_waitlist,
        add_waitlist_entry,
        update_waitlist_entry,
        add_medication_log,
        get_medication_logs,
        add_sanitation_check,
        get_sanitation_checks,
        add_sleep_safety_check,
        get_sleep_safety_checks,
        create_regulatory_rule,
        update_regulatory_rule,
        get_regulatory_rules,
        get_regulatory_rule_versions,
        find_regulatory_rule_version,
        create_regulatory_risk_assessment,
        get_regulatory_risk_assessments,
        get_workflow_heartbeats,
        upsert_workflow_heartbeat,
        create_marketing_lead,
        get_marketing_leads,
        create_review_request,
        get_review_requests,
        create_insurance_policy,
        get_insurance_policies,
        update_insurance_policy,
        create_competitor_snapshot,
        get_competitor_snapshots,
        create_marketing_channel_spend,
        get_marketing_channel_spend,
        create_marketing_touchpoint,
        get_marketing_touchpoints,
    )
    from regulatory_rag import get_regulatory_answer  # noqa: E402

    GRIST_AVAILABLE = True
except Exception as e:
    logger.warning("Grist client not available: %s", e)
    # Define safe stubs so command handlers don't raise NameError at runtime
    get_children = lambda: []  # type: ignore[assignment]
    find_child = lambda _n: None  # type: ignore[assignment]
    find_child_by_id = lambda _i: None  # type: ignore[assignment]
    get_daily_report = lambda _c, _d: None  # type: ignore[assignment]
    get_milestones = lambda _c, limit=5: []  # type: ignore[assignment]
    get_activities = lambda _d: []  # type: ignore[assignment]
    log_attendance = lambda *a, **kw: None  # type: ignore[assignment]
    add_milestone = lambda *a, **kw: None  # type: ignore[assignment]
    get_child_field = lambda _c, _f: ""  # type: ignore[assignment]
    child_id = lambda _c: None  # type: ignore[assignment]
    get_parent_chat_id = lambda _c: None  # type: ignore[assignment]
    set_parent_link = lambda _c, _ch: None  # type: ignore[assignment]
    get_staff_availability = lambda _d=None: []  # type: ignore[assignment]
    find_substitutes = lambda _d, _r: []  # type: ignore[assignment]
    get_room_ratios = lambda: []  # type: ignore[assignment]
    get_subsidies = lambda _s=None: []  # type: ignore[assignment]
    get_urgent_subsidies = lambda: []  # type: ignore[assignment]
    create_subsidy_claim = lambda _f: None  # type: ignore[assignment]
    get_subsidy_claims = lambda _m=None, _s=None, _p=None: []  # type: ignore[assignment]
    update_subsidy_claim = lambda _i, _f: None  # type: ignore[assignment]
    get_enrollment_history = lambda: []  # type: ignore[assignment]
    get_incidents = lambda _c=None: []  # type: ignore[assignment]
    get_health_summary = lambda: {"allergies": {}, "total_incidents": 0, "incidents": []}  # type: ignore[assignment]
    get_health_history = lambda _c=None: []  # type: ignore[assignment]
    get_vaccine_summary = lambda: {}  # type: ignore[assignment]
    get_portfolio_moments = lambda _c=None, limit=20: []  # type: ignore[assignment]
    get_monthly_book = lambda _c, _m=None: None  # type: ignore[assignment]
    get_all_monthly_books = lambda _m=None: []  # type: ignore[assignment]
    add_portfolio_moment = lambda *a, **kw: None  # type: ignore[assignment]
    schedule_meeting = lambda *a, **kw: None  # type: ignore[assignment]
    get_meetings = lambda _d=None, _t=None, limit=20: []  # type: ignore[assignment]
    get_parent_meetings = lambda _c: []  # type: ignore[assignment]
    get_all_parent_chat_ids = lambda: []  # type: ignore[assignment]
    create_announcement = lambda *a, **kw: None  # type: ignore[assignment]
    get_announcements = lambda limit=10: []  # type: ignore[assignment]
    log_menu_item = lambda *a, **kw: None  # type: ignore[assignment]
    get_daily_menu = lambda _d: []  # type: ignore[assignment]
    add_menu_comment = lambda *a, **kw: None  # type: ignore[assignment]
    get_menu_comments = lambda _d: []  # type: ignore[assignment]
    set_daily_activity = lambda *a, **kw: None  # type: ignore[assignment]
    get_daily_schedule = lambda _d: []  # type: ignore[assignment]
    add_contingency_teacher = lambda *a, **kw: None  # type: ignore[assignment]
    get_contingency_teachers = lambda: []  # type: ignore[assignment]
    find_contingency_teachers = lambda _r="": []  # type: ignore[assignment]
    create_guardian = lambda _f: None  # type: ignore[assignment]
    link_child_guardian = lambda *a, **kw: None  # type: ignore[assignment]
    get_child_guardian_links = lambda _c: []  # type: ignore[assignment]
    get_guardian_by_id = lambda _g: None  # type: ignore[assignment]
    get_child_guardians = lambda _c: []  # type: ignore[assignment]
    update_child_guardian_link = lambda _i, _f: None  # type: ignore[assignment]
    get_pickup_events = lambda _c=None, _a=None: []  # type: ignore[assignment]
    add_pickup_event = lambda *a, **kw: None  # type: ignore[assignment]
    create_billing_account = lambda _f: None  # type: ignore[assignment]
    get_billing_accounts = lambda _c=None: []  # type: ignore[assignment]
    create_billing_account_party = lambda _f: None  # type: ignore[assignment]
    get_billing_account_parties = lambda _a=None, _s=None: []  # type: ignore[assignment]
    update_billing_account_party = lambda _i, _f: None  # type: ignore[assignment]
    create_autopay_attempt = lambda _f: None  # type: ignore[assignment]
    get_autopay_attempts = lambda _i=None, _p=None: []  # type: ignore[assignment]
    create_invoices = lambda _invoices: None  # type: ignore[assignment]
    get_invoices = lambda status=None, account_id=None: []  # type: ignore[assignment]
    get_invoice = lambda _i: None  # type: ignore[assignment]
    add_payment = lambda _f: None  # type: ignore[assignment]
    get_payments = lambda _i=None: []  # type: ignore[assignment]
    update_invoice = lambda _i, _f: None  # type: ignore[assignment]
    get_waitlist = lambda _s=None: []  # type: ignore[assignment]
    add_waitlist_entry = lambda _f: None  # type: ignore[assignment]
    update_waitlist_entry = lambda _i, _f: None  # type: ignore[assignment]
    add_medication_log = lambda _f: None  # type: ignore[assignment]
    get_medication_logs = lambda _c=None: []  # type: ignore[assignment]
    add_sanitation_check = lambda _f: None  # type: ignore[assignment]
    get_sanitation_checks = lambda _s=None: []  # type: ignore[assignment]
    add_sleep_safety_check = lambda _f: None  # type: ignore[assignment]
    get_sleep_safety_checks = lambda _c=None, _s=None: []  # type: ignore[assignment]
    create_regulatory_rule = lambda _f: None  # type: ignore[assignment]
    update_regulatory_rule = lambda _i, _f: None  # type: ignore[assignment]
    get_regulatory_rules = lambda _k=None, _j=None, _c=None, active_only=True: []  # type: ignore[assignment]
    get_regulatory_rule_versions = lambda _k: []  # type: ignore[assignment]
    find_regulatory_rule_version = lambda _k, _v: None  # type: ignore[assignment]
    create_regulatory_risk_assessment = lambda _f: None  # type: ignore[assignment]
    get_regulatory_risk_assessments = lambda _s=None, _c=None: []  # type: ignore[assignment]
    get_workflow_heartbeats = lambda _k=None: []  # type: ignore[assignment]
    upsert_workflow_heartbeat = lambda _k, _f: None  # type: ignore[assignment]
    create_marketing_lead = lambda _f: None  # type: ignore[assignment]
    get_marketing_leads = lambda _c=None, _s=None: []  # type: ignore[assignment]
    create_review_request = lambda _f: None  # type: ignore[assignment]
    get_review_requests = lambda _p=None, _s=None: []  # type: ignore[assignment]
    create_insurance_policy = lambda _f: None  # type: ignore[assignment]
    get_insurance_policies = lambda _s=None: []  # type: ignore[assignment]
    update_insurance_policy = lambda _i, _f: None  # type: ignore[assignment]
    create_competitor_snapshot = lambda _f: None  # type: ignore[assignment]
    get_competitor_snapshots = lambda _n=None: []  # type: ignore[assignment]
    create_marketing_channel_spend = lambda _f: None  # type: ignore[assignment]
    get_marketing_channel_spend = lambda _c=None, _ca=None, _pm=None: []  # type: ignore[assignment]
    create_marketing_touchpoint = lambda _f: None  # type: ignore[assignment]
    get_marketing_touchpoints = lambda _l=None, _c=None: []  # type: ignore[assignment]
    get_regulatory_answer = lambda _q, dynamic_rules=None: None  # type: ignore[assignment]

# --- AI client ---
AI_AVAILABLE = False
try:
    from ai_client import tag_milestone, ask_question  # noqa: E402

    AI_AVAILABLE = True
except Exception as e:
    logger.warning("AI client not available: %s", e)
    tag_milestone = lambda _n: None  # type: ignore[assignment]
    ask_question = lambda _q: "I'm sorry, the AI service is currently unavailable."  # type: ignore[assignment]

# Dashboard fallback responses used by /ask when Grist is unavailable.
# Milestone tagging and Q&A are handled by ai_client; these cover the
# agent-style dashboard commands (staffing, subsidies, forecast, health).
DASHBOARD_FALLBACKS = {
    "staffing": {
        "response": (
            "📊 *Morning Staffing Copilot*\n\n"
            "Today's coverage (Wednesday):\n"
            "• Infant Room (1:4 ratio): Maria Gonzalez 7:30–16:00 ✓ Covered\n"
            "• Toddler Room (1:6 ratio): David Kim 8:00–16:00 ✓ Covered\n"
            "• Preschool Room (1:10 ratio): ⚠ No lead assigned — Sarah Chen on call\n"
            "• Pre-K Room (1:12 ratio): David Kim also covering\n\n"
            "⚠ Ratio alert: Preschool room needs coverage. Sarah Chen available as admin float.\n"
            "Suggest: Activate Sarah Chen for Preschool coverage 9:00–15:00."
        ),
    },
    "subsidy": {
        "response": (
            "💰 *Subsidy Compliance Agent*\n\n"
            "Active subsidies: 4 families\n"
            "• Emma Johnson — CCAP State Subsidy, $850/mo, reauth by Jun 15 ✓\n"
            "• Noah Williams — CCAP State Subsidy, $850/mo, reauth by Jul 1 ✓\n"
            "• Ava Thompson — Head Start (Federal), $1100/mo, reauth by Aug 15 ✓\n"
            "• Isabella Brown — CCAP State Subsidy, $850/mo, reauth by Jun 5 ⚠ URGENT\n\n"
            "⚠ Action needed: Isabella's reauthorization due in 9 days. "
            "Case worker: Janet Miller (555) 456-7001. Income verification required."
        ),
    },
    "forecast": {
        "response": (
            "📈 *Enrollment Forecaster*\n\n"
            "Enrollment trend (Jan–May 2026):\n"
            "Jan: 6 → Feb: 6 → Mar: 7 → Apr: 7 → May: 8\n\n"
            "Current: 8 enrolled (100% capacity)\n"
            "Waitlist: 5 families\n\n"
            "⚠ Summer warning: 2 families reducing to part-time June–August.\n"
            "Projected June revenue: $29,500 → $22,000 (3 full-time → 2 part-time)\n"
            "Recommendation: Offer waitlist families summer-only slots to fill gap.\n\n"
            "Revenue trend: Jan $22,500 → May $29,500 (+31% YTD)"
        ),
    },
    "health": {
        "response": (
            "🏥 *Cross-Room Health Dashboard*\n\n"
            "Allergy Summary:\n"
            "• Liam Martinez — Peanut (severe, EpiPen)\n"
            "• Sophia Chen — Dairy\n"
            "• Ava Thompson — Egg\n"
            "• Isabella Brown — Gluten\n\n"
            "Recent Incidents (last 7 days):\n"
            "• May 20 — Liam: Minor injury (playground scrape, resolved)\n"
            "• May 24 — Oliver: Behavioral (toy dispute, redirected)\n\n"
            "Food service alert: 4 allergies across 3 rooms. "
            "Confirm all snack/lunch substitutions documented in kitchen log."
        ),
    },
}

# --- Flask API (for n8n and internal) ---


@app.route("/health", methods=["GET"])
def health():
    """Health-check endpoint. Reports whether Grist and AI backends are reachable."""
    return jsonify({"status": "ok", "grist": GRIST_AVAILABLE, "ai": AI_AVAILABLE})


@app.route("/report/<child_name>", methods=["GET"])
def api_report(child_name):
    """Return today's daily report for *child_name* as JSON."""
    child = find_child(child_name)
    if not child:
        return jsonify({"error": f"Child '{child_name}' not found"}), 404
    today = datetime.now().strftime("%Y-%m-%d")
    report = get_daily_report(child_id(child), today)
    if not report:
        return jsonify({"error": f"No report for {child_name} today"}), 404
    return jsonify({"child": get_child_field(child, "first_name"), "report": report})

@app.route("/vaccines/<child_name>", methods=["GET"])
def api_vaccines(child_name):
    """Return health history (vaccines, allergies, doctors) for *child_name*."""
    child = find_child(child_name)
    if not child:
        return jsonify({"error": f"Child '{child_name}' not found"}), 404
    health_records = get_health_history(child_id(child))
    if health_records:
        return jsonify({"child": get_child_field(child, "first_name"),
                        "health_history": health_records[0]["fields"]})
    return jsonify({"child": get_child_field(child, "first_name"),
                    "health_history": None})

@app.route("/vaccines", methods=["GET"])
def api_vaccines_summary():
    """Return vaccine compliance summary for all children."""
    return jsonify({"summary": get_vaccine_summary()})

@app.route("/portfolio/<child_name>", methods=["GET"])
def api_portfolio(child_name):
    """Return portfolio moments for *child_name*."""
    child = find_child(child_name)
    if not child:
        return jsonify({"error": f"Child '{child_name}' not found"}), 404
    moments = get_portfolio_moments(child_id(child))
    return jsonify({"child": get_child_field(child, "first_name"),
                    "moments": [m["fields"] for m in moments]})

@app.route("/book/<child_name>", methods=["GET"])
def api_book(child_name):
    """Return the monthly milestone book for *child_name* (optional ?month=YYYY-MM)."""
    child = find_child(child_name)
    if not child:
        return jsonify({"error": f"Child '{child_name}' not found"}), 404
    from flask import request as flask_request
    month = flask_request.args.get("month", datetime.now().strftime("%Y-%m"))
    book = get_monthly_book(child_id(child), month)
    if not book:
        return jsonify({"error": f"No book for {child_name} in {month}"}), 404
    return jsonify({"child": get_child_field(child, "first_name"), "book": book["fields"]})

@app.route("/books", methods=["GET"])
def api_books():
    """Return all monthly books (optional ?month=YYYY-MM)."""
    from flask import request as flask_request
    month = flask_request.args.get("month", datetime.now().strftime("%Y-%m"))
    books = get_all_monthly_books(month)
    return jsonify({"month": month, "books": [b["fields"] for b in books]})

@app.route("/webhook/milestone", methods=["POST"])
def webhook_milestone():
    """Notify a parent via Telegram when a new milestone is recorded (called by n8n)."""
    data = request.get_json(force=True, silent=True) or {}
    child_id_val = data.get("child_id")
    child_name = data.get("child_name", "")
    description = data.get("description", "")
    tags = data.get("tags", "")
    category = data.get("category", "")

    if not child_id_val:
        return jsonify({"error": "child_id required"}), 400

    parent_chat_id = get_parent_chat_id(child_id_val)
    if not parent_chat_id:
        return jsonify({"status": "skipped", "reason": "no parent_chat_id"}), 200

    if not child_name:
        child = find_child_by_id(child_id_val)
        child_name = child["fields"]["first_name"] if child else "Your child"

    msg = (f"🌟 *New Milestone!*\n\n"
           f"Your child *{child_name}* just achieved something special:\n\n"
           f"📝 _{description}_\n\n"
           f"🏷 {tags if tags else category}\n\n"
           f"Use /report {child_name.lower()} for today's full update.")
    sent = send_telegram_msg(parent_chat_id, msg)
    return jsonify({"status": "sent" if sent else "failed", "chat_id": parent_chat_id})

@app.route("/webhook/moment", methods=["POST"])
def webhook_moment():
    """Notify a parent via Telegram when a new portfolio moment is added (called by n8n)."""
    data = request.get_json(force=True, silent=True) or {}
    child_id_val = data.get("child_id")
    child_name = data.get("child_name", "")
    title = data.get("title", "")
    description = data.get("description", "")
    moment_type = data.get("moment_type", "Photo")

    if not child_id_val:
        return jsonify({"error": "child_id required"}), 400

    parent_chat_id = get_parent_chat_id(child_id_val)
    if not parent_chat_id:
        return jsonify({"status": "skipped", "reason": "no parent_chat_id"}), 200

    if not child_name:
        child = find_child_by_id(child_id_val)
        child_name = child["fields"]["first_name"] if child else "Your child"

    type_emoji = {"Photo": "📸", "Video": "🎬", "Audio": "🎵", "Drawing": "🎨"}
    emoji = type_emoji.get(moment_type, "📌")

    msg = (f"{emoji} *New Portfolio Moment!*\n\n"
           f"A new memory was captured for *{child_name}*:\n\n"
           f"*{title}*\n"
           f"_{description}_\n\n"
           f"Use /portfolio {child_name.lower()} to see all moments.")
    sent = send_telegram_msg(parent_chat_id, msg)
    return jsonify({"status": "sent" if sent else "failed", "chat_id": parent_chat_id})

@app.route("/parent-chat/<child_name>", methods=["GET"])
def api_parent_chat(child_name):
    """Return the linked parent Telegram chat_id for *child_name* (used by n8n)."""
    child = find_child(child_name)
    if not child:
        return jsonify({"error": f"Child '{child_name}' not found"}), 404
    chat_id = get_parent_chat_id(child_id(child))
    return jsonify({"child": child["fields"]["first_name"], "parent_chat_id": chat_id})


@app.route("/webhook/meeting", methods=["POST"])
def webhook_meeting():
    """Notify a parent via Telegram when a parent-teacher meeting is scheduled (called by n8n)."""
    data = request.get_json(force=True, silent=True) or {}
    child_id_val = data.get("child_id")
    child_name = data.get("child_name", "")
    title = data.get("title", "Parent-Teacher Meeting")
    meeting_date = data.get("date", "")
    meeting_time = data.get("time", "")
    description = data.get("description", "")

    if not child_id_val:
        return jsonify({"error": "child_id required"}), 400

    parent_chat_id = get_parent_chat_id(child_id_val)
    if not parent_chat_id:
        return jsonify({"status": "skipped", "reason": "no parent_chat_id"}), 200

    if not child_name:
        child = find_child_by_id(child_id_val)
        child_name = child["fields"]["first_name"] if child else "Your child"

    msg = (
        f"📅 *Meeting Scheduled!*\n\n"
        f"A parent-teacher meeting has been scheduled for *{child_name}*:\n\n"
        f"📌 *{title}*\n"
        f"📅 Date: {meeting_date}\n"
        f"🕐 Time: {meeting_time}\n"
    )
    if description:
        msg += f"\n📝 _{description}_\n"
    msg += f"\nUse /meetings to see all upcoming meetings."

    sent = send_telegram_msg(parent_chat_id, msg)
    return jsonify({"status": "sent" if sent else "failed", "chat_id": parent_chat_id})


@app.route("/webhook/announcement", methods=["POST"])
def webhook_announcement():
    """Broadcast an announcement to all linked parents via Telegram (called by n8n)."""
    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title", "Announcement")
    message = data.get("message", "")
    priority = data.get("priority", "normal")

    if not message:
        return jsonify({"error": "message required"}), 400

    priority_emoji = {"urgent": "🚨", "important": "⚠️", "normal": "📢"}
    emoji = priority_emoji.get(priority, "📢")

    msg = (
        f"{emoji} *{title}*\n\n"
        f"{message}\n\n"
        f"_— Sunshine Sprouts Early Learning Center_"
    )

    parents = get_all_parent_chat_ids()
    sent_count = 0
    for chat_id, _name in parents:
        if send_telegram_msg(chat_id, msg):
            sent_count += 1

    # Also log to Grist if available
    if GRIST_AVAILABLE:
        create_announcement(title, message, priority=priority)

    return jsonify({"status": "broadcast", "sent_to": sent_count, "total_parents": len(parents)})


@app.route("/menu/<date>", methods=["GET"])
def api_menu(date):
    """Return the full daily menu for *date* (YYYY-MM-DD) including parent comments."""
    items = get_daily_menu(date)
    comments = get_menu_comments(date)

    meal_labels = {
        "breakfast": "🍳 Breakfast",
        "am_snack": "🍎 Morning Snack",
        "lunch": "🍽 Lunch",
        "pm_snack": "🍪 Afternoon Snack",
        "drinks": "🥤 Drinks",
    }

    menu = []
    for item in items:
        f = item["fields"]
        menu.append({
            "meal_type": f.get("meal_type", ""),
            "label": meal_labels.get(f.get("meal_type", ""), f.get("meal_type", "")),
            "description": f.get("description", ""),
        })

    return jsonify({
        "date": date,
        "menu": menu,
        "comments": [{"parent_name": c["fields"].get("parent_name", "Anonymous"),
                       "comment": c["fields"].get("comment", "")} for c in comments],
    })


@app.route("/webhook/menu", methods=["POST"])
def webhook_menu():
    """Notify all linked parents that today's menu has been posted (called by n8n)."""
    data = request.get_json(force=True, silent=True) or {}
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))

    items = get_daily_menu(date_str)
    if not items:
        return jsonify({"status": "skipped", "reason": "no menu for date"}), 200

    meal_labels = {
        "breakfast": "🍳 Breakfast",
        "am_snack": "🍎 Morning Snack",
        "lunch": "🍽 Lunch",
        "pm_snack": "🍪 Afternoon Snack",
        "drinks": "🥤 Drinks",
    }

    lines = [f"🍽 *Daily Menu — {date_str}*", ""]
    for item in items:
        f = item["fields"]
        label = meal_labels.get(f.get("meal_type", ""), f.get("meal_type", ""))
        lines.append(f"{label}: {f.get('description', '')}")
    lines.extend(["", "Use `/menu` to view details and leave a comment."])

    msg = "\n".join(lines)
    parents = get_all_parent_chat_ids()
    sent_count = 0
    for chat_id, _name in parents:
        if send_telegram_msg(chat_id, msg):
            sent_count += 1

    return jsonify({"status": "notified", "sent_to": sent_count, "total_parents": len(parents)})


@app.route("/schedule/<date>", methods=["GET"])
def api_daily_schedule(date):
    """Return the full daily schedule for *date* (nap, outdoor, class, craft times)."""
    blocks = get_daily_schedule(date)

    activity_emoji = {
        "nap": "😴", "outdoor": "🌳", "class": "📚", "craft": "🎨",
    }
    activity_labels = {
        "nap": "Nap Time", "outdoor": "Outdoor Play",
        "class": "Class Time", "craft": "Craft Time",
    }

    schedule = []
    for b in blocks:
        f = b["fields"]
        atype = f.get("activity_type", "")
        schedule.append({
            "activity_type": atype,
            "label": activity_labels.get(atype, atype),
            "emoji": activity_emoji.get(atype, ""),
            "start_time": f.get("start_time", ""),
            "end_time": f.get("end_time", ""),
            "description": f.get("description", ""),
            "room": f.get("room", ""),
        })

    return jsonify({"date": date, "schedule": schedule})


@app.route("/substitutes", methods=["GET"])
def api_substitutes():
    """Return the contingency teacher roster, optionally filtered by ?room=."""
    room = request.args.get("room", "")
    teachers = find_contingency_teachers(room)
    return jsonify({
        "count": len(teachers),
        "substitutes": [t["fields"] for t in teachers],
    })


def _to_float(value) -> float:
    """Convert input value to float, returning 0.0 on invalid values."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_bool(value) -> bool:
    """Convert common bool-like inputs into a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _to_grist_id(value):
    """Convert numeric string IDs to ints for Grist Ref/id fields."""
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed.isdigit():
            return int(trimmed)
        return trimmed
    return value


REQUEST_VALIDATION_SCHEMAS: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/children/<child_id_val>/guardians"): {
        "type": "object",
        "properties": {
            "guardian_id": {"type": "ref"},
            "guardian": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "phone": {"type": "string"},
                    "email": {"type": "string"},
                    "relationship": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
            "link": {
                "type": "object",
                "properties": {
                    "legal_status": {"type": "string"},
                    "pickup_allowed": {"type": "boolean"},
                    "pickup_password": {"type": "string"},
                    "court_order_url": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
        },
    },
    ("PATCH", "/children/<child_id_val>/guardians/<guardian_id_val>"): {
        "type": "object",
        "minProperties": 1,
        "properties": {
            "legal_status": {"type": "string"},
            "pickup_allowed": {"type": "boolean"},
            "pickup_password": {"type": "string"},
            "court_order_url": {"type": "string"},
            "notes": {"type": "string"},
        },
        "additionalProperties": False,
    },
    ("POST", "/pickup/verify"): {
        "type": "object",
        "required": ["child_id", "guardian_id"],
        "properties": {
            "child_id": {"type": "ref"},
            "guardian_id": {"type": "ref"},
            "pickup_password": {"type": "string"},
        },
    },
    ("POST", "/pickup/events"): {
        "type": "object",
        "required": ["child_id", "approved"],
        "properties": {
            "child_id": {"type": "ref"},
            "approved": {"type": "boolean"},
            "requested_by_guardian": {"type": "ref"},
            "approved_by_staff": {"type": "ref"},
            "method": {"type": "string"},
            "denial_reason": {"type": "string"},
            "timestamp": {"type": "string", "format": "date-time"},
            "denial_code": {"type": "string"},
            "override_used": {"type": "boolean"},
            "override_reason": {"type": "string"},
            "override_approved_by": {"type": "ref"},
        },
    },
    ("POST", "/billing/invoices/generate"): {
        "type": "object",
        "required": ["invoices"],
        "properties": {
            "invoices": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["account", "period_start", "period_end", "due_date", "total_due"],
                    "properties": {
                        "account": {"type": "ref"},
                        "period_start": {"type": "string", "format": "date"},
                        "period_end": {"type": "string", "format": "date"},
                        "due_date": {"type": "string", "format": "date"},
                        "total_due": {"type": "number", "minimum": 0},
                        "subtotal": {"type": "number", "minimum": 0},
                        "subsidy_credit": {"type": "number"},
                        "late_fees": {"type": "number", "minimum": 0},
                        "status": {"type": "string", "enum": ["draft", "issued", "partial", "paid", "void"]},
                    },
                },
            },
        },
    },
    ("POST", "/billing/accounts/<account_id_val>/parties"): {
        "type": "object",
        "required": ["guardian"],
        "properties": {
            "guardian": {"type": "ref"},
            "payer_label": {"type": "string"},
            "share_pct": {"type": "number", "minimum": 0},
            "fixed_amount": {"type": "number", "minimum": 0},
            "priority": {"type": "number"},
            "auto_debit": {"type": "boolean"},
            "status": {"type": "string", "enum": ["active", "inactive", "paused"]},
            "notes": {"type": "string"},
        },
    },
    ("PATCH", "/billing/accounts/<account_id_val>/parties/<party_id_val>"): {
        "type": "object",
        "minProperties": 1,
        "properties": {
            "payer_label": {"type": "string"},
            "share_pct": {"type": "number", "minimum": 0},
            "fixed_amount": {"type": "number", "minimum": 0},
            "priority": {"type": "number"},
            "auto_debit": {"type": "boolean"},
            "status": {"type": "string", "enum": ["active", "inactive", "paused"]},
            "notes": {"type": "string"},
        },
        "additionalProperties": False,
    },
    ("POST", "/billing/invoices/<invoice_id_val>/autopay/run"): {
        "type": "object",
        "properties": {
            "simulate_fail_party_ids": {"type": "array", "items": {"type": "ref"}},
            "dry_run": {"type": "boolean"},
        },
    },
    ("POST", "/billing/payments"): {
        "type": "object",
        "required": ["invoice", "amount", "paid_at", "method"],
        "properties": {
            "invoice": {"type": "ref"},
            "amount": {"type": "number", "minimum": 0.01},
            "paid_at": {"type": "string", "format": "date-time"},
            "method": {"type": "string"},
            "txn_ref": {"type": "string"},
            "status": {"type": "string", "enum": ["posted", "pending", "failed", "void"]},
        },
    },
    ("POST", "/subsidy/claims"): {
        "type": "object",
        "required": ["claim_month", "child", "program", "expected_amount"],
        "properties": {
            "claim_month": {"type": "string"},
            "child": {"type": "ref"},
            "program": {"type": "string"},
            "expected_amount": {"type": "number", "minimum": 0},
            "received_amount": {"type": "number"},
            "status": {"type": "string", "enum": ["submitted", "paid", "variance"]},
            "submitted_at": {"type": "string", "format": "date-time"},
            "paid_at": {"type": "string", "format": "date-time"},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/subsidy/reconcile/<claim_id_val>"): {
        "type": "object",
        "properties": {
            "received_amount": {"type": "number"},
            "status": {"type": "string", "enum": ["submitted", "paid", "variance"]},
            "paid_at": {"type": "string", "format": "date-time"},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/compliance/medication-logs"): {
        "type": "object",
        "required": ["child", "medication_name", "dosage"],
        "properties": {
            "child": {"type": "ref"},
            "medication_name": {"type": "string"},
            "dosage": {"type": "string"},
            "administered": {"type": "boolean"},
            "administered_at": {"type": "string", "format": "date-time"},
            "administered_by": {"type": "ref"},
            "reason": {"type": "string"},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/compliance/sanitation-checks"): {
        "type": "object",
        "required": ["check_area", "check_item", "status", "checked_by"],
        "properties": {
            "check_area": {"type": "string"},
            "check_item": {"type": "string"},
            "status": {"type": "string", "enum": ["completed", "issue", "skipped"]},
            "checked_at": {"type": "string", "format": "date-time"},
            "checked_by": {"type": "ref"},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/compliance/sleep-safety-checks"): {
        "type": "object",
        "required": ["child", "status", "checked_by"],
        "properties": {
            "child": {"type": "ref"},
            "status": {"type": "string", "enum": ["safe", "attention", "incident"]},
            "check_time": {"type": "string", "format": "date-time"},
            "checked_by": {"type": "ref"},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/waitlist"): {
        "type": "object",
        "required": ["child_first_name", "child_last_name", "desired_start_date", "status"],
        "properties": {
            "child_first_name": {"type": "string"},
            "child_last_name": {"type": "string"},
            "desired_start_date": {"type": "string", "format": "date"},
            "status": {"type": "string", "enum": ["new", "contacted", "tour_scheduled", "offered", "enrolled", "lost"]},
            "priority_score": {"type": "number"},
            "follow_up_sla_hours": {"type": "number", "minimum": 0},
            "last_contact_at": {"type": "string", "format": "date-time"},
            "next_follow_up_at": {"type": "string", "format": "date-time"},
            "conversion_score": {"type": "number"},
            "retention_risk_score": {"type": "number"},
        },
    },
    ("PATCH", "/waitlist/<entry_id_val>"): {
        "type": "object",
        "minProperties": 1,
        "properties": {
            "status": {"type": "string", "enum": ["new", "contacted", "tour_scheduled", "offered", "enrolled", "lost"]},
            "priority_score": {"type": "number"},
            "follow_up_sla_hours": {"type": "number", "minimum": 0},
            "next_follow_up_at": {"type": "string", "format": "date-time"},
            "conversion_score": {"type": "number"},
            "retention_risk_score": {"type": "number"},
            "tour_date": {"type": "string", "format": "date-time"},
        },
    },
    ("POST", "/waitlist/<entry_id_val>/automation-action"): {
        "type": "object",
        "required": ["action_key"],
        "properties": {
            "action_key": {"type": "string"},
            "escalate": {"type": "boolean"},
            "escalation_reason": {"type": "string"},
            "nudge_sent": {"type": "boolean"},
            "follow_up_sla_hours": {"type": "number", "minimum": 0},
            "next_follow_up_at": {"type": "string", "format": "date-time"},
        },
    },
    ("POST", "/waitlist/<entry_id_val>/advance"): {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["new", "contacted", "tour_scheduled", "offered", "enrolled", "lost"]},
            "follow_up_sla_hours": {"type": "number", "minimum": 0},
            "retention_risk_score": {"type": "number"},
        },
    },
    ("POST", "/waitlist/<entry_id_val>/schedule-tour"): {
        "type": "object",
        "required": ["tour_date"],
        "properties": {
            "tour_date": {"type": "string", "format": "date-time"},
            "follow_up_sla_hours": {"type": "number", "minimum": 0},
            "next_follow_up_at": {"type": "string", "format": "date-time"},
        },
    },
    ("POST", "/waitlist/scoring/run"): {
        "type": "object",
        "properties": {
            "persist": {"type": "boolean"},
            "open_only": {"type": "boolean"},
        },
    },
    ("POST", "/regulatory/rules/ingest"): {
        "type": "object",
        "properties": {
            "ingest_batch_id": {"type": "string"},
            "deactivate_previous": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
            "rules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["rule_key", "version", "category", "jurisdiction", "title"],
                    "properties": {
                        "rule_key": {"type": "string"},
                        "version": {"type": "string"},
                        "category": {"type": "string"},
                        "jurisdiction": {"type": "string"},
                        "title": {"type": "string"},
                        "rule_text": {"type": "string"},
                        "summary": {"type": "string"},
                        "keywords": {"type": "string"},
                        "source_url": {"type": "string"},
                        "source_document": {"type": "string"},
                        "effective_date": {"type": "string"},
                        "active": {"type": "boolean"},
                    },
                },
            },
        },
    },
    ("POST", "/regulatory/audit/risk-assessments/run"): {
        "type": "object",
        "properties": {
            "jurisdiction": {"type": "string"},
            "category": {"type": "string"},
            "status": {"type": "string", "enum": ["open", "in_progress", "resolved", "closed"]},
        },
    },
    ("POST", "/ops/workflows/heartbeat"): {
        "type": "object",
        "required": ["workflow_key", "status"],
        "properties": {
            "workflow_key": {"type": "string"},
            "workflow_name": {"type": "string"},
            "status": {"type": "string", "enum": ["success", "error", "running", "unknown"]},
            "ran_at": {"type": "string", "format": "date-time"},
            "error": {"type": "string"},
        },
    },
    ("POST", "/marketing/leads"): {
        "type": "object",
        "required": ["family_name", "channel", "status"],
        "properties": {
            "family_name": {"type": "string"},
            "email": {"type": "string"},
            "phone": {"type": "string"},
            "child_age_group": {"type": "string"},
            "channel": {"type": "string"},
            "campaign": {"type": "string"},
            "status": {"type": "string", "enum": ["new", "contacted", "tour_scheduled", "converted", "lost"]},
            "inquiry_date": {"type": "string", "format": "date-time"},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/marketing/reviews"): {
        "type": "object",
        "required": ["family_name", "platform", "status"],
        "properties": {
            "family_name": {"type": "string"},
            "platform": {"type": "string", "enum": ["google", "yelp", "facebook", "other"]},
            "status": {"type": "string", "enum": ["pending", "requested", "received", "flagged"]},
            "rating": {"type": "number", "minimum": 1, "maximum": 5},
            "requested_at": {"type": "string", "format": "date-time"},
            "received_at": {"type": "string", "format": "date-time"},
            "review_url": {"type": "string"},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/marketing/insurance/policies"): {
        "type": "object",
        "required": ["policy_type", "carrier", "policy_number", "status"],
        "properties": {
            "policy_type": {"type": "string"},
            "carrier": {"type": "string"},
            "policy_number": {"type": "string"},
            "coverage_amount": {"type": "number", "minimum": 0},
            "effective_date": {"type": "string", "format": "date"},
            "expiration_date": {"type": "string", "format": "date"},
            "status": {"type": "string", "enum": ["active", "pending", "expired", "cancelled"]},
            "renewal_contact": {"type": "string"},
            "notes": {"type": "string"},
        },
    },
    ("PATCH", "/marketing/insurance/policies/<policy_id_val>"): {
        "type": "object",
        "minProperties": 1,
        "properties": {
            "policy_type": {"type": "string"},
            "carrier": {"type": "string"},
            "policy_number": {"type": "string"},
            "coverage_amount": {"type": "number", "minimum": 0},
            "effective_date": {"type": "string", "format": "date"},
            "expiration_date": {"type": "string", "format": "date"},
            "status": {"type": "string", "enum": ["active", "pending", "expired", "cancelled"]},
            "renewal_contact": {"type": "string"},
            "notes": {"type": "string"},
        },
        "additionalProperties": False,
    },
    ("POST", "/marketing/competitors/snapshots"): {
        "type": "object",
        "required": ["competitor_name"],
        "properties": {
            "competitor_name": {"type": "string"},
            "location": {"type": "string"},
            "tuition_band": {"type": "string"},
            "capacity_estimate": {"type": "number", "minimum": 0},
            "waitlist_estimate": {"type": "number", "minimum": 0},
            "source_url": {"type": "string"},
            "captured_at": {"type": "string", "format": "date-time"},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/marketing/spend"): {
        "type": "object",
        "required": ["channel", "period_month", "spend_amount"],
        "properties": {
            "channel": {"type": "string"},
            "campaign": {"type": "string"},
            "period_month": {"type": "string"},
            "spend_amount": {"type": "number", "minimum": 0},
            "currency": {"type": "string"},
            "clicks": {"type": "integer", "minimum": 0},
            "impressions": {"type": "integer", "minimum": 0},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/marketing/attribution/touchpoints"): {
        "type": "object",
        "required": ["lead_id", "channel", "occurred_at"],
        "properties": {
            "lead_id": {"type": "integer"},
            "channel": {"type": "string"},
            "campaign": {"type": "string"},
            "touch_type": {"type": "string"},
            "occurred_at": {"type": "string", "format": "date-time"},
            "utm_source": {"type": "string"},
            "utm_medium": {"type": "string"},
            "utm_campaign": {"type": "string"},
            "notes": {"type": "string"},
        },
    },
    ("POST", "/marketing/attribution/weights"): {
        "type": "object",
        "required": ["first_touch", "middle_touch_total", "last_touch"],
        "properties": {
            "first_touch": {"type": "number", "minimum": 0, "maximum": 1},
            "middle_touch_total": {"type": "number", "minimum": 0, "maximum": 1},
            "last_touch": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
}

QUERY_PARAM_SCHEMAS: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("GET", "/waitlist"): [
        {"name": "status", "schema": {"type": "string"}},
        {"name": "followup_due", "schema": {"type": "boolean"}},
        {"name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200}},
        {"name": "offset", "schema": {"type": "integer", "minimum": 0}},
        {"name": "sort_by", "schema": {"type": "string"}},
        {"name": "sort_dir", "schema": {"type": "string", "enum": ["asc", "desc"]}},
    ],
    ("GET", "/pickup/events"): [
        {"name": "child_id", "schema": {"type": "string"}},
        {"name": "approved", "schema": {"type": "boolean"}},
        {"name": "from", "schema": {"type": "string", "format": "date-time"}},
        {"name": "to", "schema": {"type": "string", "format": "date-time"}},
        {"name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200}},
        {"name": "offset", "schema": {"type": "integer", "minimum": 0}},
        {"name": "sort_by", "schema": {"type": "string"}},
        {"name": "sort_dir", "schema": {"type": "string", "enum": ["asc", "desc"]}},
    ],
    ("GET", "/billing/invoices/<invoice_id_val>/autopay/attempts"): [
        {"name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200}},
        {"name": "offset", "schema": {"type": "integer", "minimum": 0}},
        {"name": "sort_by", "schema": {"type": "string"}},
        {"name": "sort_dir", "schema": {"type": "string", "enum": ["asc", "desc"]}},
    ],
    ("GET", "/subsidy/claims"): [
        {"name": "claim_month", "schema": {"type": "string"}},
        {"name": "status", "schema": {"type": "string"}},
        {"name": "program", "schema": {"type": "string"}},
        {"name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200}},
        {"name": "offset", "schema": {"type": "integer", "minimum": 0}},
        {"name": "sort_by", "schema": {"type": "string"}},
        {"name": "sort_dir", "schema": {"type": "string", "enum": ["asc", "desc"]}},
    ],
    ("GET", "/marketing/leads"): [
        {"name": "channel", "schema": {"type": "string"}},
        {"name": "status", "schema": {"type": "string"}},
        {"name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200}},
        {"name": "offset", "schema": {"type": "integer", "minimum": 0}},
        {"name": "sort_by", "schema": {"type": "string"}},
        {"name": "sort_dir", "schema": {"type": "string", "enum": ["asc", "desc"]}},
    ],
    ("GET", "/marketing/reviews"): [
        {"name": "platform", "schema": {"type": "string"}},
        {"name": "status", "schema": {"type": "string"}},
        {"name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200}},
        {"name": "offset", "schema": {"type": "integer", "minimum": 0}},
        {"name": "sort_by", "schema": {"type": "string"}},
        {"name": "sort_dir", "schema": {"type": "string", "enum": ["asc", "desc"]}},
    ],
    ("GET", "/marketing/insurance/policies"): [
        {"name": "status", "schema": {"type": "string"}},
        {"name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200}},
        {"name": "offset", "schema": {"type": "integer", "minimum": 0}},
        {"name": "sort_by", "schema": {"type": "string"}},
        {"name": "sort_dir", "schema": {"type": "string", "enum": ["asc", "desc"]}},
    ],
    ("GET", "/marketing/competitors/snapshots"): [
        {"name": "competitor_name", "schema": {"type": "string"}},
        {"name": "limit", "schema": {"type": "integer", "minimum": 1, "maximum": 200}},
        {"name": "offset", "schema": {"type": "integer", "minimum": 0}},
        {"name": "sort_by", "schema": {"type": "string"}},
        {"name": "sort_dir", "schema": {"type": "string", "enum": ["asc", "desc"]}},
    ],
    ("GET", "/marketing/attribution/spend-summary"): [
        {"name": "period_month", "schema": {"type": "string"}},
        {"name": "channel", "schema": {"type": "string"}},
        {"name": "campaign", "schema": {"type": "string"}},
    ],
    ("GET", "/marketing/attribution/spend-trend"): [
        {"name": "channel", "schema": {"type": "string"}},
        {"name": "campaign", "schema": {"type": "string"}},
    ],
    ("GET", "/marketing/attribution/multi-touch"): [
        {"name": "period_month", "schema": {"type": "string"}},
        {"name": "model", "schema": {"type": "string", "enum": ["first_touch", "last_touch", "position_based"]}},
    ],
    ("GET", "/marketing/attribution/weights"): [],
    ("GET", "/staffing/risk-summary"): [
        {"name": "callout_rate", "schema": {"type": "number", "minimum": 0, "maximum": 1}},
    ],
}

IDEMPOTENT_ENDPOINTS: set[tuple[str, str]] = {
    ("POST", "/pickup/events"),
    ("POST", "/billing/invoices/generate"),
    ("POST", "/billing/invoices/<invoice_id_val>/autopay/run"),
    ("POST", "/subsidy/claims"),
    ("POST", "/subsidy/reconcile/<claim_id_val>"),
    ("POST", "/waitlist"),
}

_IDEMPOTENCY_LOCK = threading.Lock()
_IDEMPOTENCY_STORE: dict[str, dict[str, Any]] = {}
_OPENAPI_CACHE: dict[str, Any] | None = None


def _validation_error_response(details: list[dict[str, str]], status_code: int = 400):
    """Return a standard validation error envelope with field-level details."""
    return jsonify({
        "error": {
            "code": "validation_error",
            "message": "payload validation failed",
            "details": details,
        }
    }), status_code


def _idempotency_fingerprint() -> str:
    """Build payload fingerprint for idempotency comparison."""
    parsed = request.get_json(silent=True)
    if parsed is not None:
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    else:
        canonical = request.get_data(as_text=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotency_key_scope() -> str:
    """Build deterministic idempotency scope for this request."""
    header_key = request.headers.get("Idempotency-Key", "").strip()
    return f"{request.method}:{request.path}:{header_key}"


def _cleanup_idempotency_store_locked(now_ts: float) -> None:
    """Drop expired idempotency cache entries (lock must be held)."""
    expired = [key for key, value in _IDEMPOTENCY_STORE.items() if value.get("expires_at", 0) <= now_ts]
    for key in expired:
        _IDEMPOTENCY_STORE.pop(key, None)


def idempotent_endpoint(func):
    """Decorator: replay cached response for repeated Idempotency-Key requests."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not IDEMPOTENCY_ENABLED:
            return func(*args, **kwargs)
        header_key = request.headers.get("Idempotency-Key", "").strip()
        if not header_key:
            return func(*args, **kwargs)
        if len(header_key) > 128:
            return _validation_error_response([{"field": "header.Idempotency-Key", "message": "must be <= 128 chars"}])

        scope_key = _idempotency_key_scope()
        fingerprint = _idempotency_fingerprint()
        now_ts = time.time()

        with _IDEMPOTENCY_LOCK:
            _cleanup_idempotency_store_locked(now_ts)
            existing = _IDEMPOTENCY_STORE.get(scope_key)
            if existing:
                if existing.get("fingerprint") != fingerprint:
                    return jsonify({
                        "error": {
                            "code": "idempotency_key_reused",
                            "message": "Idempotency-Key has already been used with a different payload",
                        }
                    }), 409
                if existing.get("state") == "done":
                    if existing.get("is_json"):
                        replay = jsonify(existing.get("body"))
                    else:
                        replay = make_response(existing.get("body", ""))
                        replay.headers["Content-Type"] = existing.get("content_type", "application/json")
                    replay.status_code = int(existing.get("status_code", 200))
                    replay.headers["X-Idempotent-Replay"] = "true"
                    return replay
                return jsonify({
                    "error": {
                        "code": "idempotency_in_progress",
                        "message": "Idempotent request with this key is already in progress",
                    }
                }), 409

            _IDEMPOTENCY_STORE[scope_key] = {
                "state": "in_progress",
                "fingerprint": fingerprint,
                "expires_at": now_ts + IDEMPOTENCY_TTL_SECONDS,
            }

        try:
            response = make_response(func(*args, **kwargs))
        except Exception:
            with _IDEMPOTENCY_LOCK:
                _IDEMPOTENCY_STORE.pop(scope_key, None)
            raise

        if response.status_code < 500:
            payload = response.get_json(silent=True)
            is_json = payload is not None
            body = payload if is_json else response.get_data(as_text=True)
            with _IDEMPOTENCY_LOCK:
                _IDEMPOTENCY_STORE[scope_key] = {
                    "state": "done",
                    "fingerprint": fingerprint,
                    "status_code": response.status_code,
                    "is_json": is_json,
                    "body": body,
                    "content_type": response.headers.get("Content-Type", "application/json"),
                    "expires_at": now_ts + IDEMPOTENCY_TTL_SECONDS,
                }
            response.headers["X-Idempotent-Replay"] = "false"
        else:
            with _IDEMPOTENCY_LOCK:
                _IDEMPOTENCY_STORE.pop(scope_key, None)
        return response

    return wrapper


def _matches_schema_type(value, schema_type: str) -> bool:
    """Return True when value matches expected schema type."""
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "ref":
        if isinstance(value, int) and not isinstance(value, bool):
            return True
        return isinstance(value, str) and value.strip().isdigit()
    return True


def _validate_json_against_schema(data, schema: dict[str, Any], path: str = "body") -> list[dict[str, str]]:
    """Validate JSON-like payload against a lightweight schema definition."""
    errors: list[dict[str, str]] = []
    expected_type = schema.get("type")
    if expected_type and not _matches_schema_type(data, expected_type):
        errors.append({"field": path, "message": f"must be {expected_type}"})
        return errors

    if expected_type == "object":
        required = schema.get("required", [])
        for field in required:
            if field not in data or data.get(field) in (None, ""):
                errors.append({"field": f"{path}.{field}", "message": "is required"})

        min_props = schema.get("minProperties")
        if isinstance(min_props, int) and len(data) < min_props:
            errors.append({"field": path, "message": f"must include at least {min_props} properties"})

        properties = schema.get("properties", {})
        for key, value in data.items():
            child_path = f"{path}.{key}"
            child_schema = properties.get(key)
            if child_schema:
                errors.extend(_validate_json_against_schema(value, child_schema, child_path))
            elif schema.get("additionalProperties") is False:
                errors.append({"field": child_path, "message": "is not allowed"})

    if expected_type == "array":
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(data) < min_items:
            errors.append({"field": path, "message": f"must include at least {min_items} item(s)"})
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(data):
                errors.extend(_validate_json_against_schema(item, item_schema, f"{path}[{idx}]"))

    enum_values = schema.get("enum")
    if enum_values and data not in enum_values:
        errors.append({"field": path, "message": f"must be one of {enum_values}"})

    if expected_type in {"string", "ref"}:
        min_len = schema.get("minLength")
        if isinstance(min_len, int) and isinstance(data, str) and len(data.strip()) < min_len:
            errors.append({"field": path, "message": f"must be at least {min_len} characters"})
        fmt = schema.get("format")
        if fmt == "date-time" and isinstance(data, str) and data.strip() and not _parse_iso_datetime(data):
            errors.append({"field": path, "message": "must be ISO datetime"})
        if fmt == "date" and isinstance(data, str) and data.strip() and not _parse_iso_date(data):
            errors.append({"field": path, "message": "must be ISO date (YYYY-MM-DD)"})

    if expected_type in {"number", "integer"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and isinstance(data, (int, float)) and data < minimum:
            errors.append({"field": path, "message": f"must be >= {minimum}"})
        if maximum is not None and isinstance(data, (int, float)) and data > maximum:
            errors.append({"field": path, "message": f"must be <= {maximum}"})

    return errors


def _extra_validation_errors(route_rule: str, payload: dict) -> list[dict[str, str]]:
    """Route-specific validation checks not covered by base schema rules."""
    errors: list[dict[str, str]] = []
    if route_rule == "/children/<child_id_val>/guardians":
        guardian_id_val = payload.get("guardian_id")
        guardian_obj = payload.get("guardian")
        if guardian_id_val in (None, "") and not isinstance(guardian_obj, dict):
            errors.append({"field": "body.guardian", "message": "guardian object is required when guardian_id is not provided"})
        if guardian_id_val in (None, "") and isinstance(guardian_obj, dict):
            for field in ("first_name", "last_name", "phone"):
                if guardian_obj.get(field) in (None, ""):
                    errors.append({"field": f"body.guardian.{field}", "message": "is required"})
    if route_rule == "/pickup/events":
        approved = payload.get("approved")
        if isinstance(approved, bool) and not approved:
            if str(payload.get("denial_code", "")).strip().lower() not in PICKUP_DENIAL_CODES:
                errors.append({"field": "body.denial_code", "message": f"must be one of {sorted(PICKUP_DENIAL_CODES)} when approved=false"})
        if payload.get("override_used") is True:
            if not str(payload.get("override_reason", "")).strip():
                errors.append({"field": "body.override_reason", "message": "is required when override_used=true"})
            if payload.get("override_approved_by") in (None, ""):
                errors.append({"field": "body.override_approved_by", "message": "is required when override_used=true"})
    if route_rule == "/billing/accounts/<account_id_val>/parties":
        share_pct = _to_float(payload.get("share_pct"))
        fixed_amount = _to_float(payload.get("fixed_amount"))
        if share_pct <= 0 and fixed_amount <= 0:
            errors.append({"field": "body", "message": "either share_pct or fixed_amount must be > 0"})
    if route_rule == "/compliance/medication-logs":
        if payload.get("administered") is True and payload.get("administered_by") in (None, ""):
            errors.append({"field": "body.administered_by", "message": "is required when administered=true"})
    if route_rule == "/regulatory/rules/ingest":
        rules = payload.get("rules")
        if rules is None and not payload:
            errors.append({"field": "body.rules", "message": "rules array is required"})
        elif rules is not None and (not isinstance(rules, list) or not rules):
            errors.append({"field": "body.rules", "message": "must be a non-empty array"})
    return errors


def _parse_list_controls(
    *,
    allowed_sort_fields: set[str],
    default_sort_by: str = "id",
    default_sort_dir: str = "asc",
    default_limit: int = 50,
    max_limit: int = 200,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Parse and validate shared list controls: limit/offset/sort_by/sort_dir."""
    errors: list[dict[str, str]] = []

    limit_raw = request.args.get("limit", str(default_limit))
    offset_raw = request.args.get("offset", "0")
    sort_by = str(request.args.get("sort_by", default_sort_by)).strip() or default_sort_by
    sort_dir = str(request.args.get("sort_dir", default_sort_dir)).strip().lower() or default_sort_dir

    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        limit = -1
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        offset = -1

    if limit < 1 or limit > max_limit:
        errors.append({"field": "query.limit", "message": f"must be between 1 and {max_limit}"})
    if offset < 0:
        errors.append({"field": "query.offset", "message": "must be >= 0"})
    if sort_dir not in {"asc", "desc"}:
        errors.append({"field": "query.sort_dir", "message": "must be one of ['asc', 'desc']"})
    if sort_by not in allowed_sort_fields:
        errors.append({"field": "query.sort_by", "message": f"must be one of {sorted(allowed_sort_fields)}"})

    if errors:
        return None, errors
    return {
        "limit": limit,
        "offset": offset,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }, []


def _sort_records(records: list[dict], *, sort_by: str, sort_dir: str) -> list[dict]:
    """Sort records deterministically by id or one field under record.fields."""
    reverse = sort_dir == "desc"

    def _value(record):
        if sort_by == "id":
            return _to_float(record.get("id"))
        raw = record.get("fields", {}).get(sort_by)
        if raw in (None, ""):
            return (2, 0)
        parsed_dt = _parse_iso_datetime(str(raw))
        if parsed_dt:
            return (0, parsed_dt.timestamp())
        try:
            return (0, float(raw))
        except (TypeError, ValueError):
            return (1, str(raw).lower())

    return sorted(records, key=lambda r: (_value(r), _to_float(r.get("id"))), reverse=reverse)


def _paginate_records(records: list[dict], *, limit: int, offset: int) -> list[dict]:
    """Return a deterministic paginated slice."""
    return records[offset: offset + limit]


def _schema_to_openapi(schema: dict[str, Any]) -> dict[str, Any]:
    """Translate lightweight validation schema into OpenAPI JSON schema."""
    converted: dict[str, Any] = {}
    schema_type = schema.get("type")
    if schema_type == "ref":
        converted["oneOf"] = [{"type": "integer"}, {"type": "string"}]
    elif schema_type:
        converted["type"] = schema_type

    for key in ("required", "enum", "minItems", "minLength", "minimum", "maximum", "minProperties"):
        if key in schema:
            converted[key] = schema[key]

    if "properties" in schema:
        converted["properties"] = {
            prop: _schema_to_openapi(prop_schema)
            for prop, prop_schema in schema["properties"].items()
        }
    if "items" in schema:
        converted["items"] = _schema_to_openapi(schema["items"])
    if "additionalProperties" in schema:
        converted["additionalProperties"] = schema["additionalProperties"]
    if schema.get("format"):
        converted["format"] = schema["format"]
    return converted


def _rule_to_openapi_path(rule: str) -> str:
    """Convert Flask route placeholders to OpenAPI path placeholders."""
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", rule)


def _build_openapi_spec() -> dict[str, Any]:
    """Build OpenAPI spec from registered Flask routes and validation schemas."""
    paths: dict[str, Any] = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint == "static":
            continue
        path = _rule_to_openapi_path(rule.rule)
        path_item = paths.setdefault(path, {})
        view_func = app.view_functions.get(rule.endpoint)
        summary = ""
        if view_func and view_func.__doc__:
            summary = view_func.__doc__.strip().splitlines()[0]
        for method in sorted(m for m in rule.methods if m in {"GET", "POST", "PATCH", "PUT", "DELETE"}):
            operation: dict[str, Any] = {
                "operationId": f"{rule.endpoint}_{method.lower()}",
                "summary": summary or f"{method} {path}",
                "responses": {
                    "200": {"description": "Success"},
                    "400": {"description": "Validation Error"},
                    "401": {"description": "Unauthorized"},
                },
            }
            if method == "POST":
                operation["responses"]["201"] = {"description": "Created"}
            if rule.endpoint not in PUBLIC_ROUTES:
                operation["security"] = [{"ApiKeyAuth": []}]
            if rule.arguments:
                operation["parameters"] = [
                    {
                        "name": arg,
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                    for arg in sorted(rule.arguments)
                ]
            query_params = QUERY_PARAM_SCHEMAS.get((method, rule.rule), [])
            if query_params:
                params = operation.setdefault("parameters", [])
                for qp in query_params:
                    params.append({
                        "name": qp["name"],
                        "in": "query",
                        "required": bool(qp.get("required", False)),
                        "schema": qp.get("schema", {"type": "string"}),
                    })
            if (method, rule.rule) in IDEMPOTENT_ENDPOINTS:
                params = operation.setdefault("parameters", [])
                params.append({
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": False,
                    "schema": {"type": "string", "maxLength": 128},
                    "description": f"Optional replay key (TTL: {IDEMPOTENCY_TTL_SECONDS}s). Same key+payload returns cached response.",
                })
            req_schema = REQUEST_VALIDATION_SCHEMAS.get((method, rule.rule))
            if req_schema:
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": _schema_to_openapi(req_schema)
                        }
                    },
                }
            path_item[method.lower()] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Daycare Ops API",
            "version": "1.1.0-p1",
            "description": "Operational API for daycare staffing, compliance, billing, waitlist, and workflow health.",
        },
        "servers": [{"url": "/"}],
        "security": [{"ApiKeyAuth": []}],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                }
            }
        },
        "paths": paths,
    }

PICKUP_DENIAL_CODES = {
    "guardian_not_linked",
    "legal_restriction",
    "pickup_not_allowed",
    "pickup_password_mismatch",
    "identity_mismatch",
    "court_order_restriction",
    "other",
}

SANITATION_STATUSES = {"completed", "issue", "skipped"}
SLEEP_SAFETY_STATUSES = {"safe", "attention", "incident"}
WAITLIST_FLOW = ["new", "contacted", "tour_scheduled", "offered", "enrolled"]
WAITLIST_SLA_HOURS = {
    "new": 48,
    "contacted": 48,
    "tour_scheduled": 24,
    "offered": 48,
    "enrolled": 168,
}
RISK_LEVEL_THRESHOLDS = (
    (70, "high"),
    (40, "medium"),
)
WORKFLOW_FRESHNESS_HOURS = {
    "daily_summary_parent_reports": 26,
    "staffing_coverage_check": 26,
    "subsidy_deadline_alert": 26,
    "subsidy_reconciliation_alert": 26,
    "autopay_due_invoices": 26,
    "waitlist_followup_sla_alert": 26,
    "waitlist_stage_playbook_daily": 26,
    "enrollment_forecast_monthly": 35 * 24,
    "regulatory_rules_ingestion_weekly": 8 * 24,
}
MARKETING_LEAD_STATUSES = {"new", "contacted", "tour_scheduled", "converted", "lost"}
REVIEW_PLATFORMS = {"google", "yelp", "facebook", "other"}
REVIEW_STATUSES = {"pending", "requested", "received", "flagged"}
INSURANCE_POLICY_STATUSES = {"active", "pending", "expired", "cancelled"}

def _safe_weight(env_name: str, default: float) -> float:
    """Parse a float weight from env, falling back to default on invalid values."""
    try:
        return float(str(os.getenv(env_name, default)).strip())
    except (TypeError, ValueError):
        return default


ATTRIBUTION_WEIGHTS: dict[str, float] = {
    "first_touch": _safe_weight("ATTRIBUTION_WEIGHT_FIRST", 0.4),
    "middle_touch_total": _safe_weight("ATTRIBUTION_WEIGHT_MIDDLE_TOTAL", 0.2),
    "last_touch": _safe_weight("ATTRIBUTION_WEIGHT_LAST", 0.4),
}


def _parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse common ISO datetime strings; return None on invalid values."""
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_iso_date(value: str | None) -> str | None:
    """Parse strict ISO date strings (YYYY-MM-DD); return canonical form or None."""
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.date().isoformat()


def _filter_records_by_day(records: list[dict], field_name: str, day: str | None) -> list[dict]:
    """Filter records by YYYY-MM-DD prefix of a datetime-like field."""
    if not day:
        return records
    day = str(day).strip()
    if not day:
        return records
    result = []
    for record in records:
        raw = str(record.get("fields", {}).get(field_name, "")).strip()
        if raw.startswith(day):
            result.append(record)
    return result


def _waitlist_followup_due_entries(entries: list[dict]) -> list[dict]:
    """Return waitlist entries whose next_follow_up_at is due (UTC now or earlier)."""
    now = datetime.utcnow()
    due = []
    for entry in entries:
        fields = entry.get("fields", {})
        next_follow_up = _parse_iso_datetime(fields.get("next_follow_up_at"))
        if next_follow_up and next_follow_up <= now:
            due.append(entry)
    return due


def _clamp_score(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """Clamp numeric score into the inclusive score range."""
    return max(minimum, min(maximum, value))


def _waitlist_score_entry(fields: dict, now: datetime) -> tuple[float, float, list[str], list[str]]:
    """Return conversion/risk scores and reason lists for one waitlist entry."""
    stage = str(fields.get("status", "new")).strip().lower()
    priority = _to_float(fields.get("priority_score", 0))
    last_contact = _parse_iso_datetime(fields.get("last_contact_at"))
    next_follow_up = _parse_iso_datetime(fields.get("next_follow_up_at"))
    tour_date = _parse_iso_datetime(fields.get("tour_date"))
    desired_start = _parse_iso_datetime(fields.get("desired_start_date"))

    hours_since_contact = ((now - last_contact).total_seconds() / 3600.0) if last_contact else None
    hours_since_tour = ((now - tour_date).total_seconds() / 3600.0) if tour_date else None
    days_to_start = ((desired_start - now).total_seconds() / 86400.0) if desired_start else None
    followup_overdue = bool(next_follow_up and next_follow_up <= now)
    offered_no_response = bool(stage == "offered" and hours_since_contact is not None and hours_since_contact > 72)
    missed_tour = bool(stage == "tour_scheduled" and hours_since_tour is not None and hours_since_tour > 2)

    conversion = _clamp_score(priority * 10.0)
    risk = 20.0
    conversion_reasons: list[str] = []
    risk_reasons: list[str] = []

    stage_conversion_bonus = {
        "new": 0.0,
        "contacted": 10.0,
        "tour_scheduled": 20.0,
        "offered": 30.0,
        "enrolled": 40.0,
        "lost": -20.0,
    }
    stage_risk_delta = {
        "new": 0.0,
        "contacted": 5.0,
        "tour_scheduled": 10.0,
        "offered": 15.0,
        "enrolled": -10.0,
        "lost": 35.0,
    }

    conversion += stage_conversion_bonus.get(stage, 0.0)
    risk += stage_risk_delta.get(stage, 0.0)
    if stage in stage_conversion_bonus:
        conversion_reasons.append(f"stage_{stage}")
    if stage in stage_risk_delta:
        risk_reasons.append(f"stage_{stage}")

    if tour_date:
        conversion += 8.0
        conversion_reasons.append("tour_recorded")

    if days_to_start is not None:
        if days_to_start <= 30:
            conversion += 15.0
            risk -= 5.0
            conversion_reasons.append("start_within_30d")
            risk_reasons.append("start_within_30d")
        elif days_to_start <= 60:
            conversion += 8.0
            conversion_reasons.append("start_within_60d")
        elif days_to_start >= 120:
            conversion -= 8.0
            risk += 5.0
            conversion_reasons.append("start_120d_plus")
            risk_reasons.append("start_120d_plus")

    if hours_since_contact is not None:
        if hours_since_contact > 72:
            conversion -= 15.0
            risk += 15.0
            conversion_reasons.append("contact_gap_72h")
            risk_reasons.append("contact_gap_72h")
        if hours_since_contact > 168:
            conversion -= 10.0
            risk += 15.0
            conversion_reasons.append("contact_gap_168h")
            risk_reasons.append("contact_gap_168h")

    if followup_overdue:
        conversion -= 15.0
        risk += 25.0
        conversion_reasons.append("followup_overdue")
        risk_reasons.append("followup_overdue")

    if offered_no_response:
        conversion -= 20.0
        risk += 25.0
        conversion_reasons.append("offered_no_response_72h")
        risk_reasons.append("offered_no_response_72h")

    if missed_tour:
        conversion -= 20.0
        risk += 30.0
        conversion_reasons.append("tour_missed")
        risk_reasons.append("tour_missed")

    if priority >= 8:
        conversion += 5.0
        risk -= 5.0
        conversion_reasons.append("priority_high")
        risk_reasons.append("priority_high")
    elif priority <= 2:
        conversion -= 5.0
        risk += 5.0
        conversion_reasons.append("priority_low")
        risk_reasons.append("priority_low")

    conversion = _clamp_score(conversion)
    if conversion >= 70:
        risk -= 10.0
        risk_reasons.append("conversion_strong")
    risk = _clamp_score(risk)

    return (
        round(conversion, 2),
        round(risk, 2),
        sorted(set(conversion_reasons)),
        sorted(set(risk_reasons)),
    )


def _risk_level_from_score(score: float) -> str:
    """Return risk level label for a numeric score."""
    for threshold, label in RISK_LEVEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "low"


def _normalize_regulatory_rule_payload(raw: dict, ingest_batch_id: str) -> tuple[dict | None, str | None]:
    """Normalize one rule payload item; returns (fields, error)."""
    rule_key = str(raw.get("rule_key", "")).strip().lower()
    version = str(raw.get("version", "")).strip()
    category = str(raw.get("category", "")).strip()
    jurisdiction = str(raw.get("jurisdiction", "")).strip()
    title = str(raw.get("title", "")).strip()
    rule_text = str(raw.get("rule_text", "")).strip()
    summary = str(raw.get("summary", "")).strip()
    if not all([rule_key, version, category, jurisdiction, title]):
        return None, "missing required fields: rule_key, version, category, jurisdiction, title"
    if not rule_text and not summary:
        return None, "rule_text or summary is required"
    fields = {
        "rule_key": rule_key,
        "version": version,
        "category": category,
        "jurisdiction": jurisdiction,
        "title": title,
        "rule_text": rule_text,
        "summary": summary,
        "keywords": str(raw.get("keywords", "")),
        "source_url": str(raw.get("source_url", "")),
        "source_document": str(raw.get("source_document", "")),
        "effective_date": str(raw.get("effective_date", "")),
        "active": _to_bool(raw.get("active", True)),
        "ingested_at": datetime.utcnow().isoformat(timespec="seconds"),
        "supersedes_version": str(raw.get("supersedes_version", "")),
        "ingest_batch_id": ingest_batch_id,
    }
    return fields, None


def _compute_regulatory_risk_snapshot(jurisdiction: str | None = None) -> dict:
    """Compute a risk summary from regulatory and compliance operational signals."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    active_rules = get_regulatory_rules(jurisdiction=jurisdiction, active_only=True)
    med_logs_today = get_medication_logs()
    med_logs_today = _filter_records_by_day(med_logs_today, "administered_at", today)
    sanitation_today = get_sanitation_checks()
    sanitation_today = _filter_records_by_day(sanitation_today, "checked_at", today)
    sleep_today = get_sleep_safety_checks()
    sleep_today = _filter_records_by_day(sleep_today, "check_time", today)
    urgent_subsidies = get_urgent_subsidies()
    open_assessments = get_regulatory_risk_assessments(status="open")

    findings: list[str] = []
    actions: list[str] = []
    score = 0.0

    if not active_rules:
        score += 35
        findings.append("No active regulatory rules ingested.")
        actions.append("Ingest current state licensing rules and set active versions.")

    stale_rules = 0
    for row in active_rules:
        effective_date = str(row.get("fields", {}).get("effective_date", "")).strip()
        if not effective_date:
            stale_rules += 1
            continue
        try:
            age_days = (datetime.utcnow().date() - datetime.strptime(effective_date, "%Y-%m-%d").date()).days
        except ValueError:
            stale_rules += 1
            continue
        if age_days > 365:
            stale_rules += 1
    if stale_rules > 0:
        score += min(20, stale_rules * 4)
        findings.append(f"{stale_rules} active rule(s) have stale/missing effective date metadata.")
        actions.append("Review and refresh stale rules to the latest published versions.")

    if not med_logs_today:
        score += 12
        findings.append("No medication logs recorded today.")
        actions.append("Verify medication administration logging is complete.")
    if not sanitation_today:
        score += 12
        findings.append("No sanitation checks recorded today.")
        actions.append("Run sanitation checklist and log outcomes.")
    if not sleep_today:
        score += 12
        findings.append("No sleep-safety checks recorded today.")
        actions.append("Run and record sleep-safety checks for infant/toddler rooms.")

    if urgent_subsidies:
        score += min(12, len(urgent_subsidies) * 4)
        findings.append(f"{len(urgent_subsidies)} subsidy case(s) flagged urgent.")
        actions.append("Complete subsidy reauthorization submissions before deadlines.")

    if open_assessments:
        score += min(15, len(open_assessments) * 3)
        findings.append(f"{len(open_assessments)} open prior regulatory risk assessment(s).")
        actions.append("Close or mitigate prior open compliance findings.")

    score = max(0.0, min(score, 100.0))
    return {
        "assessed_at": datetime.utcnow().isoformat(timespec="seconds"),
        "jurisdiction": jurisdiction or "default",
        "risk_score": round(score, 2),
        "risk_level": _risk_level_from_score(score),
        "findings": findings,
        "recommended_actions": actions,
        "signals": {
            "active_rules": len(active_rules),
            "stale_rules": stale_rules,
            "medication_logs_today": len(med_logs_today),
            "sanitation_checks_today": len(sanitation_today),
            "sleep_safety_checks_today": len(sleep_today),
            "urgent_subsidies": len(urgent_subsidies),
            "open_assessments": len(open_assessments),
        },
    }


def _workflow_heartbeat_payload(data: dict) -> tuple[dict | None, str | None]:
    """Validate and normalize workflow heartbeat input payload."""
    workflow_key = str(data.get("workflow_key", "")).strip().lower()
    workflow_name = str(data.get("workflow_name", "")).strip()
    if not workflow_key:
        return None, "workflow_key is required"
    status = str(data.get("status", "success")).strip().lower() or "success"
    ran_at_raw = data.get("ran_at")
    ran_at = _parse_iso_datetime(str(ran_at_raw)) if ran_at_raw else datetime.utcnow()
    if ran_at is None:
        return None, "ran_at must be ISO datetime"
    error_msg = str(data.get("error", "")).strip()
    fields = {
        "workflow_name": workflow_name,
        "last_status": status,
        "last_run_at": ran_at.isoformat(timespec="seconds"),
        "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    if status == "success":
        fields["last_success_at"] = fields["last_run_at"]
        fields["last_error"] = ""
    else:
        fields["last_error"] = error_msg
    return {"workflow_key": workflow_key, "fields": fields}, None


def _compute_workflow_freshness(now: datetime | None = None) -> dict:
    """Compute stale workflow summary from heartbeat rows and freshness thresholds."""
    now = now or datetime.utcnow()
    rows = get_workflow_heartbeats()
    by_key = {
        str(row.get("fields", {}).get("workflow_key", "")).strip().lower(): row
        for row in rows
    }

    items = []
    stale_count = 0
    for workflow_key, threshold_hours in WORKFLOW_FRESHNESS_HOURS.items():
        row = by_key.get(workflow_key)
        fields = row.get("fields", {}) if row else {}
        workflow_name = fields.get("workflow_name") or workflow_key
        last_status = str(fields.get("last_status", "unknown"))
        last_run_at = str(fields.get("last_run_at", "")).strip()
        last_success_at = str(fields.get("last_success_at", "")).strip()
        age_hours = None
        stale_reason = ""
        stale = False

        success_dt = _parse_iso_datetime(last_success_at)
        if not success_dt:
            stale = True
            stale_reason = "no_success_heartbeat"
        else:
            if success_dt.tzinfo is not None:
                success_dt = success_dt.astimezone(tz=None).replace(tzinfo=None)
            age_hours = round((now - success_dt).total_seconds() / 3600, 2)
            if age_hours > threshold_hours:
                stale = True
                stale_reason = f"stale_over_{threshold_hours}h"

        if stale:
            stale_count += 1

        items.append({
            "workflow_key": workflow_key,
            "workflow_name": workflow_name,
            "threshold_hours": threshold_hours,
            "last_status": last_status,
            "last_run_at": last_run_at,
            "last_success_at": last_success_at,
            "age_hours_since_success": age_hours,
            "stale": stale,
            "stale_reason": stale_reason,
            "last_error": str(fields.get("last_error", "")).strip(),
        })

    return {
        "checked_at": now.isoformat(timespec="seconds"),
        "workflow_count": len(items),
        "stale_count": stale_count,
        "all_fresh": stale_count == 0,
        "workflows": items,
    }


def _invoice_balance(invoice_rec: dict) -> dict:
    """Return total_paid and balance for an invoice record."""
    invoice_id_val = invoice_rec.get("id")
    fields = invoice_rec.get("fields", {})
    total_due = _to_float(fields.get("total_due"))
    payments = get_payments(invoice_id_val)
    total_paid = sum(_to_float(p["fields"].get("amount")) for p in payments)
    balance = total_due - total_paid
    return {"total_due": total_due, "total_paid": total_paid, "balance": balance}


def _days_overdue(due_date: str) -> int:
    """Return number of days overdue based on YYYY-MM-DD due date."""
    if not due_date:
        return 0
    try:
        due = datetime.strptime(due_date, "%Y-%m-%d").date()
    except ValueError:
        return 0
    today = datetime.utcnow().date()
    delta = (today - due).days
    return delta if delta > 0 else 0


def _compute_invoice_allocations(invoice_rec: dict, parties: list[dict]) -> list[dict]:
    """Compute per-party allocation for an invoice using fixed+percentage rules."""
    total_due = _to_float(invoice_rec.get("fields", {}).get("total_due"))
    if total_due <= 0:
        return []

    active = []
    for party in parties:
        fields = party.get("fields", {})
        status = str(fields.get("status", "active")).lower()
        if status in {"inactive", "disabled", "archived"}:
            continue
        active.append(party)
    if not active:
        return []

    for party in active:
        fields = party.get("fields", {})
        fields["_fixed_amount"] = max(0.0, _to_float(fields.get("fixed_amount")))
        fields["_share_pct"] = max(0.0, _to_float(fields.get("share_pct")))
        fields["_priority"] = _to_float(fields.get("priority"))

    active.sort(key=lambda p: p.get("fields", {}).get("_priority", 0))
    remaining = total_due
    allocations = []

    for party in active:
        fields = party.get("fields", {})
        fixed = fields.get("_fixed_amount", 0.0)
        if fixed <= 0:
            continue
        amount = min(remaining, fixed)
        if amount > 0:
            allocations.append({"party": party, "amount": amount})
            remaining -= amount
        if remaining <= 0:
            break

    if remaining > 0:
        pct_parties = [p for p in active if p.get("fields", {}).get("_share_pct", 0) > 0]
        if pct_parties:
            pct_total = sum(p["fields"].get("_share_pct", 0.0) for p in pct_parties)
            for party in pct_parties:
                share_pct = party["fields"].get("_share_pct", 0.0)
                amount = remaining * (share_pct / pct_total) if pct_total > 0 else 0
                if amount > 0:
                    allocations.append({"party": party, "amount": amount})
        else:
            even = remaining / len(active)
            for party in active:
                allocations.append({"party": party, "amount": even})

    rounded = []
    for item in allocations:
        rounded.append({**item, "amount": round(item["amount"], 2)})
    delta = round(total_due - sum(item["amount"] for item in rounded), 2)
    if rounded and abs(delta) > 0:
        rounded[0]["amount"] = round(rounded[0]["amount"] + delta, 2)

    result = []
    for item in rounded:
        party = item["party"]
        fields = party.get("fields", {})
        result.append({
            "party_id": party.get("id"),
            "account": fields.get("account"),
            "guardian": fields.get("guardian"),
            "payer_label": fields.get("payer_label", ""),
            "share_pct": fields.get("share_pct", 0),
            "fixed_amount": fields.get("fixed_amount", 0),
            "allocated_amount": item["amount"],
            "auto_debit": _to_bool(fields.get("auto_debit", False)),
            "status": fields.get("status", "active"),
        })
    return result


# --- P0: Guardians / Pickup / Billing / Waitlist endpoints ---


@app.route("/children/<child_id_val>/guardians", methods=["GET"])
def api_get_child_guardians(child_id_val):
    """Return all guardian links and guardian profiles for a child."""
    child = find_child_by_id(child_id_val)
    if not child:
        return jsonify({"error": f"Child '{child_id_val}' not found"}), 404
    guardians = get_child_guardians(child_id_val)
    return jsonify({
        "child_id": child_id_val,
        "child_name": f"{child['fields'].get('first_name', '')} {child['fields'].get('last_name', '')}".strip(),
        "guardians": guardians,
    })


@app.route("/children/<child_id_val>/guardians", methods=["POST"])
def api_add_child_guardian(child_id_val):
    """Create a guardian and link to child, or link an existing guardian."""
    child = find_child_by_id(child_id_val)
    if not child:
        return jsonify({"error": f"Child '{child_id_val}' not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    guardian_id_val = data.get("guardian_id")
    link = data.get("link", {}) if isinstance(data.get("link", {}), dict) else {}

    if guardian_id_val:
        guardian = get_guardian_by_id(guardian_id_val)
        if not guardian:
            return jsonify({"error": f"Guardian '{guardian_id_val}' not found"}), 404
    else:
        guardian_fields = data.get("guardian", {})
        if not isinstance(guardian_fields, dict):
            return jsonify({"error": "guardian must be an object"}), 400
        required = ["first_name", "last_name", "phone"]
        missing = [field for field in required if not guardian_fields.get(field)]
        if missing:
            return jsonify({"error": f"missing guardian fields: {', '.join(missing)}"}), 400
        guardian = create_guardian(guardian_fields)
        if not guardian:
            return jsonify({"error": "failed to create guardian"}), 500
        guardian_id_val = guardian.get("id")

    link_result = link_child_guardian(
        child_id_val=_to_grist_id(child_id_val),
        guardian_id_val=_to_grist_id(guardian_id_val),
        legal_status=link.get("legal_status", "custodial"),
        pickup_allowed=_to_bool(link.get("pickup_allowed", True)),
        pickup_password=link.get("pickup_password", ""),
        court_order_url=link.get("court_order_url", ""),
        notes=link.get("notes", ""),
    )
    if not link_result:
        return jsonify({"error": "failed to link guardian to child"}), 500

    return jsonify({
        "status": "linked",
        "child_id": child_id_val,
        "guardian_id": guardian_id_val,
        "link_id": link_result.get("id"),
    }), 201


@app.route("/children/<child_id_val>/guardians/<guardian_id_val>", methods=["PATCH"])
def api_patch_child_guardian(child_id_val, guardian_id_val):
    """Patch custody/pickup fields for a child-guardian link."""
    links = get_child_guardian_links(child_id_val)
    target = next((link for link in links if str(link["fields"].get("guardian")) == str(guardian_id_val)), None)
    if not target:
        return jsonify({"error": "child-guardian link not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "fields object required"}), 400

    allowed = {"legal_status", "pickup_allowed", "pickup_password", "court_order_url", "notes"}
    patch_fields = {key: value for key, value in data.items() if key in allowed}
    if not patch_fields:
        return jsonify({"error": "no allowed fields provided"}), 400
    if "pickup_allowed" in patch_fields:
        patch_fields["pickup_allowed"] = _to_bool(patch_fields.get("pickup_allowed"))

    result = update_child_guardian_link(target.get("id"), patch_fields)
    if result is None:
        return jsonify({"error": "failed to update child-guardian link"}), 500
    return jsonify({"status": "updated", "link_id": target.get("id"), "fields": patch_fields})


@app.route("/pickup/verify", methods=["POST"])
def api_pickup_verify():
    """Verify whether a guardian is allowed to pick up a child."""
    data = request.get_json(force=True, silent=True) or {}
    child_id_val = data.get("child_id")
    guardian_id_val = data.get("guardian_id")
    pickup_password = str(data.get("pickup_password", ""))

    if not child_id_val or not guardian_id_val:
        return jsonify({"error": "child_id and guardian_id required"}), 400

    links = get_child_guardian_links(child_id_val)
    link = next((r for r in links if str(r["fields"].get("guardian")) == str(guardian_id_val)), None)
    if not link:
        return jsonify({"allowed": False, "reason": "guardian_not_linked"})

    legal_status = str(link["fields"].get("legal_status", "custodial")).lower()
    if legal_status in {"restricted", "no_contact"}:
        return jsonify({"allowed": False, "reason": "legal_restriction"})

    if not _to_bool(link["fields"].get("pickup_allowed", True)):
        return jsonify({"allowed": False, "reason": "pickup_not_allowed"})

    expected_password = str(link["fields"].get("pickup_password", "")).strip()
    if expected_password and expected_password != pickup_password:
        return jsonify({"allowed": False, "reason": "pickup_password_mismatch"})

    return jsonify({"allowed": True, "reason": "ok", "link_id": link.get("id")})


@app.route("/pickup/events", methods=["POST"])
@idempotent_endpoint
def api_pickup_event():
    """Create a pickup verification/audit event."""
    data = request.get_json(force=True, silent=True) or {}
    child_id_val = data.get("child_id")
    approved = data.get("approved")
    if child_id_val is None or approved is None:
        return jsonify({"error": "child_id and approved required"}), 400

    approved_bool = _to_bool(approved)
    denial_code = str(data.get("denial_code", "")).strip().lower()
    override_used = _to_bool(data.get("override_used", False))

    if not approved_bool:
        if not denial_code:
            return jsonify({"error": "denial_code is required when approved is false"}), 400
        if denial_code not in PICKUP_DENIAL_CODES:
            return jsonify({
                "error": "invalid denial_code",
                "allowed_denial_codes": sorted(PICKUP_DENIAL_CODES),
            }), 400
    else:
        denial_code = ""

    override_reason = str(data.get("override_reason", "")).strip()
    override_approved_by = data.get("override_approved_by")
    if override_used:
        if not override_reason or override_approved_by in (None, ""):
            return jsonify({
                "error": "override_reason and override_approved_by are required when override_used is true"
            }), 400

    event = add_pickup_event(
        child_id_val=_to_grist_id(child_id_val),
        requested_by_guardian=_to_grist_id(data.get("requested_by_guardian")),
        approved=approved_bool,
        approved_by_staff=_to_grist_id(data.get("approved_by_staff")),
        method=str(data.get("method", "manual")),
        denial_reason=str(data.get("denial_reason", "")),
        timestamp=data.get("timestamp"),
        denial_code=denial_code,
        override_used=override_used,
        override_reason=override_reason,
        override_approved_by=_to_grist_id(override_approved_by),
    )
    if event is None:
        return jsonify({"error": "failed to create pickup event"}), 500
    return jsonify({"status": "logged"})


@app.route("/pickup/events", methods=["GET"])
def api_pickup_events():
    """List pickup events for audit review with optional filters."""
    controls, errors = _parse_list_controls(
        allowed_sort_fields={"id", "timestamp", "approved", "child", "requested_by_guardian", "approved_by_staff", "method"},
        default_sort_by="timestamp",
        default_sort_dir="desc",
    )
    if errors or not controls:
        return _validation_error_response(errors)

    child_id_val = request.args.get("child_id")
    approved_param = request.args.get("approved")
    approved = None
    if approved_param is not None and approved_param != "":
        approved = _to_bool(approved_param)
    from_dt = _parse_iso_datetime(request.args.get("from"))
    to_dt = _parse_iso_datetime(request.args.get("to"))

    events = get_pickup_events(child_id_val=child_id_val, approved=approved)
    filtered = []
    for event in events:
        fields = event.get("fields", {})
        event_dt = _parse_iso_datetime(fields.get("timestamp"))
        if from_dt and (not event_dt or event_dt < from_dt):
            continue
        if to_dt and (not event_dt or event_dt > to_dt):
            continue
        filtered.append({"id": event.get("id"), "fields": fields})

    sorted_rows = _sort_records(filtered, sort_by=controls["sort_by"], sort_dir=controls["sort_dir"])
    paged = _paginate_records(sorted_rows, limit=controls["limit"], offset=controls["offset"])
    return jsonify({
        "count": len(sorted_rows),
        "limit": controls["limit"],
        "offset": controls["offset"],
        "sort_by": controls["sort_by"],
        "sort_dir": controls["sort_dir"],
        "events": paged,
    })


@app.route("/billing/invoices/generate", methods=["POST"])
@idempotent_endpoint
def api_billing_generate_invoices():
    """Create draft invoices from request payload."""
    data = request.get_json(force=True, silent=True) or {}
    invoices_payload = data.get("invoices", [])
    if not isinstance(invoices_payload, list) or not invoices_payload:
        return jsonify({"error": "invoices array required"}), 400

    required = {"account", "period_start", "period_end", "due_date", "total_due"}
    normalized = []
    for item in invoices_payload:
        if not isinstance(item, dict):
            return jsonify({"error": "invoice entries must be objects"}), 400
        missing = [field for field in required if item.get(field) in (None, "")]
        if missing:
            return jsonify({"error": f"invoice missing fields: {', '.join(missing)}"}), 400
        record = dict(item)
        record["account"] = _to_grist_id(record.get("account"))
        record["total_due"] = _to_float(record.get("total_due"))
        record["status"] = str(record.get("status", "issued")).strip().lower()
        record["subtotal"] = _to_float(record.get("subtotal", record.get("total_due")))
        record["subsidy_credit"] = _to_float(record.get("subsidy_credit", 0))
        record["late_fees"] = _to_float(record.get("late_fees", 0))
        for date_field in ("period_start", "period_end", "due_date"):
            parsed_date = _parse_iso_date(record.get(date_field))
            if not parsed_date:
                return jsonify({"error": f"{date_field} must be ISO date (YYYY-MM-DD)"}), 400
            record[date_field] = parsed_date
        normalized.append(record)

    result = create_invoices(normalized)
    if result is None:
        return jsonify({"error": "failed to create invoices"}), 500
    created = result.get("records", [])
    return jsonify({"status": "created", "count": len(created), "invoice_ids": [r.get("id") for r in created]}), 201


@app.route("/billing/accounts/<account_id_val>/parties", methods=["GET"])
def api_billing_account_parties(account_id_val):
    """Return split-billing party rules for an account."""
    parties = get_billing_account_parties(account_id_val=account_id_val)
    return jsonify({
        "account_id": account_id_val,
        "count": len(parties),
        "parties": [{"id": p.get("id"), "fields": p.get("fields", {})} for p in parties],
    })


@app.route("/billing/accounts/<account_id_val>/parties", methods=["POST"])
def api_billing_account_add_party(account_id_val):
    """Create a split-billing party rule for an account."""
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "payload object required"}), 400

    guardian_id_val = data.get("guardian")
    if guardian_id_val in (None, ""):
        return jsonify({"error": "guardian is required"}), 400
    guardian = get_guardian_by_id(guardian_id_val)
    if not guardian:
        return jsonify({"error": f"guardian '{guardian_id_val}' not found"}), 404

    share_pct = _to_float(data.get("share_pct"))
    fixed_amount = _to_float(data.get("fixed_amount"))
    if share_pct <= 0 and fixed_amount <= 0:
        return jsonify({"error": "either share_pct or fixed_amount must be > 0"}), 400

    payload = {
        "account": _to_grist_id(account_id_val),
        "guardian": _to_grist_id(guardian_id_val),
        "payer_label": data.get("payer_label", ""),
        "share_pct": share_pct,
        "fixed_amount": fixed_amount,
        "priority": _to_float(data.get("priority", 100)),
        "auto_debit": _to_bool(data.get("auto_debit", False)),
        "status": str(data.get("status", "active")).strip().lower(),
        "notes": data.get("notes", ""),
    }
    result = create_billing_account_party(payload)
    if not result:
        return jsonify({"error": "failed to create billing account party"}), 500
    return jsonify({"status": "created", "party_id": result.get("id")}), 201


@app.route("/billing/accounts/<account_id_val>/parties/<party_id_val>", methods=["PATCH"])
def api_billing_account_patch_party(account_id_val, party_id_val):
    """Patch split-billing party rules for an account."""
    parties = get_billing_account_parties(account_id_val=account_id_val)
    target = next((p for p in parties if str(p.get("id")) == str(party_id_val)), None)
    if not target:
        return jsonify({"error": "billing account party not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "fields object required"}), 400

    allowed = {"payer_label", "share_pct", "fixed_amount", "priority", "auto_debit", "status", "notes"}
    patch_fields = {key: value for key, value in data.items() if key in allowed}
    if not patch_fields:
        return jsonify({"error": "no allowed fields provided"}), 400

    if "share_pct" in patch_fields:
        patch_fields["share_pct"] = _to_float(patch_fields.get("share_pct"))
    if "fixed_amount" in patch_fields:
        patch_fields["fixed_amount"] = _to_float(patch_fields.get("fixed_amount"))
    if "priority" in patch_fields:
        patch_fields["priority"] = _to_float(patch_fields.get("priority"))
    if "auto_debit" in patch_fields:
        patch_fields["auto_debit"] = _to_bool(patch_fields.get("auto_debit"))
    if "status" in patch_fields:
        patch_fields["status"] = str(patch_fields.get("status", "")).strip().lower()

    result = update_billing_account_party(party_id_val, patch_fields)
    if result is None:
        return jsonify({"error": "failed to update billing account party"}), 500
    return jsonify({"status": "updated", "party_id": party_id_val, "fields": patch_fields})


@app.route("/billing/invoices/<invoice_id_val>/allocate", methods=["POST"])
def api_billing_invoice_allocate(invoice_id_val):
    """Compute split-billing allocations for an invoice."""
    invoice = get_invoice(invoice_id_val)
    if not invoice:
        return jsonify({"error": "invoice not found"}), 404

    account_id = invoice.get("fields", {}).get("account")
    if not account_id:
        return jsonify({"error": "invoice has no account"}), 400

    parties = get_billing_account_parties(account_id_val=account_id)
    allocations = _compute_invoice_allocations(invoice, parties)
    if not allocations:
        return jsonify({"error": "no active billing parties or valid allocation rules"}), 400

    return jsonify({
        "invoice_id": invoice_id_val,
        "account_id": account_id,
        "total_due": _to_float(invoice.get("fields", {}).get("total_due")),
        "allocation_count": len(allocations),
        "allocations": allocations,
    })


@app.route("/billing/invoices/<invoice_id_val>/autopay/run", methods=["POST"])
@idempotent_endpoint
def api_billing_invoice_autopay_run(invoice_id_val):
    """Execute autopay attempts for auto-debit parties on an invoice."""
    invoice = get_invoice(invoice_id_val)
    if not invoice:
        return jsonify({"error": "invoice not found"}), 404

    account_id = invoice.get("fields", {}).get("account")
    if not account_id:
        return jsonify({"error": "invoice has no account"}), 400

    parties = get_billing_account_parties(account_id_val=account_id)
    allocations = _compute_invoice_allocations(invoice, parties)
    if not allocations:
        return jsonify({"error": "no active billing parties or valid allocation rules"}), 400

    data = request.get_json(force=True, silent=True) or {}
    fail_party_ids = {
        str(item) for item in (data.get("simulate_fail_party_ids", []) if isinstance(data.get("simulate_fail_party_ids", []), list) else [])
    }
    dry_run = _to_bool(data.get("dry_run", False))
    attempted_at = datetime.utcnow().isoformat(timespec="seconds")

    attempts = []
    for allocation in allocations:
        party_id_val = allocation.get("party_id")
        if not _to_bool(allocation.get("auto_debit", False)):
            continue
        if str(allocation.get("status", "active")).lower() != "active":
            continue

        amount = _to_float(allocation.get("allocated_amount"))
        if amount <= 0:
            continue

        should_fail = str(party_id_val) in fail_party_ids
        attempt_status = "failed" if should_fail else ("simulated" if dry_run else "posted")
        processor_ref = f"AUTO-{invoice_id_val}-{party_id_val}-{attempted_at.replace(':', '').replace('-', '')}"
        error_code = "simulated_decline" if should_fail else ""
        error_message = "Simulated processor decline" if should_fail else ""

        attempt_payload = {
            "invoice": invoice_id_val,
            "party": party_id_val,
            "amount": amount,
            "attempted_at": attempted_at,
            "status": attempt_status,
            "processor_ref": processor_ref,
            "error_code": error_code,
            "error_message": error_message,
        }
        attempt_rec = create_autopay_attempt(attempt_payload)
        if attempt_rec is None:
            return jsonify({"error": "failed to record autopay attempt"}), 500

        payment_id = None
        if not should_fail and not dry_run:
            payment = add_payment({
                "invoice": _to_grist_id(invoice_id_val),
                "amount": amount,
                "paid_at": attempted_at,
                "method": "autopay",
                "txn_ref": processor_ref,
                "status": "posted",
            })
            if not payment:
                return jsonify({"error": "failed to post autopay payment"}), 500
            payment_id = payment.get("id")

        attempts.append({
            "attempt_id": attempt_rec.get("id"),
            "party_id": party_id_val,
            "amount": amount,
            "status": attempt_status,
            "processor_ref": processor_ref,
            "error_code": error_code,
            "error_message": error_message,
            "payment_id": payment_id,
        })

    if not attempts:
        return jsonify({"error": "no eligible auto-debit parties for invoice"}), 400

    refreshed_invoice = get_invoice(invoice_id_val)
    if refreshed_invoice:
        bal = _invoice_balance(refreshed_invoice)
        if bal["balance"] <= 0:
            update_invoice(invoice_id_val, {"status": "paid"})
        elif bal["total_paid"] > 0:
            update_invoice(invoice_id_val, {"status": "partial"})

    return jsonify({
        "invoice_id": invoice_id_val,
        "dry_run": dry_run,
        "attempt_count": len(attempts),
        "attempts": attempts,
    })


@app.route("/billing/invoices/<invoice_id_val>/autopay/attempts", methods=["GET"])
def api_billing_invoice_autopay_attempts(invoice_id_val):
    """List autopay attempt audit rows for an invoice."""
    controls, errors = _parse_list_controls(
        allowed_sort_fields={"id", "attempted_at", "status", "amount", "party", "processor_ref"},
        default_sort_by="attempted_at",
        default_sort_dir="desc",
    )
    if errors or not controls:
        return _validation_error_response(errors)

    attempts = get_autopay_attempts(invoice_id_val=invoice_id_val)
    rows = [{"id": a.get("id"), "fields": a.get("fields", {})} for a in attempts]
    sorted_rows = _sort_records(rows, sort_by=controls["sort_by"], sort_dir=controls["sort_dir"])
    paged = _paginate_records(sorted_rows, limit=controls["limit"], offset=controls["offset"])
    return jsonify({
        "invoice_id": invoice_id_val,
        "count": len(sorted_rows),
        "limit": controls["limit"],
        "offset": controls["offset"],
        "sort_by": controls["sort_by"],
        "sort_dir": controls["sort_dir"],
        "attempts": paged,
    })


@app.route("/billing/invoices", methods=["GET"])
def api_billing_invoices():
    """Return invoices with optional status/account filters."""
    status = request.args.get("status")
    account_id = request.args.get("account_id")
    invoices = get_invoices(status=status, account_id=account_id)
    output = []
    for invoice in invoices:
        bal = _invoice_balance(invoice)
        output.append({
            "id": invoice.get("id"),
            "fields": invoice.get("fields", {}),
            "total_paid": bal["total_paid"],
            "balance": bal["balance"],
        })
    return jsonify({"count": len(output), "invoices": output})


@app.route("/billing/invoices/<invoice_id_val>", methods=["GET"])
def api_billing_invoice(invoice_id_val):
    """Return one invoice with payment and balance details."""
    invoice = get_invoice(invoice_id_val)
    if not invoice:
        return jsonify({"error": "invoice not found"}), 404
    payments = get_payments(invoice_id_val)
    bal = _invoice_balance(invoice)
    return jsonify({
        "invoice": {"id": invoice.get("id"), "fields": invoice.get("fields", {})},
        "payments": [{"id": p.get("id"), "fields": p.get("fields", {})} for p in payments],
        "total_paid": bal["total_paid"],
        "balance": bal["balance"],
    })


@app.route("/billing/payments", methods=["POST"])
def api_billing_payment():
    """Record a payment and update invoice status when fully paid."""
    data = request.get_json(force=True, silent=True) or {}
    required = {"invoice", "amount", "paid_at", "method"}
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        return jsonify({"error": f"missing payment fields: {', '.join(missing)}"}), 400

    payment = add_payment({
        "invoice": _to_grist_id(data.get("invoice")),
        "amount": _to_float(data.get("amount")),
        "paid_at": data.get("paid_at"),
        "method": data.get("method"),
        "txn_ref": data.get("txn_ref", ""),
        "status": str(data.get("status", "posted")).strip().lower(),
    })
    if not payment:
        return jsonify({"error": "failed to record payment"}), 500

    invoice = get_invoice(_to_grist_id(data.get("invoice")))
    if invoice:
        bal = _invoice_balance(invoice)
        if bal["balance"] <= 0:
            update_invoice(invoice.get("id"), {"status": "paid"})
        elif str(invoice["fields"].get("status", "")).lower() in {"issued", "draft"}:
            update_invoice(invoice.get("id"), {"status": "partial"})

    return jsonify({"status": "posted", "payment_id": payment.get("id")}), 201


@app.route("/billing/aging", methods=["GET"])
def api_billing_aging():
    """Return invoice aging buckets based on open balances and due dates."""
    invoices = get_invoices()
    buckets = {"current": 0.0, "1_30": 0.0, "31_60": 0.0, "61_plus": 0.0}
    open_items = []

    for invoice in invoices:
        fields = invoice.get("fields", {})
        status = str(fields.get("status", "")).lower()
        if status in {"paid", "void"}:
            continue
        bal = _invoice_balance(invoice)
        if bal["balance"] <= 0:
            continue
        overdue_days = _days_overdue(str(fields.get("due_date", "")))
        if overdue_days <= 0:
            buckets["current"] += bal["balance"]
            bucket = "current"
        elif overdue_days <= 30:
            buckets["1_30"] += bal["balance"]
            bucket = "1_30"
        elif overdue_days <= 60:
            buckets["31_60"] += bal["balance"]
            bucket = "31_60"
        else:
            buckets["61_plus"] += bal["balance"]
            bucket = "61_plus"
        open_items.append({
            "invoice_id": invoice.get("id"),
            "account": fields.get("account"),
            "due_date": fields.get("due_date"),
            "balance": bal["balance"],
            "overdue_days": overdue_days,
            "bucket": bucket,
        })

    return jsonify({"buckets": buckets, "open_items": open_items})


@app.route("/subsidy/claims", methods=["POST"])
@idempotent_endpoint
def api_subsidy_claim_create():
    """Create a subsidy claim record."""
    data = request.get_json(force=True, silent=True) or {}
    required = {"claim_month", "child", "program", "expected_amount"}
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        return jsonify({"error": f"missing subsidy claim fields: {', '.join(missing)}"}), 400

    expected_amount = _to_float(data.get("expected_amount"))
    received_amount = _to_float(data.get("received_amount", 0))
    variance = round(received_amount - expected_amount, 2)
    status = str(data.get("status", "submitted")).strip().lower()
    if received_amount > 0:
        status = "paid" if variance == 0 else "variance"

    payload = {
        "claim_month": str(data.get("claim_month")),
        "child": _to_grist_id(data.get("child")),
        "program": str(data.get("program")),
        "expected_amount": expected_amount,
        "received_amount": received_amount,
        "variance": variance,
        "status": status,
        "submitted_at": data.get("submitted_at") or datetime.utcnow().isoformat(timespec="seconds"),
        "paid_at": data.get("paid_at"),
        "notes": str(data.get("notes", "")),
    }
    result = create_subsidy_claim(payload)
    if not result:
        return jsonify({"error": "failed to create subsidy claim"}), 500
    return jsonify({"status": "created", "claim_id": result.get("id")}), 201


@app.route("/subsidy/claims", methods=["GET"])
def api_subsidy_claims_list():
    """List subsidy claims with optional month/status/program filters."""
    controls, errors = _parse_list_controls(
        allowed_sort_fields={"id", "claim_month", "status", "program", "expected_amount", "received_amount", "variance", "submitted_at", "paid_at"},
        default_sort_by="claim_month",
        default_sort_dir="desc",
    )
    if errors or not controls:
        return _validation_error_response(errors)

    claim_month = request.args.get("claim_month")
    status = request.args.get("status")
    program = request.args.get("program")
    claims = get_subsidy_claims(claim_month=claim_month, status=status, program=program)
    rows = [{"id": c.get("id"), "fields": c.get("fields", {})} for c in claims]
    sorted_rows = _sort_records(rows, sort_by=controls["sort_by"], sort_dir=controls["sort_dir"])
    paged = _paginate_records(sorted_rows, limit=controls["limit"], offset=controls["offset"])
    return jsonify({
        "count": len(sorted_rows),
        "limit": controls["limit"],
        "offset": controls["offset"],
        "sort_by": controls["sort_by"],
        "sort_dir": controls["sort_dir"],
        "claims": paged,
    })


@app.route("/subsidy/reconcile/<claim_id_val>", methods=["POST"])
@idempotent_endpoint
def api_subsidy_reconcile_claim(claim_id_val):
    """Reconcile a claim by updating received amount and computed variance/status."""
    claims = get_subsidy_claims()
    claim = next((item for item in claims if str(item.get("id")) == str(claim_id_val)), None)
    if not claim:
        return jsonify({"error": "subsidy claim not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    expected_amount = _to_float(claim.get("fields", {}).get("expected_amount"))
    received_amount = _to_float(data.get("received_amount", claim.get("fields", {}).get("received_amount", 0)))
    variance = round(received_amount - expected_amount, 2)
    status = str(data.get("status", "")).strip().lower()
    if not status:
        if received_amount <= 0:
            status = "submitted"
        elif variance == 0:
            status = "paid"
        else:
            status = "variance"

    patch = {
        "received_amount": received_amount,
        "variance": variance,
        "status": status,
        "paid_at": data.get("paid_at") or (datetime.utcnow().isoformat(timespec="seconds") if received_amount > 0 else claim.get("fields", {}).get("paid_at")),
        "notes": str(data.get("notes", claim.get("fields", {}).get("notes", ""))),
    }
    result = update_subsidy_claim(claim_id_val, patch)
    if result is None:
        return jsonify({"error": "failed to reconcile subsidy claim"}), 500
    return jsonify({"status": "reconciled", "claim_id": claim_id_val, "fields": patch})


@app.route("/subsidy/reconciliation/summary", methods=["GET"])
def api_subsidy_reconciliation_summary():
    """Return reconciliation totals and variance buckets for subsidy claims."""
    claim_month = request.args.get("claim_month")
    claims = get_subsidy_claims(claim_month=claim_month)

    expected_total = 0.0
    received_total = 0.0
    variance_total = 0.0
    by_status: dict[str, int] = {}
    buckets = {"exact": 0, "overpaid": 0, "underpaid": 0, "unpaid": 0}
    claim_rows = []

    for claim in claims:
        fields = claim.get("fields", {})
        expected = _to_float(fields.get("expected_amount"))
        received = _to_float(fields.get("received_amount"))
        variance = round(received - expected, 2)
        status = str(fields.get("status", "unknown")).lower()
        by_status[status] = by_status.get(status, 0) + 1

        expected_total += expected
        received_total += received
        variance_total += variance

        if received <= 0:
            buckets["unpaid"] += 1
        elif variance == 0:
            buckets["exact"] += 1
        elif variance > 0:
            buckets["overpaid"] += 1
        else:
            buckets["underpaid"] += 1

        claim_rows.append({
            "id": claim.get("id"),
            "claim_month": fields.get("claim_month"),
            "program": fields.get("program"),
            "child": fields.get("child"),
            "expected_amount": expected,
            "received_amount": received,
            "variance": variance,
            "status": status,
        })

    return jsonify({
        "claim_month": claim_month,
        "count": len(claims),
        "totals": {
            "expected_amount": round(expected_total, 2),
            "received_amount": round(received_total, 2),
            "variance": round(variance_total, 2),
        },
        "status_counts": by_status,
        "variance_buckets": buckets,
        "claims": claim_rows,
    })


@app.route("/compliance/medication-logs", methods=["POST"])
def api_compliance_add_medication_log():
    """Create a medication administration log entry."""
    data = request.get_json(force=True, silent=True) or {}
    required = {"child", "medication_name", "dosage"}
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        return jsonify({"error": f"missing medication fields: {', '.join(missing)}"}), 400

    administered = _to_bool(data.get("administered", True))
    administered_by = data.get("administered_by")
    if administered and administered_by in (None, ""):
        return jsonify({"error": "administered_by is required when administered is true"}), 400

    payload = {
        "child": _to_grist_id(data.get("child")),
        "medication_name": str(data.get("medication_name")),
        "dosage": str(data.get("dosage")),
        "administered": administered,
        "administered_at": data.get("administered_at") or datetime.utcnow().isoformat(timespec="seconds"),
        "administered_by": _to_grist_id(administered_by),
        "reason": str(data.get("reason", "")),
        "notes": str(data.get("notes", "")),
    }
    result = add_medication_log(payload)
    if not result:
        return jsonify({"error": "failed to create medication log"}), 500
    return jsonify({"status": "created", "log_id": result.get("id")}), 201


@app.route("/compliance/medication-logs", methods=["GET"])
def api_compliance_list_medication_logs():
    """List medication logs, optionally filtered by child/date."""
    child_id_val = request.args.get("child_id")
    day = request.args.get("date")
    logs = get_medication_logs(child_id_val=child_id_val)
    logs = _filter_records_by_day(logs, "administered_at", day)
    return jsonify({"count": len(logs), "logs": [{"id": r.get("id"), "fields": r.get("fields", {})} for r in logs]})


@app.route("/compliance/sanitation-checks", methods=["POST"])
def api_compliance_add_sanitation_check():
    """Create a sanitation checklist entry."""
    data = request.get_json(force=True, silent=True) or {}
    required = {"check_area", "check_item", "status", "checked_by"}
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        return jsonify({"error": f"missing sanitation fields: {', '.join(missing)}"}), 400

    status = str(data.get("status", "")).strip().lower()
    if status not in SANITATION_STATUSES:
        return jsonify({"error": "invalid status", "allowed_statuses": sorted(SANITATION_STATUSES)}), 400

    payload = {
        "check_area": str(data.get("check_area")),
        "check_item": str(data.get("check_item")),
        "status": status,
        "checked_at": data.get("checked_at") or datetime.utcnow().isoformat(timespec="seconds"),
        "checked_by": _to_grist_id(data.get("checked_by")),
        "notes": str(data.get("notes", "")),
    }
    result = add_sanitation_check(payload)
    if not result:
        return jsonify({"error": "failed to create sanitation check"}), 500
    return jsonify({"status": "created", "check_id": result.get("id")}), 201


@app.route("/compliance/sanitation-checks", methods=["GET"])
def api_compliance_list_sanitation_checks():
    """List sanitation checks, optionally filtered by status/date."""
    status = request.args.get("status")
    day = request.args.get("date")
    checks = get_sanitation_checks(status=status)
    checks = _filter_records_by_day(checks, "checked_at", day)
    return jsonify({"count": len(checks), "checks": [{"id": r.get("id"), "fields": r.get("fields", {})} for r in checks]})


@app.route("/compliance/sleep-safety-checks", methods=["POST"])
def api_compliance_add_sleep_safety_check():
    """Create a sleep safety checklist entry."""
    data = request.get_json(force=True, silent=True) or {}
    required = {"child", "status", "checked_by"}
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        return jsonify({"error": f"missing sleep safety fields: {', '.join(missing)}"}), 400

    status = str(data.get("status", "")).strip().lower()
    if status not in SLEEP_SAFETY_STATUSES:
        return jsonify({"error": "invalid status", "allowed_statuses": sorted(SLEEP_SAFETY_STATUSES)}), 400

    payload = {
        "child": _to_grist_id(data.get("child")),
        "status": status,
        "check_time": data.get("check_time") or datetime.utcnow().isoformat(timespec="seconds"),
        "checked_by": _to_grist_id(data.get("checked_by")),
        "notes": str(data.get("notes", "")),
    }
    result = add_sleep_safety_check(payload)
    if not result:
        return jsonify({"error": "failed to create sleep safety check"}), 500
    return jsonify({"status": "created", "check_id": result.get("id")}), 201


@app.route("/compliance/sleep-safety-checks", methods=["GET"])
def api_compliance_list_sleep_safety_checks():
    """List sleep safety checks, optionally filtered by child/status/date."""
    child_id_val = request.args.get("child_id")
    status = request.args.get("status")
    day = request.args.get("date")
    checks = get_sleep_safety_checks(child_id_val=child_id_val, status=status)
    checks = _filter_records_by_day(checks, "check_time", day)
    return jsonify({"count": len(checks), "checks": [{"id": r.get("id"), "fields": r.get("fields", {})} for r in checks]})


@app.route("/waitlist", methods=["GET"])
def api_waitlist():
    """Return waitlist entries, optionally filtered by status."""
    controls, errors = _parse_list_controls(
        allowed_sort_fields={"id", "status", "desired_start_date", "next_follow_up_at", "last_contact_at", "priority_score", "conversion_score", "retention_risk_score"},
        default_sort_by="id",
        default_sort_dir="asc",
    )
    if errors or not controls:
        return _validation_error_response(errors)

    status = request.args.get("status")
    entries = get_waitlist(status=status)
    due_only = _to_bool(request.args.get("followup_due", False))
    if due_only:
        entries = _waitlist_followup_due_entries(entries)
    rows = [{"id": e.get("id"), "fields": e.get("fields", {})} for e in entries]
    sorted_rows = _sort_records(rows, sort_by=controls["sort_by"], sort_dir=controls["sort_dir"])
    paged = _paginate_records(sorted_rows, limit=controls["limit"], offset=controls["offset"])
    return jsonify({
        "count": len(sorted_rows),
        "limit": controls["limit"],
        "offset": controls["offset"],
        "sort_by": controls["sort_by"],
        "sort_dir": controls["sort_dir"],
        "entries": paged,
    })


@app.route("/waitlist", methods=["POST"])
@idempotent_endpoint
def api_waitlist_add():
    """Create a waitlist entry."""
    data = request.get_json(force=True, silent=True) or {}
    required = {"child_first_name", "child_last_name", "desired_start_date", "status"}
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        return jsonify({"error": f"missing waitlist fields: {', '.join(missing)}"}), 400

    data.setdefault("priority_score", 0)
    data["priority_score"] = _to_float(data.get("priority_score", 0))
    status = str(data.get("status", "new")).strip().lower()
    desired_start_date = _parse_iso_date(data.get("desired_start_date"))
    if not desired_start_date:
        return jsonify({"error": "desired_start_date must be ISO date (YYYY-MM-DD)"}), 400
    sla_hours = _to_float(data.get("follow_up_sla_hours", WAITLIST_SLA_HOURS.get(status, 48)))
    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    data["desired_start_date"] = desired_start_date
    data["status"] = status
    data["follow_up_sla_hours"] = sla_hours
    data.setdefault("last_contact_at", now_iso)
    if data.get("next_follow_up_at") in (None, ""):
        data["next_follow_up_at"] = (datetime.utcnow() + timedelta(hours=sla_hours)).isoformat(timespec="seconds")
    data.setdefault("conversion_score", _to_float(data.get("priority_score", 0)))
    data.setdefault("retention_risk_score", _to_float(data.get("retention_risk_score", 0)))
    result = add_waitlist_entry(data)
    if not result:
        return jsonify({"error": "failed to create waitlist entry"}), 500
    return jsonify({"status": "created", "entry_id": result.get("id")}), 201


@app.route("/waitlist/<entry_id_val>", methods=["PATCH"])
def api_waitlist_patch(entry_id_val):
    """Patch a waitlist entry."""
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "fields object required"}), 400
    if "follow_up_sla_hours" in data:
        data["follow_up_sla_hours"] = _to_float(data.get("follow_up_sla_hours"))
    if "conversion_score" in data:
        data["conversion_score"] = _to_float(data.get("conversion_score"))
    if "retention_risk_score" in data:
        data["retention_risk_score"] = _to_float(data.get("retention_risk_score"))
    if "status" in data:
        data["status"] = str(data.get("status", "")).strip().lower()
    result = update_waitlist_entry(entry_id_val, data)
    if result is None:
        return jsonify({"error": "failed to update waitlist entry"}), 500
    return jsonify({"status": "updated", "entry_id": entry_id_val})


@app.route("/waitlist/<entry_id_val>/automation-action", methods=["POST"])
def api_waitlist_automation_action(entry_id_val):
    """Apply a validated automation action patch to a waitlist entry."""
    entries = get_waitlist()
    entry = next((item for item in entries if str(item.get("id")) == str(entry_id_val)), None)
    if not entry:
        return jsonify({"error": "waitlist entry not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    action_key = str(data.get("action_key", "")).strip().lower()
    if not action_key:
        return jsonify({"error": "action_key is required"}), 400

    now = datetime.utcnow().isoformat(timespec="seconds")
    patch = {
        "automation_last_action": action_key,
        "automation_last_action_at": now,
        "automation_escalated": _to_bool(data.get("escalate", False)),
        "automation_escalated_at": now if _to_bool(data.get("escalate", False)) else "",
        "automation_escalation_reason": str(data.get("escalation_reason", "")),
        "automation_nudge_sent_at": now if _to_bool(data.get("nudge_sent", False)) else "",
    }

    if "follow_up_sla_hours" in data:
        sla_hours = _to_float(data.get("follow_up_sla_hours"))
        patch["follow_up_sla_hours"] = sla_hours
        if not data.get("next_follow_up_at"):
            patch["next_follow_up_at"] = (datetime.utcnow() + timedelta(hours=sla_hours)).isoformat(timespec="seconds")

    if "next_follow_up_at" in data and data.get("next_follow_up_at"):
        next_follow_up_raw = str(data.get("next_follow_up_at"))
        next_follow_up = _parse_iso_datetime(next_follow_up_raw)
        if not next_follow_up:
            return jsonify({"error": "next_follow_up_at must be ISO datetime"}), 400
        patch["next_follow_up_at"] = next_follow_up.isoformat(timespec="seconds")

    result = update_waitlist_entry(entry_id_val, patch)
    if result is None:
        return jsonify({"error": "failed to apply automation action"}), 500
    return jsonify({"status": "updated", "entry_id": entry_id_val, "action_key": action_key, "fields": patch})


@app.route("/waitlist/<entry_id_val>/advance", methods=["POST"])
def api_waitlist_advance(entry_id_val):
    """Advance waitlist status to next stage or requested status."""
    entries = get_waitlist()
    entry = next((item for item in entries if str(item.get("id")) == str(entry_id_val)), None)
    if not entry:
        return jsonify({"error": "waitlist entry not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    target_status = data.get("status")
    if target_status:
        new_status = str(target_status).strip().lower()
    else:
        current = str(entry["fields"].get("status", "new")).lower()
        if current in WAITLIST_FLOW and current != WAITLIST_FLOW[-1]:
            new_status = WAITLIST_FLOW[WAITLIST_FLOW.index(current) + 1]
        else:
            new_status = current

    now = datetime.utcnow()
    sla_hours = _to_float(data.get("follow_up_sla_hours", entry.get("fields", {}).get("follow_up_sla_hours", WAITLIST_SLA_HOURS.get(new_status, 48))))
    patch = {
        "status": new_status,
        "last_contact_at": now.isoformat(timespec="seconds"),
        "follow_up_sla_hours": sla_hours,
        "next_follow_up_at": (now + timedelta(hours=sla_hours)).isoformat(timespec="seconds"),
    }
    if "retention_risk_score" in data:
        patch["retention_risk_score"] = _to_float(data.get("retention_risk_score"))
    result = update_waitlist_entry(entry_id_val, patch)
    if result is None:
        return jsonify({"error": "failed to advance waitlist entry"}), 500
    return jsonify({"status": "advanced", "entry_id": entry_id_val, "new_status": new_status})


@app.route("/waitlist/<entry_id_val>/schedule-tour", methods=["POST"])
def api_waitlist_schedule_tour(entry_id_val):
    """Schedule a waitlist tour and set follow-up SLA."""
    entries = get_waitlist()
    entry = next((item for item in entries if str(item.get("id")) == str(entry_id_val)), None)
    if not entry:
        return jsonify({"error": "waitlist entry not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    tour_date = data.get("tour_date")
    if not tour_date:
        return jsonify({"error": "tour_date is required"}), 400
    sla_hours = _to_float(data.get("follow_up_sla_hours", WAITLIST_SLA_HOURS.get("tour_scheduled", 24)))
    next_follow_up_at = data.get("next_follow_up_at")
    if not next_follow_up_at:
        tour_dt = _parse_iso_datetime(str(tour_date))
        if not tour_dt:
            return jsonify({"error": "tour_date must be ISO datetime"}), 400
        next_follow_up_at = (tour_dt + timedelta(hours=sla_hours)).isoformat(timespec="seconds")

    patch = {
        "status": "tour_scheduled",
        "tour_date": str(tour_date),
        "follow_up_sla_hours": sla_hours,
        "last_contact_at": datetime.utcnow().isoformat(timespec="seconds"),
        "next_follow_up_at": str(next_follow_up_at),
    }
    result = update_waitlist_entry(entry_id_val, patch)
    if result is None:
        return jsonify({"error": "failed to schedule tour"}), 500
    return jsonify({"status": "scheduled", "entry_id": entry_id_val, "tour_date": patch["tour_date"], "next_follow_up_at": patch["next_follow_up_at"]})


@app.route("/waitlist/followups/due", methods=["GET"])
def api_waitlist_followups_due():
    """Return waitlist entries with due follow-ups."""
    due = _waitlist_followup_due_entries(get_waitlist())
    return jsonify({"count": len(due), "entries": [{"id": e.get("id"), "fields": e.get("fields", {})} for e in due]})


@app.route("/waitlist/scoring/run", methods=["POST"])
def api_waitlist_scoring_run():
    """Compute conversion/risk scores for waitlist entries; optionally persist."""
    data = request.get_json(force=True, silent=True) or {}
    persist = _to_bool(data.get("persist", False))
    open_only = _to_bool(data.get("open_only", False))
    now = datetime.utcnow()
    open_stages = {"new", "contacted", "tour_scheduled", "offered"}

    entries = get_waitlist()
    results = []
    updated_count = 0
    errors = []
    risk_buckets = {"low": 0, "medium": 0, "high": 0}
    conversion_buckets = {"low": 0, "medium": 0, "high": 0}

    for entry in entries:
        fields = entry.get("fields", {})
        status = str(fields.get("status", "new")).strip().lower()
        if open_only and status not in open_stages:
            continue

        conversion_score, retention_risk_score, conversion_reasons, risk_reasons = _waitlist_score_entry(fields, now)
        if conversion_score >= 70:
            conversion_buckets["high"] += 1
        elif conversion_score >= 40:
            conversion_buckets["medium"] += 1
        else:
            conversion_buckets["low"] += 1

        if retention_risk_score >= 70:
            risk_buckets["high"] += 1
        elif retention_risk_score >= 40:
            risk_buckets["medium"] += 1
        else:
            risk_buckets["low"] += 1

        if persist:
            patch = {
                "conversion_score": conversion_score,
                "retention_risk_score": retention_risk_score,
            }
            updated = update_waitlist_entry(entry.get("id"), patch)
            if updated is None:
                errors.append({"entry_id": entry.get("id"), "error": "failed to update score fields"})
            else:
                updated_count += 1

        scored_fields = dict(fields)
        scored_fields["conversion_score"] = conversion_score
        scored_fields["retention_risk_score"] = retention_risk_score
        scored_fields["conversion_reason_codes"] = ",".join(conversion_reasons)
        scored_fields["risk_reason_codes"] = ",".join(risk_reasons)
        results.append({"id": entry.get("id"), "fields": scored_fields})

    status = "ok" if not errors else ("partial" if results else "error")
    code = 200 if status != "error" else 500
    return jsonify({
        "status": status,
        "persist": persist,
        "open_only": open_only,
        "count": len(results),
        "updated_count": updated_count,
        "risk_buckets": risk_buckets,
        "conversion_buckets": conversion_buckets,
        "entries": results,
        "errors": errors,
        "ran_at": now.isoformat(timespec="seconds"),
    }), code


@app.route("/waitlist/pipeline/summary", methods=["GET"])
def api_waitlist_pipeline_summary():
    """Return waitlist pipeline, conversion, SLA, and retention-risk summary."""
    entries = get_waitlist()
    stage_counts = {stage: 0 for stage in WAITLIST_FLOW}
    stage_counts["other"] = 0
    risk_buckets = {"low": 0, "medium": 0, "high": 0}
    conversion_buckets = {"low": 0, "medium": 0, "high": 0}
    stale_stage_counts = {"new": 0, "contacted": 0, "tour_scheduled": 0, "offered": 0}
    source_counts: dict[str, int] = {}
    total = len(entries)
    now = datetime.utcnow()

    for entry in entries:
        fields = entry.get("fields", {})
        status = str(fields.get("status", "new")).strip().lower()
        if status in stage_counts:
            stage_counts[status] += 1
        else:
            stage_counts["other"] += 1

        risk = _to_float(fields.get("retention_risk_score", 0))
        if risk >= 70:
            risk_buckets["high"] += 1
        elif risk >= 40:
            risk_buckets["medium"] += 1
        else:
            risk_buckets["low"] += 1

        conversion = _to_float(fields.get("conversion_score", 0))
        if conversion >= 70:
            conversion_buckets["high"] += 1
        elif conversion >= 40:
            conversion_buckets["medium"] += 1
        else:
            conversion_buckets["low"] += 1

        source = str(fields.get("source", "")).strip().lower()
        if source:
            source_counts[source] = source_counts.get(source, 0) + 1

        last_contact = _parse_iso_datetime(fields.get("last_contact_at"))
        contact_age_hours = ((now - last_contact).total_seconds() / 3600.0) if last_contact else None
        tour_dt = _parse_iso_datetime(fields.get("tour_date"))
        if status == "new" and contact_age_hours is not None and contact_age_hours > 48:
            stale_stage_counts["new"] += 1
        elif status == "contacted" and contact_age_hours is not None and contact_age_hours > 72:
            stale_stage_counts["contacted"] += 1
        elif status == "offered" and contact_age_hours is not None and contact_age_hours > 72:
            stale_stage_counts["offered"] += 1
        elif status == "tour_scheduled" and tour_dt and (now - tour_dt).total_seconds() / 3600.0 > 2:
            stale_stage_counts["tour_scheduled"] += 1

    offered = stage_counts.get("offered", 0)
    enrolled = stage_counts.get("enrolled", 0)
    conversion_rate_pct = round((enrolled / offered) * 100, 2) if offered > 0 else 0.0
    due_entries = _waitlist_followup_due_entries(entries)
    due_followups_by_stage = {"new": 0, "contacted": 0, "tour_scheduled": 0, "offered": 0, "other": 0}
    for due in due_entries:
        due_status = str(due.get("fields", {}).get("status", "")).strip().lower()
        if due_status in due_followups_by_stage:
            due_followups_by_stage[due_status] += 1
        else:
            due_followups_by_stage["other"] += 1

    return jsonify({
        "total": total,
        "stage_counts": stage_counts,
        "conversion_rate_pct": conversion_rate_pct,
        "followups_due_count": len(due_entries),
        "followups_due_by_stage": due_followups_by_stage,
        "retention_risk_buckets": risk_buckets,
        "conversion_score_buckets": conversion_buckets,
        "stale_stage_counts": stale_stage_counts,
        "top_sources": sorted(source_counts.items(), key=lambda kv: kv[1], reverse=True)[:5],
    })


@app.route("/forecast/assumptions", methods=["GET"])
def api_forecast_assumptions():
    """Return explicit forecasting assumptions used by automation/reporting."""
    operating_cost = _to_float(os.getenv("FORECAST_OPERATING_COST", "0"))
    if operating_cost <= 0:
        operating_cost = _to_float(os.getenv("BREAKEVEN_MONTHLY_COST", "0"))

    avg_rev_per_child = _to_float(os.getenv("AVG_MONTHLY_REVENUE_PER_CHILD", "0"))
    licensed_capacity = _to_float(os.getenv("FORECAST_LICENSED_CAPACITY", "0"))
    if licensed_capacity <= 0:
        rooms = get_room_ratios()
        licensed_capacity = sum(_to_float(r.get("fields", {}).get("max_children", 0)) for r in rooms)

    return jsonify({
        "operating_cost": operating_cost,
        "avg_revenue_per_child": avg_rev_per_child,
        "licensed_capacity": licensed_capacity,
        "source": {
            "operating_cost": "FORECAST_OPERATING_COST|BREAKEVEN_MONTHLY_COST",
            "avg_revenue_per_child": "AVG_MONTHLY_REVENUE_PER_CHILD",
            "licensed_capacity": "FORECAST_LICENSED_CAPACITY|Room_Ratios.max_children",
        },
    })


@app.route("/staffing/risk-summary", methods=["GET"])
def api_staffing_risk_summary():
    """Return room-level coverage gaps, predicted callout impact, and overtime risk."""
    callout_rate = _to_float(request.args.get("callout_rate", 0.08))
    if callout_rate < 0 or callout_rate > 1:
        return jsonify({"error": "callout_rate must be between 0 and 1"}), 400

    rooms = get_room_ratios()
    if not isinstance(rooms, list):
        rooms = []

    high_risk_count = 0
    medium_risk_count = 0
    coverage_gap_rooms = 0
    predicted_gap_rooms = 0
    overtime_risk_rooms = 0
    recommended_substitutes_total = 0
    unresolved_predicted_gap_rooms = 0
    day_of_week = datetime.utcnow().strftime("%A")
    room_results: list[dict[str, Any]] = []

    for room in rooms:
        fields = room.get("fields", {}) if isinstance(room, dict) else {}
        room_name = str(fields.get("room_name") or "Unknown Room")
        ratio_raw = str(fields.get("staff_child_ratio") or "0:0")
        ratio_den = 0.0
        if ":" in ratio_raw:
            try:
                ratio_den = float(ratio_raw.split(":", 1)[1])
            except (TypeError, ValueError):
                ratio_den = 0.0
        if ratio_den <= 0:
            ratio_den = 1.0

        enrolled = max(0.0, _to_float(fields.get("current_enrolled", 0)))
        scheduled_staff = max(0.0, _to_float(fields.get("scheduled_staff", 0)))
        required_staff = max(1.0, math.ceil(enrolled / ratio_den) if enrolled > 0 else 1.0)
        coverage_gap = max(0.0, required_staff - scheduled_staff)
        expected_callouts = round(scheduled_staff * callout_rate, 2)
        predicted_available = max(0.0, scheduled_staff - expected_callouts)
        predicted_gap = max(0.0, required_staff - predicted_available)
        overtime_risk_score = min(1.0, predicted_gap / required_staff) if required_staff > 0 else 0.0
        buffer_ratio = (scheduled_staff - required_staff) / required_staff if required_staff > 0 else 0.0

        risk_level = "low"
        if predicted_gap >= 1 or coverage_gap >= 1:
            risk_level = "high"
            high_risk_count += 1
        elif overtime_risk_score >= 0.15 or buffer_ratio < 0.10:
            risk_level = "medium"
            medium_risk_count += 1

        if coverage_gap > 0:
            coverage_gap_rooms += 1
        if predicted_gap > 0:
            predicted_gap_rooms += 1
            overtime_risk_rooms += 1

        recommended_needed = int(math.ceil(predicted_gap))
        recommendations: list[dict[str, Any]] = []
        if recommended_needed > 0:
            candidates = find_substitutes(day_of_week, room_name)
            for candidate in candidates[:recommended_needed]:
                recommendations.append({
                    "name": candidate.get("name", ""),
                    "phone": candidate.get("phone", ""),
                    "rooms_qualified": candidate.get("rooms_qualified", ""),
                    "is_on_call": _to_bool(candidate.get("is_on_call", False)),
                })
        recommended_substitutes_total += len(recommendations)
        resolved_gap = max(0.0, predicted_gap - len(recommendations))
        if predicted_gap > 0 and resolved_gap > 0:
            unresolved_predicted_gap_rooms += 1

        room_results.append({
            "room_name": room_name,
            "staff_child_ratio": ratio_raw,
            "current_enrolled": enrolled,
            "scheduled_staff": scheduled_staff,
            "required_staff": required_staff,
            "coverage_gap_now": round(coverage_gap, 2),
            "expected_callouts": expected_callouts,
            "predicted_available_staff": round(predicted_available, 2),
            "predicted_gap_after_callouts": round(predicted_gap, 2),
            "recommended_substitute_count": len(recommendations),
            "recommended_substitutes": recommendations,
            "remaining_gap_after_recommendations": round(resolved_gap, 2),
            "overtime_risk_score": round(overtime_risk_score, 3),
            "risk_level": risk_level,
        })

    total_rooms = len(room_results)
    return jsonify({
        "as_of": datetime.utcnow().isoformat(timespec="seconds"),
        "callout_rate_assumption": callout_rate,
        "total_rooms": total_rooms,
        "coverage_gap_rooms": coverage_gap_rooms,
        "predicted_gap_rooms": predicted_gap_rooms,
        "overtime_risk_rooms": overtime_risk_rooms,
        "recommended_substitutes_total": recommended_substitutes_total,
        "unresolved_predicted_gap_rooms": unresolved_predicted_gap_rooms,
        "risk_buckets": {
            "high": high_risk_count,
            "medium": medium_risk_count,
            "low": max(0, total_rooms - high_risk_count - medium_risk_count),
        },
        "rooms": room_results,
    })


@app.route("/regulatory/rules", methods=["GET"])
def api_regulatory_rules_list():
    """List regulatory rules with optional filters."""
    jurisdiction = request.args.get("jurisdiction")
    category = request.args.get("category")
    rule_key = request.args.get("rule_key")
    include_inactive = _to_bool(request.args.get("include_inactive", False))
    query = str(request.args.get("q", "")).strip().lower()
    rules = get_regulatory_rules(
        rule_key=rule_key,
        jurisdiction=jurisdiction,
        category=category,
        active_only=not include_inactive,
    )
    if query:
        filtered = []
        for row in rules:
            fields = row.get("fields", {})
            haystack = " ".join(
                str(fields.get(key, ""))
                for key in ("rule_key", "title", "category", "jurisdiction", "summary", "rule_text", "keywords")
            ).lower()
            if query in haystack:
                filtered.append(row)
        rules = filtered
    return jsonify({"count": len(rules), "rules": [{"id": r.get("id"), "fields": r.get("fields", {})} for r in rules]})


@app.route("/regulatory/rules/<rule_key>/versions", methods=["GET"])
def api_regulatory_rule_versions(rule_key):
    """Return all versions of a regulatory rule key."""
    versions = get_regulatory_rule_versions(rule_key)
    return jsonify({
        "rule_key": rule_key,
        "count": len(versions),
        "versions": [{"id": row.get("id"), "fields": row.get("fields", {})} for row in versions],
    })


@app.route("/regulatory/rules/ingest", methods=["POST"])
def api_regulatory_rules_ingest():
    """Ingest one or many versioned regulatory rules with active-version traceability."""
    data = request.get_json(force=True, silent=True) or {}
    rules = data.get("rules")
    if rules is None:
        rules = [data] if data else []
    if not isinstance(rules, list) or not rules:
        return jsonify({"error": "rules array is required"}), 400

    ingest_batch_id = str(data.get("ingest_batch_id") or datetime.utcnow().strftime("batch-%Y%m%d%H%M%S"))
    deactivate_previous = _to_bool(data.get("deactivate_previous", True))
    dry_run = _to_bool(data.get("dry_run", False))

    created = 0
    updated = 0
    errors = []
    items = []

    for idx, raw in enumerate(rules):
        if not isinstance(raw, dict):
            errors.append({"index": idx, "error": "rule item must be object"})
            continue
        fields, error = _normalize_regulatory_rule_payload(raw, ingest_batch_id)
        if error or not fields:
            errors.append({"index": idx, "error": error or "invalid payload"})
            continue

        existing_version = find_regulatory_rule_version(fields["rule_key"], fields["version"])
        versions = get_regulatory_rule_versions(fields["rule_key"])
        prior_active = next((row for row in versions if bool(row.get("fields", {}).get("active"))), None)
        if prior_active and str(prior_active.get("fields", {}).get("version")) != str(fields["version"]):
            fields["supersedes_version"] = str(prior_active.get("fields", {}).get("version", ""))

        if dry_run:
            action = "update" if existing_version else "create"
            items.append({"rule_key": fields["rule_key"], "version": fields["version"], "action": action})
            continue

        if existing_version:
            result = update_regulatory_rule(existing_version.get("id"), fields)
            if result is None:
                errors.append({"index": idx, "error": "failed to update rule"})
                continue
            target_id = existing_version.get("id")
            updated += 1
            action = "updated"
        else:
            result = create_regulatory_rule(fields)
            if not result:
                errors.append({"index": idx, "error": "failed to create rule"})
                continue
            target_id = result.get("id")
            created += 1
            action = "created"

        if deactivate_previous and fields.get("active"):
            for row in versions:
                if str(row.get("id")) == str(target_id):
                    continue
                if bool(row.get("fields", {}).get("active")):
                    update_regulatory_rule(row.get("id"), {"active": False})

        items.append({"rule_key": fields["rule_key"], "version": fields["version"], "action": action, "id": target_id})

    status = "ok" if not errors else ("partial" if items else "error")
    code = 200 if status != "error" else 400
    return jsonify({
        "status": status,
        "ingest_batch_id": ingest_batch_id,
        "dry_run": dry_run,
        "created": created,
        "updated": updated,
        "processed": len(items),
        "errors": errors,
        "items": items,
    }), code


@app.route("/regulatory/ask", methods=["GET"])
def api_regulatory_ask():
    """Answer a regulatory question using ingested rules first, then static fallback."""
    query = str(request.args.get("q", "")).strip()
    if not query:
        return jsonify({"error": "q is required"}), 400
    jurisdiction = request.args.get("jurisdiction")
    dynamic_rules = get_regulatory_rules(jurisdiction=jurisdiction, active_only=True)
    answer = get_regulatory_answer(query, dynamic_rules=dynamic_rules)
    if not answer:
        return jsonify({"status": "no_match", "answer": None}), 404
    return jsonify({"status": "ok", "answer": answer, "dynamic_rule_count": len(dynamic_rules)})


@app.route("/regulatory/audit/risk-summary", methods=["GET"])
def api_regulatory_audit_risk_summary():
    """Compute and return regulatory audit risk snapshot."""
    jurisdiction = request.args.get("jurisdiction")
    snapshot = _compute_regulatory_risk_snapshot(jurisdiction=jurisdiction)
    return jsonify(snapshot)


@app.route("/regulatory/audit/risk-assessments", methods=["GET"])
def api_regulatory_audit_risk_assessments():
    """List persisted regulatory risk assessments."""
    status = request.args.get("status")
    category = request.args.get("category")
    rows = get_regulatory_risk_assessments(status=status, category=category)
    return jsonify({
        "count": len(rows),
        "assessments": [{"id": row.get("id"), "fields": row.get("fields", {})} for row in rows],
    })


@app.route("/regulatory/audit/risk-assessments/run", methods=["POST"])
def api_regulatory_audit_risk_assessment_run():
    """Compute and persist a regulatory risk assessment row."""
    data = request.get_json(force=True, silent=True) or {}
    jurisdiction = data.get("jurisdiction")
    category = str(data.get("category", "overall")).strip()
    status = str(data.get("status", "open")).strip().lower()
    snapshot = _compute_regulatory_risk_snapshot(jurisdiction=jurisdiction)
    fields = {
        "assessed_at": snapshot["assessed_at"],
        "jurisdiction": snapshot["jurisdiction"],
        "category": category,
        "status": status,
        "risk_score": snapshot["risk_score"],
        "risk_level": snapshot["risk_level"],
        "rule_keys": ",".join(sorted({
            str(row.get("fields", {}).get("rule_key", "")).strip()
            for row in get_regulatory_rules(jurisdiction=jurisdiction, active_only=True)
            if str(row.get("fields", {}).get("rule_key", "")).strip()
        })),
        "findings": " | ".join(snapshot["findings"]),
        "recommended_actions": " | ".join(snapshot["recommended_actions"]),
    }
    result = create_regulatory_risk_assessment(fields)
    if not result:
        return jsonify({"error": "failed to persist regulatory risk assessment", "snapshot": snapshot}), 500
    return jsonify({"status": "created", "assessment_id": result.get("id"), "snapshot": snapshot}), 201


@app.route("/ops/workflows/heartbeat", methods=["POST"])
def api_ops_workflow_heartbeat():
    """Record (upsert) workflow run heartbeat keyed by workflow_key."""
    data = request.get_json(force=True, silent=True) or {}
    payload, error = _workflow_heartbeat_payload(data)
    if error or not payload:
        return jsonify({"error": error or "invalid payload"}), 400
    result = upsert_workflow_heartbeat(payload["workflow_key"], payload["fields"])
    if result is None:
        return jsonify({"error": "failed to persist workflow heartbeat"}), 500
    return jsonify({
        "status": "ok",
        "workflow_key": payload["workflow_key"],
        "last_status": payload["fields"].get("last_status"),
        "last_run_at": payload["fields"].get("last_run_at"),
        "last_success_at": payload["fields"].get("last_success_at", ""),
    })


@app.route("/ops/workflows/freshness", methods=["GET"])
def api_ops_workflows_freshness():
    """Return freshness status for critical automated workflows."""
    return jsonify(_compute_workflow_freshness())


@app.route("/marketing/leads", methods=["POST"])
def api_marketing_leads_create():
    """Create a marketing lead row."""
    data = request.get_json(force=True, silent=True) or {}
    status = str(data.get("status", "new")).strip().lower()
    if status not in MARKETING_LEAD_STATUSES:
        return jsonify({"error": "invalid lead status", "allowed_statuses": sorted(MARKETING_LEAD_STATUSES)}), 400
    payload = {
        "family_name": str(data.get("family_name", "")).strip(),
        "email": str(data.get("email", "")).strip(),
        "phone": str(data.get("phone", "")).strip(),
        "child_age_group": str(data.get("child_age_group", "")).strip(),
        "channel": str(data.get("channel", "")).strip().lower(),
        "campaign": str(data.get("campaign", "")).strip(),
        "status": status,
        "inquiry_date": data.get("inquiry_date") or datetime.utcnow().isoformat(timespec="seconds"),
        "notes": str(data.get("notes", "")).strip(),
    }
    result = create_marketing_lead(payload)
    if not result:
        return jsonify({"error": "failed to create marketing lead"}), 500
    return jsonify({"status": "created", "lead_id": result.get("id")}), 201


@app.route("/marketing/leads", methods=["GET"])
def api_marketing_leads_list():
    """List marketing leads with optional channel/status filters."""
    controls, errors = _parse_list_controls(
        allowed_sort_fields={"id", "inquiry_date", "status", "channel", "campaign", "family_name"},
        default_sort_by="inquiry_date",
        default_sort_dir="desc",
    )
    if errors or not controls:
        return _validation_error_response(errors)
    channel = request.args.get("channel")
    status = request.args.get("status")
    leads = get_marketing_leads(channel=channel, status=status)
    rows = [{"id": row.get("id"), "fields": row.get("fields", {})} for row in leads]
    sorted_rows = _sort_records(rows, sort_by=controls["sort_by"], sort_dir=controls["sort_dir"])
    paged = _paginate_records(sorted_rows, limit=controls["limit"], offset=controls["offset"])
    return jsonify({
        "count": len(sorted_rows),
        "limit": controls["limit"],
        "offset": controls["offset"],
        "sort_by": controls["sort_by"],
        "sort_dir": controls["sort_dir"],
        "leads": paged,
    })


@app.route("/marketing/reviews", methods=["POST"])
def api_marketing_reviews_create():
    """Create a parent review request/event row."""
    data = request.get_json(force=True, silent=True) or {}
    platform = str(data.get("platform", "other")).strip().lower()
    status = str(data.get("status", "pending")).strip().lower()
    if platform not in REVIEW_PLATFORMS:
        return jsonify({"error": "invalid review platform", "allowed_platforms": sorted(REVIEW_PLATFORMS)}), 400
    if status not in REVIEW_STATUSES:
        return jsonify({"error": "invalid review status", "allowed_statuses": sorted(REVIEW_STATUSES)}), 400
    payload = {
        "family_name": str(data.get("family_name", "")).strip(),
        "platform": platform,
        "status": status,
        "rating": _to_float(data.get("rating")) if data.get("rating") not in (None, "") else None,
        "requested_at": data.get("requested_at") or datetime.utcnow().isoformat(timespec="seconds"),
        "received_at": data.get("received_at"),
        "review_url": str(data.get("review_url", "")).strip(),
        "notes": str(data.get("notes", "")).strip(),
    }
    result = create_review_request(payload)
    if not result:
        return jsonify({"error": "failed to create review request"}), 500
    return jsonify({"status": "created", "review_request_id": result.get("id")}), 201


@app.route("/marketing/reviews", methods=["GET"])
def api_marketing_reviews_list():
    """List review requests/events with optional platform/status filters."""
    controls, errors = _parse_list_controls(
        allowed_sort_fields={"id", "requested_at", "received_at", "status", "platform", "rating", "family_name"},
        default_sort_by="requested_at",
        default_sort_dir="desc",
    )
    if errors or not controls:
        return _validation_error_response(errors)
    platform = request.args.get("platform")
    status = request.args.get("status")
    rows = get_review_requests(platform=platform, status=status)
    records = [{"id": row.get("id"), "fields": row.get("fields", {})} for row in rows]
    sorted_rows = _sort_records(records, sort_by=controls["sort_by"], sort_dir=controls["sort_dir"])
    paged = _paginate_records(sorted_rows, limit=controls["limit"], offset=controls["offset"])
    return jsonify({
        "count": len(sorted_rows),
        "limit": controls["limit"],
        "offset": controls["offset"],
        "sort_by": controls["sort_by"],
        "sort_dir": controls["sort_dir"],
        "reviews": paged,
    })


@app.route("/marketing/insurance/policies", methods=["POST"])
def api_marketing_insurance_policies_create():
    """Create an insurance policy tracking row."""
    data = request.get_json(force=True, silent=True) or {}
    status = str(data.get("status", "active")).strip().lower()
    if status not in INSURANCE_POLICY_STATUSES:
        return jsonify({"error": "invalid insurance status", "allowed_statuses": sorted(INSURANCE_POLICY_STATUSES)}), 400

    effective_date = _parse_iso_date(data.get("effective_date"))
    expiration_date = _parse_iso_date(data.get("expiration_date"))
    payload = {
        "policy_type": str(data.get("policy_type", "")).strip(),
        "carrier": str(data.get("carrier", "")).strip(),
        "policy_number": str(data.get("policy_number", "")).strip(),
        "coverage_amount": _to_float(data.get("coverage_amount")),
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "status": status,
        "renewal_contact": str(data.get("renewal_contact", "")).strip(),
        "notes": str(data.get("notes", "")).strip(),
    }
    result = create_insurance_policy(payload)
    if not result:
        return jsonify({"error": "failed to create insurance policy"}), 500
    return jsonify({"status": "created", "policy_id": result.get("id")}), 201


@app.route("/marketing/insurance/policies/<policy_id_val>", methods=["PATCH"])
def api_marketing_insurance_policies_patch(policy_id_val):
    """Patch an insurance policy tracking row."""
    data = request.get_json(force=True, silent=True) or {}
    if not isinstance(data, dict) or not data:
        return jsonify({"error": "fields object required"}), 400
    patch = dict(data)
    if "status" in patch:
        patch["status"] = str(patch.get("status", "")).strip().lower()
        if patch["status"] not in INSURANCE_POLICY_STATUSES:
            return jsonify({"error": "invalid insurance status", "allowed_statuses": sorted(INSURANCE_POLICY_STATUSES)}), 400
    if "coverage_amount" in patch:
        patch["coverage_amount"] = _to_float(patch.get("coverage_amount"))
    if "effective_date" in patch:
        parsed = _parse_iso_date(patch.get("effective_date"))
        if patch.get("effective_date") not in (None, "") and not parsed:
            return jsonify({"error": "effective_date must be ISO date (YYYY-MM-DD)"}), 400
        patch["effective_date"] = parsed
    if "expiration_date" in patch:
        parsed = _parse_iso_date(patch.get("expiration_date"))
        if patch.get("expiration_date") not in (None, "") and not parsed:
            return jsonify({"error": "expiration_date must be ISO date (YYYY-MM-DD)"}), 400
        patch["expiration_date"] = parsed
    result = update_insurance_policy(policy_id_val, patch)
    if result is None:
        return jsonify({"error": "failed to update insurance policy"}), 500
    return jsonify({"status": "updated", "policy_id": policy_id_val, "fields": patch})


@app.route("/marketing/insurance/policies", methods=["GET"])
def api_marketing_insurance_policies_list():
    """List insurance policies with optional status filter."""
    controls, errors = _parse_list_controls(
        allowed_sort_fields={"id", "effective_date", "expiration_date", "status", "carrier", "policy_type"},
        default_sort_by="expiration_date",
        default_sort_dir="asc",
    )
    if errors or not controls:
        return _validation_error_response(errors)
    status = request.args.get("status")
    rows = get_insurance_policies(status=status)
    records = [{"id": row.get("id"), "fields": row.get("fields", {})} for row in rows]
    sorted_rows = _sort_records(records, sort_by=controls["sort_by"], sort_dir=controls["sort_dir"])
    paged = _paginate_records(sorted_rows, limit=controls["limit"], offset=controls["offset"])
    return jsonify({
        "count": len(sorted_rows),
        "limit": controls["limit"],
        "offset": controls["offset"],
        "sort_by": controls["sort_by"],
        "sort_dir": controls["sort_dir"],
        "policies": paged,
    })


@app.route("/marketing/competitors/snapshots", methods=["POST"])
def api_marketing_competitor_snapshots_create():
    """Create a competitive positioning snapshot row."""
    data = request.get_json(force=True, silent=True) or {}
    payload = {
        "competitor_name": str(data.get("competitor_name", "")).strip(),
        "location": str(data.get("location", "")).strip(),
        "tuition_band": str(data.get("tuition_band", "")).strip(),
        "capacity_estimate": _to_float(data.get("capacity_estimate")),
        "waitlist_estimate": _to_float(data.get("waitlist_estimate")),
        "source_url": str(data.get("source_url", "")).strip(),
        "captured_at": data.get("captured_at") or datetime.utcnow().isoformat(timespec="seconds"),
        "notes": str(data.get("notes", "")).strip(),
    }
    result = create_competitor_snapshot(payload)
    if not result:
        return jsonify({"error": "failed to create competitor snapshot"}), 500
    return jsonify({"status": "created", "snapshot_id": result.get("id")}), 201


@app.route("/marketing/competitors/snapshots", methods=["GET"])
def api_marketing_competitor_snapshots_list():
    """List competitor snapshots with optional competitor filter."""
    controls, errors = _parse_list_controls(
        allowed_sort_fields={"id", "captured_at", "competitor_name", "location", "waitlist_estimate", "capacity_estimate"},
        default_sort_by="captured_at",
        default_sort_dir="desc",
    )
    if errors or not controls:
        return _validation_error_response(errors)
    competitor_name = request.args.get("competitor_name")
    rows = get_competitor_snapshots(competitor_name=competitor_name)
    records = [{"id": row.get("id"), "fields": row.get("fields", {})} for row in rows]
    sorted_rows = _sort_records(records, sort_by=controls["sort_by"], sort_dir=controls["sort_dir"])
    paged = _paginate_records(sorted_rows, limit=controls["limit"], offset=controls["offset"])
    return jsonify({
        "count": len(sorted_rows),
        "limit": controls["limit"],
        "offset": controls["offset"],
        "sort_by": controls["sort_by"],
        "sort_dir": controls["sort_dir"],
        "snapshots": paged,
    })


@app.route("/marketing/spend", methods=["POST"])
def api_marketing_spend_create():
    """Create a marketing channel spend row used for attribution spend analytics."""
    data = request.get_json(force=True, silent=True) or {}
    channel = str(data.get("channel", "")).strip().lower()
    period_month = str(data.get("period_month", "")).strip()
    if not channel:
        return jsonify({"error": "channel is required"}), 400
    if not re.match(r"^\d{4}-\d{2}$", period_month):
        return jsonify({"error": "period_month must be YYYY-MM"}), 400
    spend_amount = _to_float(data.get("spend_amount"))
    if spend_amount < 0:
        return jsonify({"error": "spend_amount must be >= 0"}), 400

    payload = {
        "channel": channel,
        "campaign": str(data.get("campaign", "")).strip().lower(),
        "period_month": period_month,
        "spend_amount": spend_amount,
        "currency": str(data.get("currency", "USD")).strip().upper() or "USD",
        "clicks": int(_to_float(data.get("clicks"))) if data.get("clicks") not in (None, "") else None,
        "impressions": int(_to_float(data.get("impressions"))) if data.get("impressions") not in (None, "") else None,
        "notes": str(data.get("notes", "")).strip(),
    }
    result = create_marketing_channel_spend(payload)
    if not result:
        return jsonify({"error": "failed to create marketing spend"}), 500
    return jsonify({"status": "created", "spend_id": result.get("id")}), 201


@app.route("/marketing/attribution/spend-summary", methods=["GET"])
def api_marketing_attribution_spend_summary():
    """Return channel/campaign spend efficiency metrics (CPL/CPA)."""
    period_month = request.args.get("period_month")
    channel_filter = request.args.get("channel")
    campaign_filter = request.args.get("campaign")

    spend_rows = get_marketing_channel_spend(
        channel=channel_filter,
        campaign=campaign_filter,
        period_month=period_month,
    )
    leads = get_marketing_leads(channel=channel_filter, status=None)

    leads_by_key: dict[tuple[str, str], dict[str, int]] = {}
    for row in leads:
        fields = row.get("fields", {})
        inquiry = str(fields.get("inquiry_date", "")).strip()
        month = inquiry[:7] if len(inquiry) >= 7 and inquiry[4] == "-" else ""
        if period_month and month != period_month:
            continue
        channel = str(fields.get("channel", "unknown")).strip().lower() or "unknown"
        campaign = str(fields.get("campaign", "")).strip().lower()
        if campaign_filter and campaign != str(campaign_filter).strip().lower():
            continue
        key = (channel, campaign)
        bucket = leads_by_key.setdefault(key, {"lead_count": 0, "converted_count": 0})
        bucket["lead_count"] += 1
        if str(fields.get("status", "")).strip().lower() == "converted":
            bucket["converted_count"] += 1

    results: list[dict[str, Any]] = []
    total_spend = 0.0
    total_leads = 0
    total_converted = 0
    for row in spend_rows:
        fields = row.get("fields", {})
        channel = str(fields.get("channel", "unknown")).strip().lower() or "unknown"
        campaign = str(fields.get("campaign", "")).strip().lower()
        key = (channel, campaign)
        lead_count = leads_by_key.get(key, {}).get("lead_count", 0)
        converted_count = leads_by_key.get(key, {}).get("converted_count", 0)
        spend_amount = _to_float(fields.get("spend_amount"))
        cpl = round(spend_amount / lead_count, 2) if lead_count > 0 else None
        cpa = round(spend_amount / converted_count, 2) if converted_count > 0 else None
        result = {
            "channel": channel,
            "campaign": campaign,
            "period_month": str(fields.get("period_month", "")),
            "spend_amount": spend_amount,
            "currency": str(fields.get("currency", "USD") or "USD"),
            "lead_count": lead_count,
            "converted_count": converted_count,
            "cpl": cpl,
            "cpa": cpa,
            "clicks": int(_to_float(fields.get("clicks"))) if fields.get("clicks") not in (None, "") else None,
            "impressions": int(_to_float(fields.get("impressions"))) if fields.get("impressions") not in (None, "") else None,
        }
        results.append(result)
        total_spend += spend_amount
        total_leads += lead_count
        total_converted += converted_count

    return jsonify({
        "count": len(results),
        "period_month": period_month,
        "items": sorted(results, key=lambda x: x["spend_amount"], reverse=True),
        "totals": {
            "spend_amount": round(total_spend, 2),
            "lead_count": total_leads,
            "converted_count": total_converted,
            "blended_cpl": round(total_spend / total_leads, 2) if total_leads > 0 else None,
            "blended_cpa": round(total_spend / total_converted, 2) if total_converted > 0 else None,
        },
    })


@app.route("/marketing/attribution/spend-trend", methods=["GET"])
def api_marketing_attribution_spend_trend():
    """Return monthly blended CPL/CPA trend with month-over-month deltas."""
    channel_filter = request.args.get("channel")
    campaign_filter = request.args.get("campaign")
    spend_rows = get_marketing_channel_spend(channel=channel_filter, campaign=campaign_filter, period_month=None)
    leads = get_marketing_leads(channel=channel_filter, status=None)

    leads_monthly: dict[str, dict[str, int]] = {}
    for row in leads:
        fields = row.get("fields", {})
        inquiry = str(fields.get("inquiry_date", "")).strip()
        month = inquiry[:7] if len(inquiry) >= 7 and inquiry[4] == "-" else ""
        if not month:
            continue
        campaign = str(fields.get("campaign", "")).strip().lower()
        if campaign_filter and campaign != str(campaign_filter).strip().lower():
            continue
        bucket = leads_monthly.setdefault(month, {"lead_count": 0, "converted_count": 0})
        bucket["lead_count"] += 1
        if str(fields.get("status", "")).strip().lower() == "converted":
            bucket["converted_count"] += 1

    spend_monthly: dict[str, float] = {}
    for row in spend_rows:
        fields = row.get("fields", {})
        month = str(fields.get("period_month", "")).strip()
        if not re.match(r"^\d{4}-\d{2}$", month):
            continue
        spend_monthly[month] = spend_monthly.get(month, 0.0) + _to_float(fields.get("spend_amount"))

    months = sorted(set(spend_monthly.keys()) | set(leads_monthly.keys()))
    trend: list[dict[str, Any]] = []
    prev_cpl: float | None = None
    prev_cpa: float | None = None
    for month in months:
        spend_amount = round(spend_monthly.get(month, 0.0), 2)
        lead_count = int(leads_monthly.get(month, {}).get("lead_count", 0))
        converted_count = int(leads_monthly.get(month, {}).get("converted_count", 0))
        cpl = round(spend_amount / lead_count, 2) if lead_count > 0 else None
        cpa = round(spend_amount / converted_count, 2) if converted_count > 0 else None
        trend.append({
            "period_month": month,
            "spend_amount": spend_amount,
            "lead_count": lead_count,
            "converted_count": converted_count,
            "blended_cpl": cpl,
            "blended_cpa": cpa,
            "mom_cpl_change": (round(cpl - prev_cpl, 2) if cpl is not None and prev_cpl is not None else None),
            "mom_cpa_change": (round(cpa - prev_cpa, 2) if cpa is not None and prev_cpa is not None else None),
        })
        if cpl is not None:
            prev_cpl = cpl
        if cpa is not None:
            prev_cpa = cpa

    return jsonify({"count": len(trend), "items": trend})


@app.route("/marketing/attribution/touchpoints", methods=["POST"])
def api_marketing_attribution_touchpoints_create():
    """Create attribution touchpoint events tied to a marketing lead."""
    data = request.get_json(force=True, silent=True) or {}
    lead_id = data.get("lead_id")
    channel = str(data.get("channel", "")).strip().lower()
    occurred_at = str(data.get("occurred_at", "")).strip()
    if lead_id in (None, ""):
        return jsonify({"error": "lead_id is required"}), 400
    if not channel:
        return jsonify({"error": "channel is required"}), 400
    if not occurred_at:
        return jsonify({"error": "occurred_at is required"}), 400
    if _parse_iso_datetime(occurred_at) is None:
        return jsonify({"error": "occurred_at must be ISO datetime"}), 400

    payload = {
        "lead_id": _to_grist_id(lead_id),
        "channel": channel,
        "campaign": str(data.get("campaign", "")).strip().lower(),
        "touch_type": str(data.get("touch_type", "unknown")).strip().lower(),
        "occurred_at": occurred_at,
        "utm_source": str(data.get("utm_source", "")).strip().lower(),
        "utm_medium": str(data.get("utm_medium", "")).strip().lower(),
        "utm_campaign": str(data.get("utm_campaign", "")).strip().lower(),
        "notes": str(data.get("notes", "")).strip(),
    }
    result = create_marketing_touchpoint(payload)
    if not result:
        return jsonify({"error": "failed to create marketing touchpoint"}), 500
    return jsonify({"status": "created", "touchpoint_id": result.get("id")}), 201


@app.route("/marketing/attribution/weights", methods=["GET"])
def api_marketing_attribution_weights_get():
    """Return current position-based attribution weights."""
    return jsonify({
        "first_touch": ATTRIBUTION_WEIGHTS["first_touch"],
        "middle_touch_total": ATTRIBUTION_WEIGHTS["middle_touch_total"],
        "last_touch": ATTRIBUTION_WEIGHTS["last_touch"],
        "sum": round(
            ATTRIBUTION_WEIGHTS["first_touch"]
            + ATTRIBUTION_WEIGHTS["middle_touch_total"]
            + ATTRIBUTION_WEIGHTS["last_touch"],
            6,
        ),
    })


@app.route("/marketing/attribution/weights", methods=["POST"])
def api_marketing_attribution_weights_set():
    """Set position-based attribution weights at runtime."""
    data = request.get_json(force=True, silent=True) or {}
    first = _to_float(data.get("first_touch"))
    middle = _to_float(data.get("middle_touch_total"))
    last = _to_float(data.get("last_touch"))
    if first < 0 or middle < 0 or last < 0:
        return jsonify({"error": "weights must be >= 0"}), 400
    total = round(first + middle + last, 6)
    if abs(total - 1.0) > 0.0001:
        return jsonify({"error": "weights must sum to 1.0", "sum": total}), 400
    ATTRIBUTION_WEIGHTS["first_touch"] = first
    ATTRIBUTION_WEIGHTS["middle_touch_total"] = middle
    ATTRIBUTION_WEIGHTS["last_touch"] = last
    return jsonify({
        "status": "updated",
        "first_touch": ATTRIBUTION_WEIGHTS["first_touch"],
        "middle_touch_total": ATTRIBUTION_WEIGHTS["middle_touch_total"],
        "last_touch": ATTRIBUTION_WEIGHTS["last_touch"],
        "sum": round(first + middle + last, 6),
    })


@app.route("/marketing/attribution/multi-touch", methods=["GET"])
def api_marketing_attribution_multi_touch():
    """Return weighted attribution by channel using first/last/position-based models."""
    period_month = str(request.args.get("period_month", "")).strip()
    model = str(request.args.get("model", "position_based")).strip().lower()
    if period_month and not re.match(r"^\d{4}-\d{2}$", period_month):
        return jsonify({"error": "period_month must be YYYY-MM"}), 400
    if model not in {"first_touch", "last_touch", "position_based"}:
        return jsonify({"error": "model must be one of first_touch,last_touch,position_based"}), 400

    leads = get_marketing_leads()
    touchpoints = get_marketing_touchpoints()
    spend_rows = get_marketing_channel_spend(period_month=period_month or None)

    spend_by_channel: dict[str, float] = {}
    for row in spend_rows:
        fields = row.get("fields", {})
        channel = str(fields.get("channel", "unknown")).strip().lower() or "unknown"
        spend_by_channel[channel] = spend_by_channel.get(channel, 0.0) + _to_float(fields.get("spend_amount"))

    lead_by_id = {str(row.get("id")): row for row in leads}
    converted_leads: list[str] = []
    for row in leads:
        fields = row.get("fields", {})
        if str(fields.get("status", "")).strip().lower() != "converted":
            continue
        inquiry = str(fields.get("inquiry_date", "")).strip()
        month = inquiry[:7] if len(inquiry) >= 7 and inquiry[4] == "-" else ""
        if period_month and month != period_month:
            continue
        converted_leads.append(str(row.get("id")))

    tps_by_lead: dict[str, list[dict[str, Any]]] = {}
    for tp in touchpoints:
        fields = tp.get("fields", {})
        lid = str(fields.get("lead_id", "")).strip()
        if not lid:
            continue
        tps_by_lead.setdefault(lid, []).append(tp)

    channel_weights: dict[str, float] = {}
    total_attributed_conversions = 0.0

    for lid in converted_leads:
        lead = lead_by_id.get(lid, {})
        lead_fields = lead.get("fields", {})
        fallback_channel = str(lead_fields.get("channel", "unknown")).strip().lower() or "unknown"
        lead_tps = sorted(
            tps_by_lead.get(lid, []),
            key=lambda x: str(x.get("fields", {}).get("occurred_at", "")),
        )
        if not lead_tps:
            channel_weights[fallback_channel] = channel_weights.get(fallback_channel, 0.0) + 1.0
            total_attributed_conversions += 1.0
            continue

        channels = [str(tp.get("fields", {}).get("channel", fallback_channel)).strip().lower() or fallback_channel for tp in lead_tps]
        if model == "first_touch":
            alloc = {channels[0]: 1.0}
        elif model == "last_touch":
            alloc = {channels[-1]: 1.0}
        else:
            alloc: dict[str, float] = {}
            if len(channels) == 1:
                alloc[channels[0]] = 1.0
            elif len(channels) == 2:
                # No middle touches; split middle share evenly across first/last.
                first_share = ATTRIBUTION_WEIGHTS["first_touch"] + (ATTRIBUTION_WEIGHTS["middle_touch_total"] / 2.0)
                last_share = ATTRIBUTION_WEIGHTS["last_touch"] + (ATTRIBUTION_WEIGHTS["middle_touch_total"] / 2.0)
                alloc[channels[0]] = first_share
                alloc[channels[1]] = alloc.get(channels[1], 0.0) + last_share
            else:
                first = channels[0]
                last = channels[-1]
                alloc[first] = ATTRIBUTION_WEIGHTS["first_touch"]
                alloc[last] = alloc.get(last, 0.0) + ATTRIBUTION_WEIGHTS["last_touch"]
                middle = channels[1:-1]
                share = ATTRIBUTION_WEIGHTS["middle_touch_total"] / len(middle)
                for ch in middle:
                    alloc[ch] = alloc.get(ch, 0.0) + share

        for ch, weight in alloc.items():
            channel_weights[ch] = channel_weights.get(ch, 0.0) + weight
            total_attributed_conversions += weight

    results = []
    for ch, conversions in channel_weights.items():
        spend = round(spend_by_channel.get(ch, 0.0), 2)
        weighted_cpa = round(spend / conversions, 2) if conversions > 0 else None
        results.append({
            "channel": ch,
            "weighted_conversions": round(conversions, 4),
            "spend_amount": spend,
            "weighted_cpa": weighted_cpa,
        })
    results = sorted(results, key=lambda x: x["weighted_conversions"], reverse=True)

    prior_month = ""
    if period_month and re.match(r"^\d{4}-\d{2}$", period_month):
        y, m = period_month.split("-")
        yi = int(y)
        mi = int(m) - 1
        if mi == 0:
            yi -= 1
            mi = 12
        prior_month = f"{yi:04d}-{mi:02d}"

    prior_weighted_cpa = None
    current_weighted_cpa = None
    if period_month:
        current_spend_total = sum(_to_float(r.get("fields", {}).get("spend_amount")) for r in spend_rows)
        current_converted = len(converted_leads)
        current_weighted_cpa = round(current_spend_total / current_converted, 2) if current_converted > 0 else None
    if prior_month:
        prior_spend = get_marketing_channel_spend(period_month=prior_month)
        prior_spend_total = sum(_to_float(r.get("fields", {}).get("spend_amount")) for r in prior_spend)
        prior_converted = 0
        for row in leads:
            f = row.get("fields", {})
            if str(f.get("status", "")).strip().lower() != "converted":
                continue
            inquiry = str(f.get("inquiry_date", "")).strip()
            if len(inquiry) >= 7 and inquiry[:7] == prior_month:
                prior_converted += 1
        prior_weighted_cpa = round(prior_spend_total / prior_converted, 2) if prior_converted > 0 else None

    cpa_delta = None
    if current_weighted_cpa is not None and prior_weighted_cpa is not None:
        cpa_delta = round(float(current_weighted_cpa) - float(prior_weighted_cpa), 2)

    return jsonify({
        "period_month": period_month or None,
        "model": model,
        "count": len(results),
        "items": results,
        "totals": {
            "weighted_conversions": round(total_attributed_conversions, 4),
            "weighted_cpa": current_weighted_cpa,
            "prior_month": prior_month or None,
            "prior_weighted_cpa": prior_weighted_cpa,
            "weighted_cpa_change_vs_prior_month": cpa_delta,
        },
    })


@app.route("/marketing/dashboard", methods=["GET"])
def api_marketing_dashboard():
    """Return consolidated marketing/reviews/insurance/competitive dashboard summary."""
    leads = get_marketing_leads()
    reviews = get_review_requests()
    policies = get_insurance_policies()
    competitors = get_competitor_snapshots()

    lead_status_counts: dict[str, int] = {}
    lead_channel_counts: dict[str, int] = {}
    for row in leads:
        fields = row.get("fields", {})
        status = str(fields.get("status", "unknown")).strip().lower()
        channel = str(fields.get("channel", "unknown")).strip().lower()
        lead_status_counts[status] = lead_status_counts.get(status, 0) + 1
        lead_channel_counts[channel] = lead_channel_counts.get(channel, 0) + 1

    review_status_counts: dict[str, int] = {}
    ratings = []
    for row in reviews:
        fields = row.get("fields", {})
        status = str(fields.get("status", "unknown")).strip().lower()
        review_status_counts[status] = review_status_counts.get(status, 0) + 1
        rating = _to_float(fields.get("rating"))
        if rating > 0:
            ratings.append(rating)

    insurance_status_counts: dict[str, int] = {}
    expiring_soon = 0
    now = datetime.utcnow()
    for row in policies:
        fields = row.get("fields", {})
        status = str(fields.get("status", "unknown")).strip().lower()
        insurance_status_counts[status] = insurance_status_counts.get(status, 0) + 1
        expiration = _parse_iso_datetime(fields.get("expiration_date"))
        if expiration and 0 <= (expiration - now).days <= 45:
            expiring_soon += 1

    return jsonify({
        "leads": {
            "count": len(leads),
            "status_counts": lead_status_counts,
            "channel_counts": lead_channel_counts,
        },
        "reviews": {
            "count": len(reviews),
            "status_counts": review_status_counts,
            "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        },
        "insurance": {
            "count": len(policies),
            "status_counts": insurance_status_counts,
            "expiring_within_45_days": expiring_soon,
        },
        "competitive": {
            "snapshot_count": len(competitors),
            "latest_captured_at": max(
                [str(row.get("fields", {}).get("captured_at", "")) for row in competitors if row.get("fields", {}).get("captured_at")],
                default="",
            ),
        },
    })


@app.route("/marketing/attribution/summary", methods=["GET"])
def api_marketing_attribution_summary():
    """Return channel/campaign attribution summary from lead + review lifecycle data."""
    leads = get_marketing_leads()
    reviews = get_review_requests()

    channel_summary: dict[str, dict[str, Any]] = {}
    campaign_summary: dict[str, dict[str, Any]] = {}
    family_to_channel: dict[str, str] = {}

    for row in leads:
        fields = row.get("fields", {})
        channel = str(fields.get("channel", "unknown")).strip().lower() or "unknown"
        campaign = str(fields.get("campaign", "uncategorized")).strip().lower() or "uncategorized"
        status = str(fields.get("status", "unknown")).strip().lower()
        family = str(fields.get("family_name", "")).strip().lower()

        if family:
            family_to_channel[family] = channel

        chan_bucket = channel_summary.setdefault(channel, {
            "lead_count": 0,
            "converted_count": 0,
            "lost_count": 0,
        })
        chan_bucket["lead_count"] += 1
        if status == "converted":
            chan_bucket["converted_count"] += 1
        if status == "lost":
            chan_bucket["lost_count"] += 1

        camp_bucket = campaign_summary.setdefault(campaign, {
            "lead_count": 0,
            "converted_count": 0,
        })
        camp_bucket["lead_count"] += 1
        if status == "converted":
            camp_bucket["converted_count"] += 1

    review_received_by_channel: dict[str, int] = {}
    rating_totals: dict[str, float] = {}
    rating_counts: dict[str, int] = {}
    for row in reviews:
        fields = row.get("fields", {})
        if str(fields.get("status", "")).strip().lower() != "received":
            continue
        family = str(fields.get("family_name", "")).strip().lower()
        channel = family_to_channel.get(family, "unknown")
        review_received_by_channel[channel] = review_received_by_channel.get(channel, 0) + 1
        rating = _to_float(fields.get("rating"))
        if rating > 0:
            rating_totals[channel] = rating_totals.get(channel, 0.0) + rating
            rating_counts[channel] = rating_counts.get(channel, 0) + 1

    for channel, bucket in channel_summary.items():
        leads_total = bucket["lead_count"]
        converted = bucket["converted_count"]
        lost = bucket["lost_count"]
        reviews_received = review_received_by_channel.get(channel, 0)
        bucket["conversion_rate"] = round((converted / leads_total), 4) if leads_total else 0.0
        bucket["loss_rate"] = round((lost / leads_total), 4) if leads_total else 0.0
        bucket["reviews_received_count"] = reviews_received
        bucket["review_per_lead_rate"] = round((reviews_received / leads_total), 4) if leads_total else 0.0
        if rating_counts.get(channel, 0) > 0:
            bucket["average_review_rating"] = round(rating_totals[channel] / rating_counts[channel], 2)
        else:
            bucket["average_review_rating"] = None

    for campaign, bucket in campaign_summary.items():
        leads_total = bucket["lead_count"]
        converted = bucket["converted_count"]
        bucket["conversion_rate"] = round((converted / leads_total), 4) if leads_total else 0.0

    ranked_channels = sorted(
        [{"channel": ch, **vals} for ch, vals in channel_summary.items()],
        key=lambda item: (item["conversion_rate"], item["lead_count"]),
        reverse=True,
    )
    ranked_campaigns = sorted(
        [{"campaign": camp, **vals} for camp, vals in campaign_summary.items()],
        key=lambda item: (item["conversion_rate"], item["lead_count"]),
        reverse=True,
    )

    return jsonify({
        "lead_count": len(leads),
        "review_count": len(reviews),
        "channels": ranked_channels,
        "campaigns": ranked_campaigns,
    })


@app.route("/marketing/seo/summary", methods=["GET"])
def api_marketing_seo_summary():
    """Return SEO-style weekly/monthly trend signals from marketing lead + review data."""
    leads = get_marketing_leads()
    reviews = get_review_requests()

    monthly_leads: dict[str, int] = {}
    monthly_reviews_received: dict[str, int] = {}
    channel_mix: dict[str, int] = {}
    campaign_performance: dict[str, dict[str, Any]] = {}

    def _month_bucket(raw: Any) -> str:
        txt = str(raw or "").strip()
        if len(txt) >= 7 and txt[4] == "-":
            return txt[:7]
        parsed = _parse_iso_datetime(txt)
        if parsed:
            return parsed.strftime("%Y-%m")
        return "unknown"

    for row in leads:
        fields = row.get("fields", {})
        month = _month_bucket(fields.get("inquiry_date"))
        monthly_leads[month] = monthly_leads.get(month, 0) + 1

        channel = str(fields.get("channel", "unknown")).strip().lower() or "unknown"
        campaign = str(fields.get("campaign", "uncategorized")).strip().lower() or "uncategorized"
        status = str(fields.get("status", "")).strip().lower()
        channel_mix[channel] = channel_mix.get(channel, 0) + 1

        camp = campaign_performance.setdefault(campaign, {"lead_count": 0, "converted_count": 0})
        camp["lead_count"] += 1
        if status == "converted":
            camp["converted_count"] += 1

    for row in reviews:
        fields = row.get("fields", {})
        if str(fields.get("status", "")).strip().lower() != "received":
            continue
        month = _month_bucket(fields.get("received_at") or fields.get("requested_at"))
        monthly_reviews_received[month] = monthly_reviews_received.get(month, 0) + 1

    for campaign, bucket in campaign_performance.items():
        leads_total = int(bucket.get("lead_count", 0))
        converted = int(bucket.get("converted_count", 0))
        bucket["conversion_rate"] = round((converted / leads_total), 4) if leads_total else 0.0

    def _trend_series(data: dict[str, int]) -> list[dict[str, Any]]:
        keys = sorted([k for k in data.keys() if k != "unknown"])
        if "unknown" in data:
            keys.append("unknown")
        return [{"month": key, "count": data.get(key, 0)} for key in keys]

    channel_mix_ranked = sorted(
        [{"channel": channel, "lead_count": count} for channel, count in channel_mix.items()],
        key=lambda item: item["lead_count"],
        reverse=True,
    )
    campaigns_ranked = sorted(
        [{"campaign": campaign, **values} for campaign, values in campaign_performance.items()],
        key=lambda item: (item["conversion_rate"], item["lead_count"]),
        reverse=True,
    )

    return jsonify({
        "lead_count": len(leads),
        "review_count": len(reviews),
        "lead_trend_by_month": _trend_series(monthly_leads),
        "received_review_trend_by_month": _trend_series(monthly_reviews_received),
        "channel_mix": channel_mix_ranked,
        "campaign_performance": campaigns_ranked,
    })


# --- Telegram bot ---
TELEGRAM_AVAILABLE = False
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
    TELEGRAM_AVAILABLE = True
except ImportError:
    logger.error("python-telegram-bot not installed")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "placeholder")

# --- Staff access control ---
# Comma-separated Telegram chat IDs of staff members.
# Only these users may run operational commands (checkin, observe, announce, etc.).
_staff_ids_raw = os.getenv("STAFF_CHAT_IDS", "")
STAFF_CHAT_IDS: set[int] = set()
for _cid in _staff_ids_raw.split(","):
    _cid = _cid.strip()
    if _cid:
        try:
            STAFF_CHAT_IDS.add(int(_cid))
        except ValueError:
            logger.warning("Invalid STAFF_CHAT_IDS entry: %s", _cid)

if not STAFF_CHAT_IDS:
    if INSECURE_DEMO_MODE:
        logger.warning("STAFF_CHAT_IDS is empty — allowing all users for staff commands (INSECURE_DEMO_MODE)")
    else:
        logger.error("STAFF_CHAT_IDS is empty — staff commands are disabled until configured")


def _is_staff(chat_id: int) -> bool:
    """Return True if *chat_id* is in the staff whitelist."""
    if not STAFF_CHAT_IDS:
        return INSECURE_DEMO_MODE
    return chat_id in STAFF_CHAT_IDS


def _actor_id(update: Update) -> int:
    """Return stable actor identity (user id when available, else chat id)."""
    if update.effective_user and update.effective_user.id is not None:
        return int(update.effective_user.id)
    return int(update.effective_chat.id)


def _chat_id(update: Update) -> int:
    """Return chat id for the current update."""
    return int(update.effective_chat.id)


def _is_private_chat(update: Update) -> bool:
    """Return True when command is sent in a direct bot chat."""
    return bool(update.effective_chat and update.effective_chat.type == "private")


async def _require_private_chat(update: Update, command_name: str) -> bool:
    """Deny sensitive commands in groups/channels to avoid accidental data exposure."""
    if _is_private_chat(update):
        return True
    if update.message:
        await update.message.reply_text(
            f"⛔ {command_name} is only available in a private chat with this bot."
        )
    elif update.callback_query:
        await update.callback_query.answer(
            "This action is only available in a private chat with this bot.",
            show_alert=True,
        )
    return False


async def _require_staff(update: Update) -> bool:
    """Check that the sender is staff. Replies with an error and returns False if not."""
    actor_id = _actor_id(update)
    if not _is_staff(actor_id):
        logger.warning("Non-staff actor %s attempted restricted command", actor_id)
        if update.message:
            await update.message.reply_text("⛔ This command is for staff only.")
        return False
    return True


def _linked_children_for_chat(primary_id: int, fallback_chat_id: int | None = None) -> list[dict]:
    """Return children linked to a parent Telegram chat_id."""
    children = get_children()
    valid_ids = {str(primary_id)}
    if fallback_chat_id is not None:
        valid_ids.add(str(fallback_chat_id))
    return [
        child for child in children
        if str(child.get("fields", {}).get("parent_chat_id", "")).strip() in valid_ids
    ]


async def _require_child_access(update: Update, child: dict) -> bool:
    """Allow staff, or the parent account linked to the child."""
    actor_id = _actor_id(update)
    chat_id = _chat_id(update)
    if _is_staff(actor_id):
        return True
    linked_chat = str(child.get("fields", {}).get("parent_chat_id", "")).strip()
    if linked_chat and linked_chat in {str(actor_id), str(chat_id)}:
        return True
    if update.message:
        await update.message.reply_text(
            "⛔ You can only access records for your linked child. "
            "Use `/link <first> <last>` or contact the office manager.",
            parse_mode="Markdown",
        )
    elif update.callback_query:
        await update.callback_query.answer(
            "You can only access records for your linked child.",
            show_alert=True,
        )
    return False


# Store parent chat_ids for n8n notifications
PARENT_CHAT_IDS: dict[str, str] = {}

def send_telegram_msg(chat_id: int, text: str) -> bool:
    """Send a Telegram message via the Bot API (synchronous, for Flask/webhook contexts)."""
    if not TOKEN or TOKEN == "placeholder":
        logger.warning("No valid bot token — cannot send Telegram message")
        return False
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
        return False

def fmt_report(child_rec: dict, report: dict) -> str:
    """Format a daily report as a Markdown message for Telegram."""
    c = child_rec["fields"]
    emoji_map = {"Happy": "😊", "Energetic": "⚡", "Calm": "😌", "Focused": "🧠",
                 "Confident": "💪", "Settled": "🏠", "Quiet": "🤫"}
    mood_emoji = emoji_map.get(report.get("mood", ""), "📝")
    lines = [
        f"📋 *Daily Report — {c['first_name']} {c['last_name']}*",
        f"Age: {c['age']} | {report.get('date', 'Today')}",
        "",
        f"🍽 *Meals*",
        f"• Breakfast: {report.get('breakfast', 'N/A')}",
        f"• Lunch: {report.get('lunch', 'N/A')}",
        f"• Snack: {report.get('snack', 'N/A')}",
        "",
        f"😴 *Nap*: {report.get('nap_start', 'N/A')} – {report.get('nap_end', 'N/A')}",
        f"{mood_emoji} *Mood*: {report.get('mood', 'N/A')}",
        f"🎨 *Activities*: {report.get('activities_summary', 'N/A')}",
    ]
    if report.get("milestone_notes"):
        lines.extend(["", f"🌟 *Milestone*: {report['milestone_notes']}"])
    return "\n".join(lines)

def fmt_milestones(child_rec: dict, milestones: list) -> str:
    """Format a child's recent milestones as a Markdown message for Telegram."""
    if not milestones:
        return "No milestones recorded yet."
    c = child_rec["fields"]
    lines = [f"🌟 *{c['first_name']}'s Recent Milestones*", ""]
    cat_emoji = {"Physical": "🏃", "Cognitive": "🧠", "Language": "🗣", "Social-Emotional": "💕"}
    for m in milestones:
        f = m["fields"]
        emoji = cat_emoji.get(f.get("category", ""), "📌")
        lines.append(f"{emoji} *{f.get('category', 'General')}* — {f.get('date', '')}")
        lines.append(f"   {f.get('description', '')}")
        if f.get("tags"):
            lines.append(f"   Tags: {f.get('tags')}")
        lines.append("")
    return "\n".join(lines)

def fmt_activities(activities: list) -> str:
    """Format today's activity schedule as a Markdown message for Telegram."""
    if not activities:
        return "No activities scheduled for today."
    lines = ["📅 *Today's Schedule*", ""]
    for a in activities:
        f = a["fields"]
        lines.append(f"🕐 {f.get('start_time','')}–{f.get('end_time','')}  *{f.get('title','')}*")
        if f.get("location"):
            lines.append(f"   📍 {f.get('location')}")
    return "\n".join(lines)

def build_child_keyboard(children: list) -> InlineKeyboardMarkup:
    """Build an inline keyboard with one button per child for disambiguation."""
    buttons = []
    for c in children:
        f = c["fields"]
        label = f"{f['first_name']} {f['last_name']} ({f['age']})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"child_{c['id']}")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start — register the user's chat ID and show a welcome message."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    PARENT_CHAT_IDS[str(chat_id)] = user.full_name
    logger.info("New user: %s (chat_id=%s)", user.full_name, chat_id)
    await update.message.reply_text(
        f"👋 Welcome to *Sunshine Sprouts Early Learning Center*!\n\n"
        f"Your chat ID ({chat_id}) has been registered for daily reports.\n\n"
        f"Type /help to see available commands.",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help — show all available commands."""
    text = (
        "*Available Commands*\n\n"
        "*Daily Operations*\n"
        "📋 /report `<child>` — Daily report (meals, naps, activities)\n"
        "🌟 /milestones `<child>` — Recent developmental milestones\n"
        "📅 /activity — Today's schedule\n"
        "✅ /checkin `<child>` — Record arrival (staff)\n"
        "🚪 /checkout `<child>` — Record departure (staff)\n"
        "📝 /observe `<child>` `<note>` — Log AI-tagged observation (staff)\n\n"
        "*AI Agents*\n"
        "👥 /staffing — Today's staff coverage & ratio alerts\n"
        "📞 /callout `<room>` — Find available substitutes for call-outs\n"
        "👤 /substitutes `[room]` — View contingency teacher roster (staff)\n"
        "➕ /addsub `<name> | <phone> | ...` — Add a substitute teacher (staff)\n"
        "💰 /subsidies — Subsidy status & reauthorization deadlines\n"
        "📈 /forecast — Enrollment trends & revenue projections\n"
        "🏥 /health — Cross-room allergies, vaccine & incident dashboard\n"
        "💉 /vaccines `<child>` — Health record (vaccines, allergies, doctors)\n\n"
        "*Portfolio & Memories*\n"
        "📚 /portfolio `<child>` — View child's milestone moments (photos, videos, audio)\n"
        "📌 /moment `<child>` `<type>` `<title> — <desc>` — Add a portfolio moment (staff)\n"
        "📖 /book `<child>` `[month]` — Monthly milestone book (omit child for all)\n\n"
        "*Calendar & Meetings*\n"
        "📅 /schedule `staff <date> <time> <title> — <desc>` — Schedule a staff meeting\n"
        "👨‍👩‍👧 /schedule `parent <child> <date> <time> <title> — <desc>` — Schedule parent-teacher\n"
        "📋 /meetings `[date]` — View upcoming meetings\n\n"
        "*Message Board*\n"
        "📢 /announce `<title> — <message>` — Broadcast announcement to all parents\n"
        "📋 /announcements — View recent announcements\n\n"
        "*Kitchen & Daily Menu*\n"
        "🍽 /menu `[date]` — View the full daily menu & parent comments\n"
        "📝 /logmenu `<date> <meal_type> <description>` — Log a menu item (staff)\n"
        "💬 /menucomment `[date] <text>` — Leave feedback on the daily menu (parents)\n\n"
        "*Daily Schedule*\n"
        "📅 /scheduletoday `[date]` — View the daily routine (nap, outdoor, class, craft)\n"
        "🕐 /setschedule `<date> <type> <start> <end> <desc>` — Set an activity block (staff)\n\n"
        "*Other*\n"
        "🔗 /link `<first> <last>` — Link your Telegram to your child (parents)\n"
        "🤖 /ask `<question>` — Ask about policies or curriculum\n"
        "❓ /help — Show this message\n\n"
        "*Children:* Emma, Liam, Sophia, Noah, Ava, Oliver, Isabella, Ethan"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report <child> — show today's daily report."""
    chat_id = update.effective_chat.id
    if not context.args:
        if _is_staff(chat_id):
            children = get_children()
            await update.message.reply_text("Which child?", reply_markup=build_child_keyboard(children))
            return
        linked = _linked_children_for_chat(chat_id)
        if not linked:
            await update.message.reply_text(
                "Usage: `/report <child>`\n"
                "You must link your account first with `/link <first> <last>`.",
                parse_mode="Markdown",
            )
            return
        names = ", ".join(f"{c['fields'].get('first_name', '')} {c['fields'].get('last_name', '')}".strip() for c in linked)
        await update.message.reply_text(
            f"Usage: `/report <child>`\nYour linked child records: {names}",
            parse_mode="Markdown",
        )
        return
    child_name = context.args[0]
    child = find_child(child_name)
    if not child:
        await update.message.reply_text(f"❌ Child '{child_name}' not found. Try: Emma, Liam, Sophia, Noah, Ava, Oliver, Isabella, Ethan")
        return
    if not await _require_child_access(update, child):
        return
    today = datetime.now().strftime("%Y-%m-%d")
    report = get_daily_report(child_id(child), today)
    if not report:
        await update.message.reply_text(f"📋 No report for {child['fields']['first_name']} yet today.")
        return
    await update.message.reply_text(fmt_report(child, report), parse_mode="Markdown")

async def milestones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /milestones <child> — show recent developmental milestones."""
    if not await _require_private_chat(update, "/milestones"):
        return
    actor_id = _actor_id(update)
    chat_id = _chat_id(update)
    if not context.args:
        if _is_staff(actor_id):
            children = get_children()
            await update.message.reply_text("Which child?", reply_markup=build_child_keyboard(children))
            return
        linked = _linked_children_for_chat(actor_id, fallback_chat_id=chat_id)
        if not linked:
            await update.message.reply_text(
                "Usage: `/milestones <child>`\n"
                "You must link your account first with `/link <first> <last>`.",
                parse_mode="Markdown",
            )
            return
        names = ", ".join(f"{c['fields'].get('first_name', '')} {c['fields'].get('last_name', '')}".strip() for c in linked)
        await update.message.reply_text(
            f"Usage: `/milestones <child>`\nYour linked child records: {names}",
            parse_mode="Markdown",
        )
        return
    child = find_child(context.args[0])
    if not child:
        await update.message.reply_text("❌ Child not found. Try a first name.")
        return
    if not await _require_child_access(update, child):
        return
    milestones = get_milestones(child_id(child))
    await update.message.reply_text(fmt_milestones(child, milestones), parse_mode="Markdown")


async def activity_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /activity — show today's scheduled activities (staff only)."""
    if not await _require_private_chat(update, "/activity"):
        return
    if not await _require_staff(update):
        return
    today = datetime.now().strftime("%Y-%m-%d")
    activities = get_activities(today)
    activities.sort(key=lambda a: a["fields"].get("start_time", ""))
    await update.message.reply_text(fmt_activities(activities), parse_mode="Markdown")


async def checkin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /checkin <child> — record arrival time (staff only)."""
    if not await _require_staff(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /checkin <child>")
        return
    child = find_child(context.args[0])
    if not child:
        await update.message.reply_text("❌ Child not found.")
        return
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    log_attendance(child_id(child), today, check_in=time_str)
    await update.message.reply_text(
        f"✅ {child['fields']['first_name']} {child['fields']['last_name']} checked in at {time_str} by staff"
    )

async def checkout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /checkout <child> — record departure time (staff only)."""
    if not await _require_staff(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /checkout <child>")
        return
    child = find_child(context.args[0])
    if not child:
        await update.message.reply_text("❌ Child not found.")
        return
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    log_attendance(child_id(child), today, check_out=time_str)
    await update.message.reply_text(
        f"🚪 {child['fields']['first_name']} {child['fields']['last_name']} checked out at {time_str}"
    )

async def observe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log a staff observation note with AI-tagged developmental milestone."""
    if not await _require_staff(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /observe <child> <your observation note>")
        return
    child = find_child(context.args[0])
    if not child:
        await update.message.reply_text("❌ Child not found.")
        return
    note = " ".join(context.args[1:])
    today = datetime.now().strftime("%Y-%m-%d")

    # Use AI client for milestone tagging (falls back to cache when Ollama is down)
    ai_result = tag_milestone(note) if AI_AVAILABLE else None

    if ai_result and ai_result.get("category"):
        add_milestone(child_id(child), today, ai_result["category"],
                      ai_result.get("description", note), 1, ai_result.get("tags", ""))
        lines = [
            "✅ *Observation logged!*",
            f"👶 Child: {child['fields']['first_name']} {child['fields']['last_name']}",
            f"📝 Note: \"{note}\"",
            f"🏷 Tags: {ai_result.get('tags', '')}",
            f"📊 Category: {ai_result.get('category', '')}",
            f"🌟 Milestone: {ai_result.get('milestone', '')}",
        ]
    else:
        add_milestone(child_id(child), today, "General", note, 1, "")
        lines = [
            "✅ *Observation logged!*",
            f"👶 Child: {child['fields']['first_name']} {child['fields']['last_name']}",
            f"📝 Note: \"{note}\"",
            "🏷 Tags: pending AI analysis...",
        ]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    # Notify parent
    parent_chat_id = get_parent_chat_id(child_id(child))
    if parent_chat_id:
        child_name = child["fields"]["first_name"]
        try:
            await context.bot.send_message(
                chat_id=parent_chat_id,
                text=(f"🌟 *New Milestone!*\n\n"
                      f"Your child *{child_name}* just achieved something special:\n\n"
                      f"📝 _{note}_\n\n"
                      f"🏷 {ai_result.get('tags', 'General') if ai_result else 'General'}\n\n"
                      f"Use /report {child_name.lower()} for today's full update."),
                parse_mode="Markdown")
        except Exception as e:
            logger.warning("Failed to notify parent for %s: %s", child_name, e)

async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Answer a free-text question using the AI client, regulatory RAG, or dashboard fallbacks."""
    if not context.args:
        await update.message.reply_text("Usage: /ask <your question about daycare policies or curriculum>")
        return
    question = " ".join(context.args)
    question_lower = question.lower()
    chat_id = update.effective_chat.id
    restricted_dashboard_keys = {"staffing", "subsidy", "subsidies", "forecast", "health"}
    if any(key in question_lower for key in restricted_dashboard_keys) and not _is_staff(chat_id):
        await update.message.reply_text(
            "⛔ Staffing, subsidy, forecast, and health dashboards are staff-only. "
            "Parents can still ask general policy questions with `/ask`.",
            parse_mode="Markdown",
        )
        return

    # 1. Try AI client (cache + Ollama)
    if AI_AVAILABLE:
        ai_answer = ask_question(question)
        if ai_answer and "I couldn't process" not in ai_answer:
            await update.message.reply_text(f"🤖 *AI Assistant*\n\n{ai_answer}", parse_mode="Markdown")
            return

    # 2. Try dashboard fallbacks
    for key, cached in DASHBOARD_FALLBACKS.items():
        if key in question_lower:
            await update.message.reply_text(f"🤖 *AI Assistant*\n\n{cached['response']}", parse_mode="Markdown")
            return

    # 3. Try regulatory RAG
    try:
        dynamic_rules = get_regulatory_rules(active_only=True)
        rag_answer = get_regulatory_answer(question, dynamic_rules=dynamic_rules)
        if rag_answer:
            await update.message.reply_text(rag_answer, parse_mode="Markdown")
            return
    except Exception:
        pass

    await update.message.reply_text(
        "🤖 *AI Assistant*\n\n"
        "I don't have an answer for that yet. Try asking about:\n"
        "• Staff ratios (infant, toddler, preschool, pre-K)\n"
        "• Allergy policies and food safety\n"
        "• Staff qualifications and training requirements\n"
        "• Nap time and outdoor play policies\n"
        "• Incident reporting procedures\n"
        "• Subsidy compliance and reauthorization\n\n"
        "Or use /staffing, /subsidies, /forecast, /health for specific dashboards.",
        parse_mode="Markdown",
    )


async def staffing_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /staffing — show today's staff coverage and ratio compliance."""
    if not await _require_private_chat(update, "/staffing"):
        return
    if not await _require_staff(update):
        return
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    today = days[datetime.now().weekday()]
    avail = get_staff_availability(today)
    rooms = get_room_ratios()

    lines = [f"📊 *Staffing Coverage — {today}*", ""]
    staff_by_room = {}
    for a in avail:
        f = a["fields"]
        for room in f.get("rooms_qualified", "").split(","):
            room = room.strip()
            if room not in staff_by_room:
                staff_by_room[room] = []
            staff_by_room[room].append(f"{f['staff']} ({f['start_time']}–{f['end_time']})"
                                       f"{' 📞 On Call' if f.get('is_on_call') else ''}")

    for r in rooms:
        rf = r["fields"]
        room_name = rf["room_name"]
        covered = staff_by_room.get(room_name, []) or staff_by_room.get(room_name.split(" ")[0], [])
        status = "✓ Covered" if covered else "⚠ No coverage"
        lines.append(f"*{room_name}* ({rf['staff_child_ratio']} ratio, {rf['current_enrolled']} enrolled): {status}")
        for s in covered:
            lines.append(f"  └ {s}")

    lines.extend(["", "💡 Use /callout to find substitutes if a staff member is out."])
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def callout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /callout [room] — find available substitutes for a staff call-out."""
    if not await _require_private_chat(update, "/callout"):
        return
    if not await _require_staff(update):
        return
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    today = days[datetime.now().weekday()]

    room = "Preschool"
    if context.args:
        room = " ".join(context.args)

    candidates = find_substitutes(today, room)

    lines = [f"📞 *Substitute Finder — {today}*", f"Room need: {room}", ""]
    if candidates:
        lines.append("Available substitutes:")
        for c in candidates:
            lines.append(f"• Staff #{c['staff']}: {c['start_time']}–{c['end_time']}")
            lines.append(f"  Qualified: {c['rooms_qualified']}")
            lines.append(f"  Phone: {c.get('phone', 'N/A')}")
            if c.get('notes'):
                lines.append(f"  Note: {c['notes']}")
    else:
        lines.append("⚠ No on-call or qualified substitutes found for today.")
        lines.append("Check staff availability table in Grist for manual override.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def subsidies_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /subsidies — show subsidy status and reauthorization deadlines."""
    if not await _require_staff(update):
        return
    subs = get_subsidies("Active")
    urgent = get_urgent_subsidies()

    lines = ["💰 *Subsidy Compliance*", ""]
    lines.append(f"Active subsidies: {len(subs)}")
    monthly_total = sum(_to_float(s["fields"].get("monthly_amount", 0)) for s in subs)
    lines.append(f"Monthly total: ${monthly_total:,.2f}")
    lines.append("")

    if urgent:
        lines.append("⚠ *URGENT — Action Required:*")
        for u in urgent:
            f = u["fields"]
            lines.append(f"• Child #{f['child']}: {f['program_name']}")
            lines.append(f"  Reauthorization: {f['reauthorization_date']}")
            lines.append(f"  Case Worker: {f['case_worker']} — {f['case_worker_phone']}")
            lines.append(f"  {f.get('notes', '')}")
        lines.append("")

    lines.append("All active subsidies:")
    for s in subs:
        f = s["fields"]
        amount = _to_float(f.get("monthly_amount", 0))
        lines.append(f"• Child #{f['child']}: {f['program_name']} — ${amount:,.2f}/mo")
        lines.append(f"  Reauth: {f['reauthorization_date']} | {f.get('status', '')}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def forecast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /forecast — show enrollment trends and revenue projections."""
    if not await _require_staff(update):
        return
    history = get_enrollment_history()
    children = get_children()
    active = [c for c in children if c["fields"].get("status", "").lower() != "inactive"]
    waitlist_entries = get_waitlist()
    waitlist_open = [
        w for w in waitlist_entries
        if str(w.get("fields", {}).get("status", "")).lower() in {"new", "contacted", "tour_scheduled", "offered"}
    ]
    waitlist = len(waitlist_open)

    lines = ["📈 *Enrollment Forecaster*", ""]
    lines.append(f"Current enrollment: {len(active)} children")
    lines.append(f"Waitlist: {waitlist} families")
    lines.append("")

    if history:
        lines.append("*Monthly trend:*")
        for h in history:
            f = h["fields"]
            enrolled = int(_to_float(f.get("total_enrolled", 0)))
            revenue = _to_float(f.get("monthly_revenue", 0))
            bar = "█" * max(enrolled, 0)
            lines.append(f"{f.get('month', '')}: {bar} {enrolled} enrolled | ${revenue:,.2f}")
        lines.append("")

    last = history[-1]["fields"] if history else {}
    current_revenue = _to_float(last.get("monthly_revenue", 0))
    lines.append(f"*Revenue:* ${current_revenue:,.2f}/mo (current)")
    if history and len(history) >= 2:
        prev_rev = _to_float(history[-2]["fields"].get("monthly_revenue", 0))
        if prev_rev > 0:
            delta_pct = ((current_revenue - prev_rev) / prev_rev) * 100
            trend_emoji = "📈" if delta_pct >= 0 else "📉"
            lines.append(f"{trend_emoji} Revenue {delta_pct:+.0f}% vs {history[-2]['fields'].get('month', '')}")
    lines.append("")

    # Anomaly detection (latest month drop vs prior 3-month average)
    if history and len(history) >= 4:
        recent = history[-1]["fields"]
        prior = history[-4:-1]
        avg_prior_enrollment = sum(_to_float(h["fields"].get("total_enrolled", 0)) for h in prior) / 3
        avg_prior_revenue = sum(_to_float(h["fields"].get("monthly_revenue", 0)) for h in prior) / 3
        recent_enrollment = _to_float(recent.get("total_enrolled", 0))
        recent_revenue = _to_float(recent.get("monthly_revenue", 0))
        anomalies = []
        if avg_prior_enrollment > 0 and recent_enrollment < avg_prior_enrollment * 0.9:
            anomalies.append("enrollment drop >10% vs prior 3-month average")
        if avg_prior_revenue > 0 and recent_revenue < avg_prior_revenue * 0.9:
            anomalies.append("revenue drop >10% vs prior 3-month average")
        if anomalies:
            lines.append(f"⚠ *Anomaly:* {'; '.join(anomalies)}")
            lines.append("")

    # Churn proxy (waitlist retention risk)
    high_risk = [
        w for w in waitlist_open
        if _to_float(w.get("fields", {}).get("retention_risk_score", 0)) >= 70
    ]
    medium_risk = [
        w for w in waitlist_open
        if 40 <= _to_float(w.get("fields", {}).get("retention_risk_score", 0)) < 70
    ]
    lines.append(f"*Churn Proxy:* high-risk leads {len(high_risk)}, medium-risk leads {len(medium_risk)}")

    rooms = get_room_ratios()
    capacity = sum(_to_float(r.get("fields", {}).get("max_children", 0)) for r in rooms)
    if capacity > 0:
        utilization = round((len(active) / capacity) * 100)
        lines.append(f"*Capacity utilization:* {utilization}% ({len(active)}/{int(capacity)})")
    else:
        lines.append("*Capacity utilization:* unavailable (set FORECAST_LICENSED_CAPACITY or Room Ratios.max_children)")

    # Breakeven signal (no hardcoded defaults)
    breakeven_cost_candidates = [
        _to_float(os.getenv("FORECAST_OPERATING_COST", "0")),
        _to_float(os.getenv("BREAKEVEN_MONTHLY_COST", "0")),
        _to_float(last.get("breakeven_monthly_cost", 0)),
        _to_float(last.get("operating_cost", 0)),
        _to_float(last.get("monthly_cost", 0)),
        _to_float(last.get("fixed_costs", 0)),
    ]
    breakeven_cost = next((v for v in breakeven_cost_candidates if v > 0), 0.0)
    avg_rev_per_child = _to_float(os.getenv("AVG_MONTHLY_REVENUE_PER_CHILD", "0"))
    if avg_rev_per_child <= 0:
        rev_per_child_series = [
            _to_float(h.get("fields", {}).get("monthly_revenue", 0)) / _to_float(h.get("fields", {}).get("total_enrolled", 0))
            for h in history
            if _to_float(h.get("fields", {}).get("total_enrolled", 0)) > 0 and _to_float(h.get("fields", {}).get("monthly_revenue", 0)) > 0
        ]
        if rev_per_child_series:
            avg_rev_per_child = sum(rev_per_child_series) / len(rev_per_child_series)
        elif len(active) > 0 and current_revenue > 0:
            avg_rev_per_child = current_revenue / len(active)

    if breakeven_cost > 0 and avg_rev_per_child > 0:
        breakeven_children = int((breakeven_cost / avg_rev_per_child) + 0.999)
        gap_children = breakeven_children - len(active)
        if gap_children > 0:
            lines.append(f"*Breakeven:* needs ~{breakeven_children} children (gap: {gap_children})")
        else:
            lines.append(f"*Breakeven:* above threshold by {abs(gap_children)} children")
    else:
        lines.append("*Breakeven:* unavailable (set FORECAST_OPERATING_COST/BREAKEVEN_MONTHLY_COST and AVG_MONTHLY_REVENUE_PER_CHILD)")

    if last.get("notes"):
        warning_indicators = ["warning", "decline", "part-time"]
        if any(w in last["notes"].lower() for w in warning_indicators):
            lines.append(f"⚠ *Alert:* {last['notes']}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /health — show cross-room allergies, incidents, and vaccine compliance."""
    if not await _require_staff(update):
        return
    summary = get_health_summary()

    lines = ["🏥 *Cross-Room Health Dashboard*", ""]

    if summary["allergies"]:
        lines.append("*Food Allergies:*")
        for child_name, allergy in summary["allergies"].items():
            lines.append(f"• {child_name}: {allergy}")
        lines.append(f"  Total: {len(summary['allergies'])} children with dietary restrictions")
        lines.append("")

    lines.append(f"*Recent Incidents:* {summary['total_incidents']}")
    for inc in summary["incidents"]:
        f = inc["fields"]
        lines.append(f"• {f['date']} — Child #{f['child']}: {f['incident_type']}")
        lines.append(f"  {f.get('description', '')}")
        lines.append(f"  Action: {f.get('action_taken', '')}")
        lines.append(f"  Parent notified: {'✅' if f.get('parent_notified') else '❌'}")
        lines.append("")

    # Vaccine compliance snapshot from Health History
    vaccine_summary = get_vaccine_summary()
    overdue_vax = [n for n, s in vaccine_summary.items() if s.get("compliance") == "Overdue"]
    due_soon_vax = [n for n, s in vaccine_summary.items() if s.get("compliance") == "Due soon"]
    if overdue_vax or due_soon_vax:
        lines.append("")
        lines.append("*Vaccine Compliance:*")
        if overdue_vax:
            lines.append(f"🔴 Overdue: {', '.join(overdue_vax)}")
        if due_soon_vax:
            lines.append(f"⚠️ Due soon: {', '.join(due_soon_vax)}")
        lines.append("Use `/vaccines <name>` for full health record.")

    if summary["allergies"]:
        lines.append("")
        lines.append("💡 *Kitchen reminder:* All allergen substitutions must be documented in the kitchen log.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def vaccines_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /vaccines [child] — show full health record for a child, or compliance summary for all."""
    if context.args:
        child = find_child(context.args[0])
        if not child:
            await update.message.reply_text("❌ Child not found. Try a first name.")
            return
        if not await _require_child_access(update, child):
            return
        health_records = get_health_history(child_id(child))
        c = child["fields"]
        if not health_records:
            await update.message.reply_text(f"No health record for {c['first_name']}.")
            return

        h = health_records[0]["fields"]
        lines = [f"🏥 *{c['first_name']} {c['last_name']} — Health Record*", ""]

        # Vaccine status
        vax = h.get("vaccine_status", "No records")
        vax_emoji = "🔴" if "OVERDUE" in vax or "overdue" in vax.lower() else ("⚠️" if "due soon" in vax.lower() else "✅")
        lines.append(f"{vax_emoji} *Vaccine Status:*")
        lines.append(f"   {vax}")
        lines.append("")

        # Allergen status
        allergen = h.get("allergen_status", "None")
        allergen_emoji = "⚠️" if "No known" not in allergen else "✅"
        lines.append(f"{allergen_emoji} *Allergen Status:*")
        lines.append(f"   {allergen}")
        lines.append("")

        # Doctors
        lines.append(f"👨‍⚕️ *Family Doctor:*")
        lines.append(f"   {h.get('family_doctor', 'Not on file')}")
        lines.append("")
        lines.append(f"🏥 *Pediatrician:*")
        lines.append(f"   {h.get('pediatrician', 'Not on file')}")
        lines.append("")

        # Other conditions
        other = h.get("other_conditions", "").strip()
        if other:
            lines.append(f"📋 *Other Conditions/Concerns:*")
            lines.append(f"   {other}")
            lines.append("")

        # Last updated
        lines.append(f"📅 Last updated: {h.get('last_updated', 'Unknown')}")
    else:
        if not await _require_staff(update):
            return
        # Summary view for all children
        vaccine_summary = get_vaccine_summary()
        lines = ["🏥 *Vaccine Compliance — All Children*", ""]
        compliance_emoji = {"Complete": "✅", "Overdue": "🔴", "Due soon": "⚠️", "Unknown": "⬜"}

        overdue_children = []
        due_soon_children = []
        for name, summary in sorted(vaccine_summary.items()):
            comp = summary.get("compliance", "Unknown")
            emoji = compliance_emoji.get(comp, "📋")
            stext = summary.get("status_text", "")
            # Extract first sentence for summary
            short = stext.split(".")[0] if stext else comp
            lines.append(f"{emoji} *{name}*: {comp}")
            if comp in ("Overdue", "Due soon"):
                lines.append(f"   _{short}_")
                if comp == "Overdue":
                    overdue_children.append(name)
                else:
                    due_soon_children.append(name)

        if overdue_children or due_soon_children:
            lines.append("")
            if overdue_children:
                lines.append(f"🔴 *Overdue:* {', '.join(overdue_children)} — use `/vaccines <name>` for full health record")
            if due_soon_children:
                lines.append(f"⚠️ *Due soon:* {', '.join(due_soon_children)} — schedule appointments")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /portfolio <child> — show a child's portfolio of milestone moments."""
    if not await _require_private_chat(update, "/portfolio"):
        return
    actor_id = _actor_id(update)
    chat_id = _chat_id(update)
    if not context.args:
        if _is_staff(actor_id):
            children = get_children()
            await update.message.reply_text("Which child's portfolio?", reply_markup=build_child_keyboard(children))
            return
        linked = _linked_children_for_chat(actor_id, fallback_chat_id=chat_id)
        if not linked:
            await update.message.reply_text(
                "Usage: `/portfolio <child>`\n"
                "You must link your account first with `/link <first> <last>`.",
                parse_mode="Markdown",
            )
            return
        names = ", ".join(f"{c['fields'].get('first_name', '')} {c['fields'].get('last_name', '')}".strip() for c in linked)
        await update.message.reply_text(
            f"Usage: `/portfolio <child>`\nYour linked child records: {names}",
            parse_mode="Markdown",
        )
        return
    child = find_child(context.args[0])
    if not child:
        await update.message.reply_text("❌ Child not found.")
        return
    if not await _require_child_access(update, child):
        return
    moments = get_portfolio_moments(child_id(child), limit=10)
    c = child["fields"]
    if not moments:
        await update.message.reply_text(f"No portfolio moments for {c['first_name']} yet.")
        return

    type_emoji = {"Photo": "📸", "Video": "🎬", "Audio": "🎵", "Drawing": "🎨"}
    cat_emoji = {"Physical": "🏃", "Cognitive": "🧠", "Language": "🗣",
                 "Social-Emotional": "💕", "Creative": "✨"}

    lines = [f"📚 *{c['first_name']}'s Portfolio*", f"{len(moments)} milestone moments captured", ""]

    for m in moments[:8]:
        f = m["fields"]
        t_emoji = type_emoji.get(f.get("moment_type", ""), "📌")
        c_emoji = cat_emoji.get(f.get("category", ""), "")
        highlight = " ⭐" if f.get("is_highlight") else ""
        lines.append(f"{t_emoji} *{f['title']}*{highlight}")
        lines.append(f"   {f.get('date', '')} | {c_emoji} {f.get('category', '')}")
        desc = f.get("description", "")
        if len(desc) > 120:
            desc = desc[:117] + "..."
        lines.append(f"   _{desc}_")
        if f.get("tags"):
            lines.append(f"   `{f['tags']}`")
        lines.append("")

    lines.append(f"💡 Use `/book {c['first_name'].lower()}` for this month's curated book.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def moment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /moment <child> <type> <title> — <desc> — log a new portfolio moment (staff only)."""
    if not await _require_staff(update):
        return
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: `/moment <child> <Photo|Video|Audio|Drawing> <title> — <description>`\n"
            "Example: `/moment emma Photo First painting — Emma painted a purple dinosaur today!`",
            parse_mode="Markdown")
        return
    child = find_child(context.args[0])
    if not child:
        await update.message.reply_text("❌ Child not found.")
        return
    moment_type = context.args[1].capitalize()
    if moment_type not in ("Photo", "Video", "Audio", "Drawing"):
        moment_type = "Photo"
    rest = " ".join(context.args[2:])
    if " — " in rest:
        title, description = rest.split(" — ", 1)
    else:
        title = rest[:80]
        description = rest

    today = datetime.now().strftime("%Y-%m-%d")
    add_portfolio_moment(child_id(child), today, moment_type, title.strip(), description.strip(),
                          "General", tags="Staff Entry", staff_id=1)

    await update.message.reply_text(
        f"✅ *Portfolio moment added!*\n"
        f"👶 {child['fields']['first_name']}\n"
        f"📌 {moment_type}: {title.strip()}\n"
        f"📅 {today}\n\n"
        f"Moment saved to Grist Portfolio_Moments table. Media file can be uploaded separately to Minio.",
        parse_mode="Markdown")

    # Notify parent
    parent_chat_id = get_parent_chat_id(child_id(child))
    if parent_chat_id:
        child_name = child["fields"]["first_name"]
        type_emoji = {"Photo": "📸", "Video": "🎬", "Audio": "🎵", "Drawing": "🎨"}
        emoji = type_emoji.get(moment_type, "📌")
        try:
            await context.bot.send_message(
                chat_id=parent_chat_id,
                text=f"{emoji} *New Portfolio Moment!*\n\n"
                     f"A new memory was captured for *{child_name}*:\n\n"
                     f"*{title.strip()}*\n"
                     f"_{description.strip()}_\n\n"
                     f"Use /portfolio {child_name.lower()} to see all moments.",
                parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Failed to notify parent for {child_name}: {e}")


async def book_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /book [child] [month] — view monthly milestone books."""
    chat_id = update.effective_chat.id
    if not context.args:
        if not _is_staff(chat_id):
            linked = _linked_children_for_chat(chat_id)
            if not linked:
                await update.message.reply_text(
                    "Usage: `/book <child>`\n"
                    "You must link your account first with `/link <first> <last>`.",
                    parse_mode="Markdown",
                )
                return
            names = ", ".join(f"{c['fields'].get('first_name', '')} {c['fields'].get('last_name', '')}".strip() for c in linked)
            await update.message.reply_text(
                f"Usage: `/book <child>`\nYour linked child records: {names}",
                parse_mode="Markdown",
            )
            return

        month = datetime.now().strftime("%Y-%m")
        books = get_all_monthly_books(month)
        if not books:
            await update.message.reply_text(f"No monthly books for {month} yet.")
            return

        lines = [f"📖 *Monthly Books — {month}*", ""]
        for b in books:
            f = b["fields"]
            child_name = ""
            children = get_children()
            for c in children:
                if str(c["id"]) == str(f.get("child")):
                    child_name = c["fields"]["first_name"]
                    break
            lines.append(f"📕 *{f['title']}*")
            lines.append(f"   {child_name} | Status: {f.get('status', 'Draft')}")
            lines.append(f"   _{f.get('cover_description', '')[:100]}_")
            lines.append("")
        lines.append("Use `/book <child>` to read a child's full monthly book.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    child = find_child(context.args[0])
    if not child:
        await update.message.reply_text("❌ Child not found.")
        return
    if not await _require_child_access(update, child):
        return

    month = context.args[1] if len(context.args) > 1 else datetime.now().strftime("%Y-%m")
    book = get_monthly_book(child_id(child), month)
    c = child["fields"]

    if not book:
        await update.message.reply_text(f"No {month} book for {c['first_name']} yet.")
        return

    bf = book["fields"]
    lines = [
        f"📖 *{bf['title']}*",
        f"",
        f"📸 *Cover:* {bf.get('cover_description', '')}",
        f"",
        f"📝 *Monthly Highlights:*",
        f"{bf.get('highlights', '')}",
        f"",
        f"💌 *Teacher's Note:*",
        f"_{bf.get('teacher_note', '')}_",
        f"",
        f"📅 {bf.get('month', '')} | ✏️ Status: {bf.get('status', 'Draft')}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /link <first_name> <last_name> — link a parent's Telegram account to their child."""
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/link <first_name> <last_name>`\n"
            "Example: `/link Emma Johnson`\n\n"
            "For security, both first AND last name are required. "
            "This links your Telegram account to your child so you receive instant "
            "notifications when staff record milestones and portfolio moments.",
            parse_mode="Markdown")
        return

    first_name = context.args[0]
    last_name = context.args[1]

    # Require exact match on both first and last name (case-insensitive)
    children = get_children()
    child = None
    for c in children:
        f = c["fields"]
        if (f["first_name"].lower() == first_name.lower()
                and f["last_name"].lower() == last_name.lower()):
            child = c
            break

    if not child:
        await update.message.reply_text(
            f"❌ No child found matching *{first_name} {last_name}*.\n"
            f"Please use the exact first and last name as registered with the daycare. "
            f"If you're unsure, ask the office manager.",
            parse_mode="Markdown")
        return

    # Prevent re-linking a child that already has a different parent linked
    existing_chat = get_parent_chat_id(child_id(child))
    chat_id = update.effective_chat.id
    if existing_chat and str(existing_chat) != str(chat_id):
        logger.warning(
            "Child %s %s already linked to chat %s — attempted re-link by chat %s",
            first_name, last_name, existing_chat, chat_id)
        await update.message.reply_text(
            "❌ This child is already linked to another parent account. "
            "Please contact the office manager to update the link.",
            parse_mode="Markdown")
        return

    result = set_parent_link(child_id(child), chat_id)
    if result is not None:
        await update.message.reply_text(
            f"✅ Your Telegram account has been linked to *{child['fields']['first_name']} "
            f"{child['fields']['last_name']}*!\n\n"
            f"You will now receive instant notifications when staff record milestones "
            f"or portfolio moments for your child.",
            parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Failed to link. Please ask the office manager for help.")


# --- Calendar / Meeting commands ---


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /schedule — create a staff meeting or parent-teacher conference."""
    if not await _require_staff(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "• `/schedule staff <date> <time> <title> — <description>`\n"
            "• `/schedule parent <child> <date> <time> <title> — <description>`\n\n"
            "Examples:\n"
            "• `/schedule staff 2026-06-01 14:00 Staff Training — Monthly safety review`\n"
            "• `/schedule parent emma 2026-06-05 15:30 Q2 Progress — Emma's development check-in`",
            parse_mode="Markdown")
        return

    meeting_type = context.args[0].lower()
    if meeting_type not in ("staff", "parent"):
        await update.message.reply_text(
            "First argument must be `staff` or `parent`.\n"
            "• `/schedule staff <date> <time> <title> — <description>`\n"
            "• `/schedule parent <child> <date> <time> <title> — <description>`",
            parse_mode="Markdown")
        return

    if meeting_type == "staff":
        # /schedule staff <date> <time> <title> — <description>
        if len(context.args) < 4:
            await update.message.reply_text(
                "Usage: `/schedule staff <date> <time> <title> — <description>`\n"
                "Example: `/schedule staff 2026-06-01 14:00 Staff Training — Monthly safety review`",
                parse_mode="Markdown")
            return
        date_str = context.args[1]
        time_str = context.args[2]
        rest = " ".join(context.args[3:])
        if " — " in rest:
            title, description = rest.split(" — ", 1)
        else:
            title = rest
            description = ""
        child_id_val = None
    else:
        # /schedule parent <child> <date> <time> <title> — <description>
        if len(context.args) < 5:
            await update.message.reply_text(
                "Usage: `/schedule parent <child> <date> <time> <title> — <description>`\n"
                "Example: `/schedule parent emma 2026-06-05 15:30 Q2 Progress — Development check-in`",
                parse_mode="Markdown")
            return
        child = find_child(context.args[1])
        if not child:
            await update.message.reply_text("❌ Child not found.")
            return
        child_id_val = child_id(child)
        date_str = context.args[2]
        time_str = context.args[3]
        rest = " ".join(context.args[4:])
        if " — " in rest:
            title, description = rest.split(" — ", 1)
        else:
            title = rest
            description = ""

    grist_type = "parent_teacher" if meeting_type == "parent" else meeting_type
    result = schedule_meeting(date_str, time_str, title.strip(), grist_type,
                              description.strip(), child_id=child_id_val)

    if result is not None:
        type_label = "Staff Meeting" if meeting_type == "staff" else "Parent-Teacher Meeting"
        lines = [
            f"✅ *{type_label} Scheduled!*",
            f"📌 *{title.strip()}*",
            f"📅 Date: {date_str}",
            f"🕐 Time: {time_str}",
        ]
        if description.strip():
            lines.append(f"📝 _{description.strip()}_")
        if meeting_type == "parent":
            lines.append("")
            lines.append("The parent will be notified via Telegram.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

        # Notify parent for parent-teacher meetings
        if meeting_type == "parent":
            parent_chat_id = get_parent_chat_id(child_id_val)
            if parent_chat_id:
                child_name = child["fields"]["first_name"]
                try:
                    await context.bot.send_message(
                        chat_id=parent_chat_id,
                        text=(f"📅 *Meeting Scheduled!*\n\n"
                              f"A parent-teacher meeting has been scheduled for *{child_name}*:\n\n"
                              f"📌 *{title.strip()}*\n"
                              f"📅 Date: {date_str}\n"
                              f"🕐 Time: {time_str}\n"
                              f"\n📝 _{description.strip()}_\n"
                              f"\nUse /meetings to see all upcoming meetings."),
                        parse_mode="Markdown")
                except Exception as e:
                    logger.warning("Failed to notify parent for %s: %s", child_name, e)
    else:
        await update.message.reply_text("❌ Failed to schedule meeting. Check Grist connection.")


async def meetings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /meetings [date] — list upcoming meetings."""
    chat_id = update.effective_chat.id
    date_filter = context.args[0] if context.args else None
    if _is_staff(chat_id):
        meetings = get_meetings(date=date_filter)
    else:
        linked_children = _linked_children_for_chat(chat_id)
        if not linked_children:
            await update.message.reply_text(
                "You have no linked child record yet. Use `/link <first> <last>` first.",
                parse_mode="Markdown",
            )
            return
        linked_child_ids = {str(c.get("id")) for c in linked_children}
        meetings = [
            meeting for meeting in get_meetings(date=date_filter, meeting_type="parent_teacher")
            if str(meeting.get("fields", {}).get("child", "")) in linked_child_ids
        ]

    if not meetings:
        label = f"on {date_filter}" if date_filter else ""
        if _is_staff(chat_id):
            await update.message.reply_text(f"📅 No meetings scheduled {label}.".strip())
        else:
            await update.message.reply_text(f"📅 No parent-teacher meetings scheduled {label}.".strip())
        return

    label = f"for {date_filter}" if date_filter else "(upcoming)"
    lines = [f"📅 *Meetings {label}*", ""]
    type_emoji = {"staff": "👥", "parent_teacher": "👨‍👩‍👧"}

    for m in meetings[:15]:
        f = m["fields"]
        emoji = type_emoji.get(f.get("meeting_type", ""), "📌")
        type_label = "Staff" if f.get("meeting_type") == "staff" else "Parent-Teacher"
        lines.append(f"{emoji} *{f['title']}*")
        lines.append(f"   {f.get('date', '')} at {f.get('time', '')} | {type_label}")
        desc = f.get("description", "")
        if desc:
            if len(desc) > 100:
                desc = desc[:97] + "..."
            lines.append(f"   _{desc}_")

        # Show child name for parent-teacher meetings
        if f.get("meeting_type") == "parent_teacher" and f.get("child"):
            child = find_child_by_id(f["child"])
            if child:
                lines.append(f"   👶 {child['fields']['first_name']} {child['fields']['last_name']}")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# --- Announcement / Message Board commands ---


async def announce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /announce — create and broadcast an announcement to all linked parents."""
    if not await _require_staff(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/announce <title> — <message>`\n\n"
            "This will broadcast the announcement to ALL linked parents.\n"
            "Add `!urgent` or `!important` at the start of the title for priority.\n\n"
            "Examples:\n"
            "• `/announce School Closure — Due to snow, school will be closed tomorrow March 15`\n"
            "• `/announce !important Reminder — No school this Friday for staff training`",
            parse_mode="Markdown")
        return

    raw = " ".join(context.args)

    # Parse priority from title prefix
    priority = "normal"
    if raw.lower().startswith("!urgent"):
        priority = "urgent"
        raw = raw[7:].strip()
    elif raw.lower().startswith("!important"):
        priority = "important"
        raw = raw[10:].strip()

    if " — " in raw:
        title, message = raw.split(" — ", 1)
    else:
        title = raw[:80]
        message = raw

    title = title.strip()
    message = message.strip()

    # Persist announcement to Grist
    if GRIST_AVAILABLE:
        create_announcement(title, message, priority=priority)

    # Broadcast to all linked parents
    priority_emoji = {"urgent": "🚨", "important": "⚠️", "normal": "📢"}
    emoji = priority_emoji.get(priority, "📢")

    broadcast_msg = (
        f"{emoji} *{title}*\n\n"
        f"{message}\n\n"
        f"_— Sunshine Sprouts Early Learning Center_"
    )

    parents = get_all_parent_chat_ids()
    sent_count = 0
    for chat_id, _name in parents:
        try:
            await context.bot.send_message(chat_id=chat_id, text=broadcast_msg, parse_mode="Markdown")
            sent_count += 1
        except Exception as e:
            logger.warning("Failed to send announcement to chat %s: %s", chat_id, e)

    await update.message.reply_text(
        f"📢 *Announcement Broadcast!*\n\n"
        f"*{title}*\n\n"
        f"_{message}_\n\n"
        f"✅ Sent to {sent_count}/{len(parents)} linked parents.",
        parse_mode="Markdown")


async def announcements_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /announcements — show recent announcements from the message board."""
    announcements = get_announcements(limit=10)

    if not announcements:
        await update.message.reply_text("📢 No announcements yet.")
        return

    priority_emoji = {"urgent": "🚨", "important": "⚠️", "normal": "📢"}
    lines = ["📢 *Message Board — Recent Announcements*", ""]

    for a in announcements:
        f = a["fields"]
        emoji = priority_emoji.get(f.get("priority", "normal"), "📢")
        lines.append(f"{emoji} *{f['title']}*")
        lines.append(f"   📅 {f.get('date', '')}")
        msg = f.get("message", "")
        if len(msg) > 120:
            msg = msg[:117] + "..."
        lines.append(f"   _{msg}_")
        lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# --- Kitchen Daily Menu commands ---


async def logmenu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /logmenu <date> <meal_type> <description> — staff logs a daily menu item."""
    if not await _require_staff(update):
        return
    valid_types = {"breakfast", "am_snack", "lunch", "pm_snack", "drinks"}
    type_labels = {
        "breakfast": "🍳 Breakfast",
        "am_snack": "🍎 Morning Snack",
        "lunch": "🍽 Lunch",
        "pm_snack": "🍪 Afternoon Snack",
        "drinks": "🥤 Drinks",
    }

    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: `/logmenu <date> <meal_type> <description>`\n\n"
            "Meal types: `breakfast`, `am_snack`, `lunch`, `pm_snack`, `drinks`\n\n"
            "Examples:\n"
            "• `/logmenu 2026-05-28 breakfast Scrambled eggs, whole wheat toast, apple slices, milk`\n"
            "• `/logmenu 2026-05-28 lunch Chicken quesadillas, carrot sticks, mixed berries, water`\n"
            "• `/logmenu 2026-05-28 pm_snack Yogurt parfait with granola and fresh peaches`",
            parse_mode="Markdown")
        return

    date_str = context.args[0]
    meal_type = context.args[1].lower()

    if meal_type not in valid_types:
        await update.message.reply_text(
            f"❌ Unknown meal type `{meal_type}`. Use: {', '.join(sorted(valid_types))}.",
            parse_mode="Markdown")
        return

    description = " ".join(context.args[2:])
    result = log_menu_item(date_str, meal_type, description)

    if result is not None:
        label = type_labels[meal_type]
        await update.message.reply_text(
            f"✅ *Menu logged!*\n\n"
            f"📅 Date: {date_str}\n"
            f"{label}\n"
            f"📝 {description}\n\n"
            f"Use `/menu {date_str}` to preview the full daily menu.",
            parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Failed to log menu item. Check Grist connection.")


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu [date] — view the daily menu with parent comments."""
    date_str = context.args[0] if context.args else datetime.now().strftime("%Y-%m-%d")
    items = get_daily_menu(date_str)
    comments = get_menu_comments(date_str)

    meal_labels = {
        "breakfast": "🍳 Breakfast",
        "am_snack": "🍎 Morning Snack",
        "lunch": "🍽 Lunch",
        "pm_snack": "🍪 Afternoon Snack",
        "drinks": "🥤 Drinks",
    }

    lines = [f"🍽 *Daily Menu — {date_str}*", ""]

    if not items:
        lines.append("_No menu posted yet for this date._")
    else:
        for item in items:
            f = item["fields"]
            label = meal_labels.get(f.get("meal_type", ""), f.get("meal_type", ""))
            lines.append(f"*{label}*")
            lines.append(f"{f.get('description', '')}")
            lines.append("")

    # Parent comments
    if comments:
        lines.append("💬 *Parent Comments*")
        for c in comments[:10]:
            f = c["fields"]
            lines.append(f"• _{f.get('comment', '')}_ — {f.get('parent_name', 'Anonymous')}")
    else:
        lines.append("💬 _No comments yet._")

    lines.extend(["", f"Parents: use `/menucomment {date_str} <your note>` to leave feedback."])

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def menucomment_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menucomment [date] <text> — parent leaves a comment on the daily menu."""
    user = update.effective_user
    parent_name = user.full_name

    if not context.args:
        await update.message.reply_text(
            "Usage: `/menucomment [date] <your comment>`\n\n"
            "Examples:\n"
            "• `/menucomment Love the variety of fruits this week!`\n"
            "• `/menucomment 2026-05-28 Could we add more dairy-free options?`",
            parse_mode="Markdown")
        return

    # First arg may be a date or the start of the comment
    first = context.args[0]
    if len(first) == 10 and first[4] == "-" and first[7] == "-":
        # Looks like a date
        date_str = first
        comment = " ".join(context.args[1:])
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        comment = " ".join(context.args)

    if not comment.strip():
        await update.message.reply_text("Please include a comment after the date.")
        return

    result = add_menu_comment(date_str, parent_name, comment.strip())
    if result is not None:
        await update.message.reply_text(
            f"✅ *Comment added!*\n\n"
            f"📅 Menu date: {date_str}\n"
            f"💬 _{comment.strip()}_\n\n"
            f"Thank you for your feedback, {parent_name}!",
            parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Failed to save comment. Check Grist connection.")


# --- Daily Schedule commands ---


async def setschedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setschedule <date> <type> <start>-<end> <desc> — staff sets a daily activity block."""
    if not await _require_staff(update):
        return
    valid_types = {"nap", "outdoor", "class", "craft"}
    type_labels = {
        "nap": "😴 Nap Time", "outdoor": "🌳 Outdoor Play",
        "class": "📚 Class Time", "craft": "🎨 Craft Time",
    }

    if len(context.args) < 4:
        await update.message.reply_text(
            "Usage: `/setschedule <date> <type> <start_time> <end_time> <description>`\n\n"
            "Activity types: `nap`, `outdoor`, `class`, `craft`\n\n"
            "Examples:\n"
            "• `/setschedule 2026-05-28 nap 12:30 14:30 Quiet time — children on cots`\n"
            "• `/setschedule 2026-05-28 outdoor 10:00 11:00 Playground — sandbox & climbing`\n"
            "• `/setschedule 2026-05-28 class 09:00 10:00 Circle time — alphabet & counting`\n"
            "• `/setschedule 2026-05-28 craft 15:00 16:00 Finger painting — primary colors`",
            parse_mode="Markdown")
        return

    date_str = context.args[0]
    activity_type = context.args[1].lower()

    if activity_type not in valid_types:
        await update.message.reply_text(
            f"❌ Unknown activity type `{activity_type}`. Use: {', '.join(sorted(valid_types))}.",
            parse_mode="Markdown")
        return

    start_time = context.args[2]
    end_time = context.args[3]
    description = " ".join(context.args[4:]) if len(context.args) > 4 else ""

    result = set_daily_activity(date_str, activity_type, start_time, end_time, description)

    if result is not None:
        label = type_labels[activity_type]
        lines = [
            f"✅ *Activity Block Set!*",
            f"📅 Date: {date_str}",
            f"{label}",
            f"🕐 {start_time} – {end_time}",
        ]
        if description:
            lines.append(f"📝 _{description}_")
        lines.extend(["", f"Use `/scheduletoday {date_str}` to see the full day."])
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Failed to save. Check Grist connection.")


async def scheduletoday_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /scheduletoday [date] — view the full daily routine schedule."""
    date_str = context.args[0] if context.args else datetime.now().strftime("%Y-%m-%d")
    blocks = get_daily_schedule(date_str)

    activity_emoji = {
        "nap": "😴", "outdoor": "🌳", "class": "📚", "craft": "🎨",
    }
    activity_labels = {
        "nap": "Nap Time", "outdoor": "Outdoor Play",
        "class": "Class Time", "craft": "Craft Time",
    }

    lines = [f"📅 *Daily Schedule — {date_str}*", ""]

    if not blocks:
        lines.append("_No schedule posted yet for this date._")
        lines.append("Staff: use `/setschedule` to add nap, outdoor, class, and craft times.")
    else:
        for b in blocks:
            f = b["fields"]
            atype = f.get("activity_type", "")
            emoji = activity_emoji.get(atype, "📌")
            label = activity_labels.get(atype, atype)
            start = f.get("start_time", "")
            end = f.get("end_time", "")
            desc = f.get("description", "")
            room = f.get("room", "")

            lines.append(f"{emoji} *{label}*  |  🕐 {start} – {end}")
            if room:
                lines.append(f"   📍 {room}")
            if desc:
                lines.append(f"   📝 _{desc}_")
            lines.append("")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# --- Contingency Teacher Roster commands ---


async def addsub_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /addsub <name> | <phone> | <email> | <rooms> | <availability> — add a sub teacher."""
    if not await _require_staff(update):
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/addsub <name> | <phone> | <email> | <rooms> | <availability> | <notes>`\n\n"
            "Use `|` to separate fields. Name and phone are required; others are optional.\n\n"
            "Examples:\n"
            "• `/addsub Jane Smith | 555-0100 | jane@email.com | Infant, Toddler | Weekdays | CPR certified`\n"
            "• `/addsub Bob Wilson | 555-0200 | bob@email.com | Preschool, Pre-K | Weekends`",
            parse_mode="Markdown")
        return

    raw = " ".join(context.args)
    parts = [p.strip() for p in raw.split("|")]

    name = parts[0] if len(parts) > 0 else ""
    phone = parts[1] if len(parts) > 1 else ""
    email = parts[2] if len(parts) > 2 else ""
    rooms = parts[3] if len(parts) > 3 else ""
    availability = parts[4] if len(parts) > 4 else ""
    notes = parts[5] if len(parts) > 5 else ""

    if not name or not phone:
        await update.message.reply_text("❌ Name and phone are required fields.", parse_mode="Markdown")
        return

    result = add_contingency_teacher(name, phone, email, rooms, notes, availability)
    if result is not None:
        lines = [
            "✅ *Substitute Teacher Added!*",
            "",
            f"👤 *Name:* {name}",
            f"📞 *Phone:* {phone}",
        ]
        if email:
            lines.append(f"📧 *Email:* {email}")
        if rooms:
            lines.append(f"🏫 *Rooms:* {rooms}")
        if availability:
            lines.append(f"📅 *Availability:* {availability}")
        if notes:
            lines.append(f"📝 *Notes:* {notes}")
        lines.extend(["", "Use `/substitutes` to view the full roster."])
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Failed to add substitute. Check Grist connection.")


async def substitutes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /substitutes [room] — view the contingency teacher roster (staff only)."""
    if not await _require_staff(update):
        return
    room = " ".join(context.args) if context.args else ""
    teachers = find_contingency_teachers(room)

    if not teachers:
        label = f" qualified for '{room}'" if room else ""
        await update.message.reply_text(f"No substitute teachers{label} in the roster.")
        return

    label = f" — qualified for '{room}'" if room else " (all)"
    lines = [f"📞 *Contingency Teacher Roster{label}*", ""]

    for t in teachers:
        f = t["fields"]
        lines.append(f"👤 *{f.get('name', '')}*")
        lines.append(f"   📞 {f.get('phone', 'N/A')}")
        email = f.get("email", "")
        if email:
            lines.append(f"   📧 {email}")
        rooms_q = f.get("rooms_qualified", "")
        if rooms_q:
            lines.append(f"   🏫 Rooms: {rooms_q}")
        avail = f.get("availability", "")
        if avail:
            lines.append(f"   📅 {avail}")
        notes = f.get("notes", "")
        if notes:
            lines.append(f"   📝 _{notes}_")
        lines.append("")

    lines.extend([
        f"📋 *{len(teachers)} substitute(s) found.*",
        "",
        "Use `/addsub` to add a new substitute teacher.",
        "Use `/callout <room>` to find available staff for today.",
    ])
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle non-command text — try to match a child name and show their daily report."""
    text = update.message.text
    if not text.startswith("/"):
        children = get_children()
        for c in children:
            if c["fields"]["first_name"].lower() in text.lower():
                child = find_child(c["fields"]["first_name"])
                if child:
                    if not await _require_child_access(update, child):
                        return
                    today = datetime.now().strftime("%Y-%m-%d")
                    report = get_daily_report(child_id(child), today)
                    if report:
                        await update.message.reply_text(fmt_report(child, report), parse_mode="Markdown")
                        return
        await update.message.reply_text("Type /help to see available commands.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks — show report or milestones for the selected child."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("child_"):
        child_id_str = data.replace("child_", "")
        children = get_children()
        child = next((c for c in children if str(c["id"]) == child_id_str), None)
        if child:
            if not await _require_child_access(update, child):
                return
            today = datetime.now().strftime("%Y-%m-%d")
            report = get_daily_report(child_id(child), today)
            if report:
                # Determine which command was used by checking the message
                msg_text = query.message.text or ""
                if "report" in msg_text.lower() or "Which child" in msg_text:
                    await query.edit_message_text(fmt_report(child, report), parse_mode="Markdown")
                elif "milestone" in msg_text.lower():
                    milestones = get_milestones(child_id(child))
                    await query.edit_message_text(fmt_milestones(child, milestones), parse_mode="Markdown")
                else:
                    await query.edit_message_text(fmt_report(child, report), parse_mode="Markdown")
            else:
                await query.edit_message_text(f"📋 No report for {child['fields']['first_name']} yet today.")


def run_telegram_bot():
    """Build the Telegram Application, register all handlers, and start polling."""
    if not TELEGRAM_AVAILABLE:
        logger.error("Telegram not available")
        return
    if TOKEN == "placeholder" or TOKEN.startswith("placeholder"):
        logger.warning("TELEGRAM_BOT_TOKEN is placeholder — bot polling not started. Flask API still available.")
        return

    logger.info("Starting Telegram bot polling...")
    try:
        tg_app = Application.builder().token(TOKEN).build()
        tg_app.add_handler(CommandHandler("start", start))
        tg_app.add_handler(CommandHandler("help", help_cmd))
        tg_app.add_handler(CommandHandler("report", report_cmd))
        tg_app.add_handler(CommandHandler("milestones", milestones_cmd))
        tg_app.add_handler(CommandHandler("activity", activity_cmd))
        tg_app.add_handler(CommandHandler("checkin", checkin_cmd))
        tg_app.add_handler(CommandHandler("checkout", checkout_cmd))
        tg_app.add_handler(CommandHandler("observe", observe_cmd))
        tg_app.add_handler(CommandHandler("ask", ask_cmd))
        tg_app.add_handler(CommandHandler("staffing", staffing_cmd))
        tg_app.add_handler(CommandHandler("callout", callout_cmd))
        tg_app.add_handler(CommandHandler("subsidies", subsidies_cmd))
        tg_app.add_handler(CommandHandler("forecast", forecast_cmd))
        tg_app.add_handler(CommandHandler("health", health_cmd))
        tg_app.add_handler(CommandHandler("vaccines", vaccines_cmd))
        tg_app.add_handler(CommandHandler("portfolio", portfolio_cmd))
        tg_app.add_handler(CommandHandler("moment", moment_cmd))
        tg_app.add_handler(CommandHandler("book", book_cmd))
        tg_app.add_handler(CommandHandler("link", link_cmd))
        tg_app.add_handler(CommandHandler("schedule", schedule_cmd))
        tg_app.add_handler(CommandHandler("meetings", meetings_cmd))
        tg_app.add_handler(CommandHandler("announce", announce_cmd))
        tg_app.add_handler(CommandHandler("announcements", announcements_cmd))
        tg_app.add_handler(CommandHandler("logmenu", logmenu_cmd))
        tg_app.add_handler(CommandHandler("menu", menu_cmd))
        tg_app.add_handler(CommandHandler("menucomment", menucomment_cmd))
        tg_app.add_handler(CommandHandler("setschedule", setschedule_cmd))
        tg_app.add_handler(CommandHandler("scheduletoday", scheduletoday_cmd))
        tg_app.add_handler(CommandHandler("addsub", addsub_cmd))
        tg_app.add_handler(CommandHandler("substitutes", substitutes_cmd))
        tg_app.add_handler(CallbackQueryHandler(button_callback))
        tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
        tg_app.run_polling(allowed_updates=Update.ALL_TYPES, stop_signals=[])
    except Exception as e:
        logger.error("Telegram bot failed to start: %s. Flask API still available.", e)

def run_flask():
    """Start the Flask API server (runs in a daemon thread)."""
    port = int(os.getenv("PORT", "8097"))
    logger.info("Starting Flask API on port %d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    # Start Flask API in a daemon thread — Telegram bot runs in main thread
    # (run_polling requires main thread for asyncio signal handling)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask API thread started")

    # Start Telegram bot in main thread, or keep alive if no valid token
    token_valid = TELEGRAM_AVAILABLE and TOKEN and TOKEN != "placeholder" and not TOKEN.startswith("placeholder")
    if token_valid:
        run_telegram_bot()
    else:
        logger.warning("Telegram bot not started (no valid token). Flask API available.")
    # Keep process alive so Flask keeps serving (bot failure shouldn't kill the API)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
