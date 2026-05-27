"""Daycare Telegram Bot — Flask API + Telegram polling bridge."""

import logging
import os
import threading
import time
from datetime import datetime

import requests
from flask import Flask, request, jsonify

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Shared secret for API authentication (n8n webhooks, external callers).
# Requests must include header  X-API-Key: <value>
API_KEY = os.getenv("API_KEY", "")
PUBLIC_ROUTES = {"health"}  # endpoint names that skip auth
INSECURE_DEMO_MODE = os.getenv("INSECURE_DEMO_MODE", "").strip().lower() in {"1", "true", "yes"}


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
    if token != API_KEY:
        return jsonify({"error": "unauthorized"}), 401
    return None


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
    get_regulatory_answer = lambda _q: None  # type: ignore[assignment]

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


PICKUP_DENIAL_CODES = {
    "guardian_not_linked",
    "legal_restriction",
    "pickup_not_allowed",
    "pickup_password_mismatch",
    "identity_mismatch",
    "court_order_restriction",
    "other",
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

    return jsonify({"count": len(filtered), "events": filtered})


@app.route("/billing/invoices/generate", methods=["POST"])
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
        record.setdefault("status", "issued")
        record["subtotal"] = _to_float(record.get("subtotal", record.get("total_due")))
        record["subsidy_credit"] = _to_float(record.get("subsidy_credit", 0))
        record["late_fees"] = _to_float(record.get("late_fees", 0))
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
    attempts = get_autopay_attempts(invoice_id_val=invoice_id_val)
    return jsonify({
        "invoice_id": invoice_id_val,
        "count": len(attempts),
        "attempts": [{"id": a.get("id"), "fields": a.get("fields", {})} for a in attempts],
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
    claim_month = request.args.get("claim_month")
    status = request.args.get("status")
    program = request.args.get("program")
    claims = get_subsidy_claims(claim_month=claim_month, status=status, program=program)
    return jsonify({
        "count": len(claims),
        "claims": [{"id": c.get("id"), "fields": c.get("fields", {})} for c in claims],
    })


@app.route("/subsidy/reconcile/<claim_id_val>", methods=["POST"])
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


@app.route("/waitlist", methods=["GET"])
def api_waitlist():
    """Return waitlist entries, optionally filtered by status."""
    status = request.args.get("status")
    entries = get_waitlist(status=status)
    return jsonify({"count": len(entries), "entries": [{"id": e.get("id"), "fields": e.get("fields", {})} for e in entries]})


@app.route("/waitlist", methods=["POST"])
def api_waitlist_add():
    """Create a waitlist entry."""
    data = request.get_json(force=True, silent=True) or {}
    required = {"child_first_name", "child_last_name", "desired_start_date", "status"}
    missing = [field for field in required if data.get(field) in (None, "")]
    if missing:
        return jsonify({"error": f"missing waitlist fields: {', '.join(missing)}"}), 400

    data.setdefault("priority_score", 0)
    data["priority_score"] = _to_float(data.get("priority_score", 0))
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
    result = update_waitlist_entry(entry_id_val, data)
    if result is None:
        return jsonify({"error": "failed to update waitlist entry"}), 500
    return jsonify({"status": "updated", "entry_id": entry_id_val})


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
        new_status = str(target_status)
    else:
        flow = ["new", "contacted", "tour_scheduled", "offered", "enrolled"]
        current = str(entry["fields"].get("status", "new")).lower()
        if current in flow and current != flow[-1]:
            new_status = flow[flow.index(current) + 1]
        else:
            new_status = current

    patch = {"status": new_status, "last_contact_at": datetime.utcnow().isoformat(timespec="seconds")}
    result = update_waitlist_entry(entry_id_val, patch)
    if result is None:
        return jsonify({"error": "failed to advance waitlist entry"}), 500
    return jsonify({"status": "advanced", "entry_id": entry_id_val, "new_status": new_status})


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


async def _require_staff(update: Update) -> bool:
    """Check that the sender is staff. Replies with an error and returns False if not."""
    chat_id = update.effective_chat.id
    if not _is_staff(chat_id):
        logger.warning("Non-staff chat %s attempted restricted command", chat_id)
        if update.message:
            await update.message.reply_text("⛔ This command is for staff only.")
        return False
    return True


def _linked_children_for_chat(chat_id: int) -> list[dict]:
    """Return children linked to a parent Telegram chat_id."""
    children = get_children()
    return [
        child for child in children
        if str(child.get("fields", {}).get("parent_chat_id", "")).strip() == str(chat_id)
    ]


async def _require_child_access(update: Update, child: dict) -> bool:
    """Allow staff, or the parent account linked to the child."""
    chat_id = update.effective_chat.id
    if _is_staff(chat_id):
        return True
    linked_chat = str(child.get("fields", {}).get("parent_chat_id", "")).strip()
    if linked_chat and linked_chat == str(chat_id):
        return True
    if update.message:
        await update.message.reply_text(
            "⛔ You can only access records for your linked child. "
            "Use `/link <first> <last>` or contact the office manager.",
            parse_mode="Markdown",
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
    if not context.args:
        children = get_children()
        await update.message.reply_text("Which child?", reply_markup=build_child_keyboard(children))
        return
    child = find_child(context.args[0])
    if not child:
        await update.message.reply_text(f"❌ Child not found. Try a first name.")
        return
    milestones = get_milestones(child_id(child))
    await update.message.reply_text(fmt_milestones(child, milestones), parse_mode="Markdown")

async def activity_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /activity — show today's scheduled activities."""
    today = datetime.now().strftime("%Y-%m-%d")
    activities = get_activities(today)
    # Sort by start time
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
        rag_answer = get_regulatory_answer(question)
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
    waitlist = 5  # From seed data

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
        if prev_rev > 0 and current_revenue > prev_rev:
            delta_pct = ((current_revenue - prev_rev) / prev_rev) * 100
            lines.append(f"📈 Revenue up {delta_pct:.0f}% since {history[-2]['fields'].get('month', '')}")
    lines.append("")

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
    if not context.args:
        children = get_children()
        await update.message.reply_text("Which child's portfolio?", reply_markup=build_child_keyboard(children))
        return
    child = find_child(context.args[0])
    if not child:
        await update.message.reply_text("❌ Child not found.")
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
    if not context.args:
        # Show all May 2026 books
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
    date_filter = context.args[0] if context.args else None
    meetings = get_meetings(date=date_filter)

    if not meetings:
        label = f"on {date_filter}" if date_filter else ""
        await update.message.reply_text(f"📅 No meetings scheduled {label}.".strip())
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
