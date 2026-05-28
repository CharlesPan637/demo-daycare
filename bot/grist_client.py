"""Grist API client for daycare data queries."""
import os, requests

API_KEY = os.getenv("GRIST_API_KEY")
DOC_ID = os.getenv("GRIST_DOC_ID")
BASE_URL = os.getenv("GRIST_BASE_URL", "http://grist:8484")

HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
TABLE_MAP = {"children": "Table2", "staff": "Table3", "attendance": "Table4",
              "activities": "Table5", "milestones": "Table6", "reports": "Table7",
              "staff_avail": "Table8", "room_ratios": "Table9", "subsidies": "Table10",
              "enrollment": "Table11", "incidents": "Table12", "health_history": "Health_History",
              "portfolio": "Table14", "monthly_books": "Table15",
              "meetings": "Table16", "announcements": "Table17",
              "menu": "Table18", "menu_comments": "Table19",
              "daily_schedule": "Table20",
              "contingency_teachers": "Table21",
              "guardians": "Guardians",
              "child_guardians": "Child_Guardians",
              "pickup_events": "Pickup_Events",
              "billing_accounts": "Billing_Accounts",
              "billing_account_parties": "Billing_Account_Parties",
              "invoices": "Invoices",
              "payments": "Payments",
              "waitlist": "Waitlist",
              "subsidy_claims": "Subsidy_Claims",
              "autopay_attempts": "Autopay_Attempts",
              "medication_logs": "Medication_Logs",
              "sanitation_checks": "Sanitation_Checks",
              "sleep_safety_checks": "Sleep_Safety_Checks",
              "regulatory_rules": "Regulatory_Rules",
              "regulatory_risk_assessments": "Regulatory_Risk_Assessments",
              "workflow_heartbeat": "Workflow_Heartbeat",
              "marketing_leads": "Marketing_Leads",
              "review_requests": "Review_Requests",
              "insurance_policies": "Insurance_Policies",
              "competitor_snapshots": "Competitor_Snapshots",
              "marketing_channel_spend": "Marketing_Channel_Spend"}


def _as_grist_id(value: int | str | None) -> int | str | None:
    """Convert numeric-string record IDs to ints for Grist Ref/id fields."""
    if value is None:
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed.isdigit():
            return int(trimmed)
    return value

def _api(method: str, path: str, data: dict | None = None) -> dict | None:
    """Make an authenticated request to the Grist API. Returns parsed JSON or None on error."""
    url = f"{BASE_URL}/api/docs/{DOC_ID}{path}"
    kwargs: dict = {"headers": HEADERS, "timeout": 10}
    if data is not None:
        kwargs["json"] = data
    try:
        r = requests.request(method, url, **kwargs)
    except requests.RequestException:
        return None
    if r.status_code >= 400:
        return None
    if not r.text:
        return {}
    try:
        payload = r.json()
    except ValueError:
        return {}
    return {} if payload is None else payload

def get_children() -> list:
    """Return all child records from the Grist Children table."""
    resp = _api("GET", f"/tables/{TABLE_MAP['children']}/records")
    if not resp:
        return []
    return resp.get("records", [])

def find_child(name: str) -> dict | None:
    """Find a child record by first name (case-insensitive prefix or substring match)."""
    children = get_children()
    name_lower = name.lower().strip()
    matches = [c for c in children if c["fields"]["first_name"].lower().startswith(name_lower)]
    if len(matches) == 1:
        return matches[0]
    # Try contains
    matches = [c for c in children if name_lower in c["fields"]["first_name"].lower()]
    return matches[0] if len(matches) == 1 else None

def find_child_by_id(child_id_val: int | str) -> dict | None:
    """Find a child record by its Grist record ID."""
    children = get_children()
    for c in children:
        if str(c.get("id")) == str(child_id_val):
            return c
    return None

def get_parent_chat_id(child_id_val: int | str) -> str | None:
    """Return the parent's Telegram chat ID linked to *child_id_val*, or None."""
    child = find_child_by_id(child_id_val)
    if not child:
        return None
    chat_id = get_child_field(child, "parent_chat_id")
    return chat_id if chat_id else None

def set_parent_link(child_id_val: int | str, chat_id: int | str) -> dict | None:
    """Store a parent's Telegram chat_id on their child's Grist record."""
    return _api("PATCH", f"/tables/{TABLE_MAP['children']}/records", {
        "records": [{"id": child_id_val, "fields": {"parent_chat_id": str(chat_id)}}]})

def get_daily_report(child_id: int | str, date: str) -> dict | None:
    """Return the daily report fields for *child_id* on *date* (YYYY-MM-DD), or None."""
    reports = _api("GET", f"/tables/{TABLE_MAP['reports']}/records")
    if not reports:
        return None
    for r in reports.get("records", []):
        f = r["fields"]
        if str(f.get("child")) == str(child_id) and f.get("date") == date:
            return f
    return None

def get_milestones(child_id: int | str, limit: int = 5) -> list:
    """Return the most recent milestones for *child_id*, newest first."""
    milestones = _api("GET", f"/tables/{TABLE_MAP['milestones']}/records")
    if not milestones:
        return []
    child_milestones = [m for m in milestones.get("records", []) if str(m["fields"].get("child")) == str(child_id)]
    return sorted(child_milestones, key=lambda m: m["fields"].get("date", ""), reverse=True)[:limit]

def get_activities(date: str) -> list:
    """Return all scheduled activities for *date* (YYYY-MM-DD)."""
    activities = _api("GET", f"/tables/{TABLE_MAP['activities']}/records")
    if not activities:
        return []
    return [a for a in activities.get("records", []) if a["fields"].get("activity_date") == date]

def log_attendance(child_id: int | str, date: str, check_in: str | None = None,
                   check_out: str | None = None, staff_id: int = 1, notes: str = "") -> dict | None:
    """Create or update an attendance record. Posts check_in; patches check_out onto existing row."""
    if check_in:
        return _api("POST", f"/tables/{TABLE_MAP['attendance']}/records", {
            "records": [{"fields": {"child": child_id, "date": date, "check_in": check_in,
                                     "staff": staff_id, "notes": notes}}]})
    if check_out:
        # Find existing attendance and update
        records = _api("GET", f"/tables/{TABLE_MAP['attendance']}/records")
        if records:
            for r in records.get("records", []):
                f = r["fields"]
                if str(f.get("child")) == str(child_id) and f.get("date") == date and not f.get("check_out"):
                    return _api("PATCH", f"/tables/{TABLE_MAP['attendance']}/records", {
                        "records": [{"id": r["id"], "fields": {"check_out": check_out}}]})
    return None

def add_milestone(child_id: int | str, date: str, category: str, description: str,
                   staff_id: int, tags: str, ai_generated: bool = True) -> dict | None:
    """Create a new developmental milestone record for *child_id*."""
    return _api("POST", f"/tables/{TABLE_MAP['milestones']}/records", {
        "records": [{"fields": {"child": child_id, "date": date, "category": category,
                                 "description": description, "staff": staff_id,
                                 "tags": tags, "ai_generated": ai_generated}}]})

def get_child_field(child_record: dict, field_name: str) -> str:
    """Safely extract a field value from a child record dict (handles nested 'fields' key)."""
    if isinstance(child_record, dict) and "fields" in child_record:
        return child_record["fields"].get(field_name, "")
    return child_record.get(field_name, "") if isinstance(child_record, dict) else ""

def child_id(child_record: dict) -> int | None:
    """Return the Grist record ID from a child record dict."""
    if isinstance(child_record, dict):
        return child_record.get("id")
    return None


# --- Staff Availability (Table8) ---


def get_staff_availability(day_of_week: str | None = None) -> list:
    """Return staff availability records, optionally filtered by day of week."""
    records = _api("GET", f"/tables/{TABLE_MAP['staff_avail']}/records")
    if not records:
        return []
    if day_of_week:
        return [r for r in records.get("records", []) if r["fields"].get("day_of_week") == day_of_week]
    return records.get("records", [])


def find_substitutes(day_of_week: str, room_qual: str) -> list:
    """Return on-call or room-qualified staff available as substitutes for *day_of_week*."""
    all_avail = get_staff_availability(day_of_week)
    candidates = []
    for r in all_avail:
        f = r["fields"]
        if f.get("is_on_call"):
            candidates.append(f)
        elif room_qual.lower() in f.get("rooms_qualified", "").lower():
            candidates.append(f)
    return candidates


# --- Room Ratios (Table9) ---


def get_room_ratios() -> list:
    """Return all room ratio records (room name, ratio, enrolled count)."""
    records = _api("GET", f"/tables/{TABLE_MAP['room_ratios']}/records")
    return records.get("records", []) if records else []


# --- Subsidies (Table10) ---


def get_subsidies(status: str | None = None) -> list:
    """Return subsidy records, optionally filtered by status (e.g. 'Active')."""
    records = _api("GET", f"/tables/{TABLE_MAP['subsidies']}/records")
    if not records:
        return []
    if status:
        return [r for r in records.get("records", []) if r["fields"].get("status") == status]
    return records.get("records", [])


def get_urgent_subsidies() -> list:
    """Return subsidies whose notes indicate an urgent/upcoming reauthorization deadline."""
    records = _api("GET", f"/tables/{TABLE_MAP['subsidies']}/records")
    if not records:
        return []
    urgent = []
    for r in records.get("records", []):
        notes = r["fields"].get("notes", "")
        if "urgent" in notes.lower() or "due in" in notes.lower():
            urgent.append(r)
    return urgent


def create_subsidy_claim(fields: dict) -> dict | None:
    """Create a subsidy claim record."""
    result = _api("POST", f"/tables/{TABLE_MAP['subsidy_claims']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_subsidy_claims(claim_month: str | None = None, status: str | None = None,
                       program: str | None = None) -> list:
    """Return subsidy claim records, optionally filtered by month/status/program."""
    records = _api("GET", f"/tables/{TABLE_MAP['subsidy_claims']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if claim_month:
        result = [r for r in result if str(r["fields"].get("claim_month", "")).strip() == claim_month.strip()]
    if status:
        result = [r for r in result if str(r["fields"].get("status", "")).lower() == status.lower()]
    if program:
        result = [r for r in result if str(r["fields"].get("program", "")).lower() == program.lower()]
    return result


def update_subsidy_claim(claim_id_val: int | str, fields: dict) -> dict | None:
    """Patch fields on a subsidy claim record."""
    return _api("PATCH", f"/tables/{TABLE_MAP['subsidy_claims']}/records", {
        "records": [{"id": _as_grist_id(claim_id_val), "fields": fields}]})


# --- Enrollment History (Table11) ---


def get_enrollment_history() -> list:
    """Return enrollment history records sorted by month ascending."""
    records = _api("GET", f"/tables/{TABLE_MAP['enrollment']}/records")
    if not records:
        return []
    return sorted(records.get("records", []), key=lambda r: r["fields"].get("month", ""))


# --- Incidents (Table12) ---


def get_incidents(child_id_val: int | str | None = None) -> list:
    """Return incident records, optionally filtered by child ID."""
    records = _api("GET", f"/tables/{TABLE_MAP['incidents']}/records")
    if not records:
        return []
    if child_id_val:
        return [r for r in records.get("records", []) if str(r["fields"].get("child")) == str(child_id_val)]
    return records.get("records", [])


def get_health_summary() -> dict:
    """Return a cross-room health summary: allergies by child, incident count, and incident list."""
    children = get_children()
    allergies = {}
    for c in children:
        f = c["fields"]
        allergy = f.get("allergies", "")
        if allergy and allergy.lower() not in ("none", "", "n/a"):
            allergies[f["first_name"]] = allergy

    incidents = get_incidents()
    incident_count = len(incidents)

    return {"allergies": allergies, "total_incidents": incident_count, "incidents": incidents}


# --- Health History (Health_History) ---


def get_health_history(child_id_val: int | str | None = None) -> list:
    """Return health history records, optionally filtered by child ID."""
    records = _api("GET", f"/tables/{TABLE_MAP['health_history']}/records")
    if not records:
        return []
    if child_id_val:
        return [r for r in records.get("records", []) if str(r["fields"].get("child_ref")) == str(child_id_val)]
    return records.get("records", [])


def get_vaccine_summary() -> dict:
    """Return vaccine compliance status per child (Complete / Due soon / Overdue / Unknown)."""
    records = _api("GET", f"/tables/{TABLE_MAP['health_history']}/records")
    if not records:
        return {}
    children = get_children()
    child_names = {str(c["id"]): c["fields"]["first_name"] for c in children}
    summary = {}
    for r in records.get("records", []):
        f = r["fields"]
        child_id_str = str(f.get("child_ref", ""))
        name = child_names.get(child_id_str, f.get("child_name", "Unknown"))
        vax = f.get("vaccine_status", "")
        if "OVERDUE" in vax or "overdue" in vax:
            compliance = "Overdue"
        elif "due soon" in vax.lower() or "DUE SOON" in vax:
            compliance = "Due soon"
        elif "Up to date" in vax:
            compliance = "Complete"
        else:
            compliance = "Unknown"
        summary[name] = {"compliance": compliance, "status_text": vax}
    return summary


# --- Portfolio Moments (Table14) ---


def get_portfolio_moments(child_id_val: int | str | None = None, limit: int = 20) -> list:
    """Return portfolio moments (newest first), optionally filtered by child ID."""
    records = _api("GET", f"/tables/{TABLE_MAP['portfolio']}/records")
    if not records:
        return []
    if child_id_val:
        filtered = [r for r in records.get("records", []) if str(r["fields"].get("child")) == str(child_id_val)]
    else:
        filtered = records.get("records", [])
    return sorted(filtered, key=lambda r: r["fields"].get("date", ""), reverse=True)[:limit]


def get_monthly_book(child_id_val: int | str, month: str | None = None) -> dict | None:
    """Return the monthly milestone book for *child_id_val*, newest if *month* is omitted."""
    records = _api("GET", f"/tables/{TABLE_MAP['monthly_books']}/records")
    if not records:
        return None
    for r in records.get("records", []):
        f = r["fields"]
        if str(f.get("child")) == str(child_id_val):
            if month is None or f.get("month") == month:
                return r
    return None


def get_all_monthly_books(month: str | None = None) -> list:
    """Return all monthly books, optionally filtered by *month* (YYYY-MM)."""
    records = _api("GET", f"/tables/{TABLE_MAP['monthly_books']}/records")
    if not records:
        return []
    if month:
        return [r for r in records.get("records", []) if r["fields"].get("month") == month]
    return records.get("records", [])


def add_portfolio_moment(child_id_val: int | str, date: str, moment_type: str, title: str,
                          description: str, category: str, media_url: str = "",
                          tags: str = "", staff_id: int = 1, is_highlight: bool = False) -> dict | None:
    """Create a new portfolio moment record for *child_id_val*."""
    return _api("POST", f"/tables/{TABLE_MAP['portfolio']}/records", {
        "records": [{"fields": {"child": child_id_val, "date": date, "moment_type": moment_type,
                                "title": title, "description": description, "category": category,
                                "media_url": media_url, "media_type": "",
                                "tags": tags, "staff": staff_id, "is_highlight": is_highlight}}]})


# --- Calendar / Meetings (Table16) ---


def schedule_meeting(date: str, time: str, title: str, meeting_type: str,
                     description: str = "", child_id: int | str | None = None,
                     staff_id: int = 1) -> dict | None:
    """Create a meeting record. *meeting_type* is 'staff' or 'parent_teacher'."""
    return _api("POST", f"/tables/{TABLE_MAP['meetings']}/records", {
        "records": [{"fields": {
            "date": date, "time": time, "title": title,
            "meeting_type": meeting_type, "description": description,
            "child": child_id, "staff": staff_id,
        }}]})


def get_meetings(date: str | None = None, meeting_type: str | None = None,
                 limit: int = 20) -> list:
    """Return upcoming meetings, optionally filtered by *date* (YYYY-MM-DD) or *meeting_type*."""
    records = _api("GET", f"/tables/{TABLE_MAP['meetings']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if date:
        result = [r for r in result if r["fields"].get("date") == date]
    if meeting_type:
        result = [r for r in result if r["fields"].get("meeting_type") == meeting_type]
    return sorted(result, key=lambda r: (r["fields"].get("date", ""),
                                          r["fields"].get("time", "")), reverse=True)[:limit]


def get_parent_meetings(child_id_val: int | str) -> list:
    """Return parent-teacher meetings for a specific child."""
    meetings = get_meetings(meeting_type="parent_teacher")
    return [m for m in meetings if str(m["fields"].get("child")) == str(child_id_val)]


def get_all_parent_chat_ids() -> list[tuple[int, str]]:
    """Return (chat_id, first_name) for every child with a linked parent chat_id."""
    children = get_children()
    result = []
    for c in children:
        f = c["fields"]
        chat_id = f.get("parent_chat_id")
        if chat_id:
            try:
                result.append((int(chat_id), f.get("first_name", "")))
            except (ValueError, TypeError):
                pass
    return result


# --- Announcements / Message Board (Table17) ---


def create_announcement(title: str, message: str, priority: str = "normal",
                        sent_by: int = 1) -> dict | None:
    """Create a new announcement record with today's date."""
    from datetime import datetime

    return _api("POST", f"/tables/{TABLE_MAP['announcements']}/records", {
        "records": [{"fields": {
            "title": title, "message": message, "priority": priority,
            "date": datetime.now().strftime("%Y-%m-%d"), "sent_by": sent_by,
        }}]})


def get_announcements(limit: int = 10) -> list:
    """Return recent announcements, newest first."""
    records = _api("GET", f"/tables/{TABLE_MAP['announcements']}/records")
    if not records:
        return []
    return sorted(records.get("records", []),
                  key=lambda r: r["fields"].get("date", ""), reverse=True)[:limit]


# --- Kitchen Daily Menu (Table18) & Menu Comments (Table19) ---


def log_menu_item(date: str, meal_type: str, description: str,
                  staff_id: int = 1) -> dict | None:
    """Add or update a menu item for *meal_type* on *date*.

    *meal_type* is one of: breakfast, am_snack, lunch, pm_snack, drinks.
    If a record for the same date + meal_type already exists it is updated.
    """
    # Check for existing record to update
    existing = _api("GET", f"/tables/{TABLE_MAP['menu']}/records")
    if existing:
        for r in existing.get("records", []):
            f = r["fields"]
            if f.get("date") == date and f.get("meal_type") == meal_type:
                return _api("PATCH", f"/tables/{TABLE_MAP['menu']}/records", {
                    "records": [{"id": r["id"], "fields": {"description": description,
                                                            "staff": staff_id}}]})

    return _api("POST", f"/tables/{TABLE_MAP['menu']}/records", {
        "records": [{"fields": {
            "date": date, "meal_type": meal_type, "description": description,
            "staff": staff_id,
        }}]})


def get_daily_menu(date: str) -> list:
    """Return all menu items for *date* (YYYY-MM-DD), ordered by meal_type."""
    meal_order = {"breakfast": 0, "am_snack": 1, "lunch": 2, "pm_snack": 3, "drinks": 4}
    records = _api("GET", f"/tables/{TABLE_MAP['menu']}/records")
    if not records:
        return []
    items = [r for r in records.get("records", []) if r["fields"].get("date") == date]
    return sorted(items, key=lambda r: meal_order.get(r["fields"].get("meal_type", ""), 99))


def add_menu_comment(date: str, parent_name: str, comment: str) -> dict | None:
    """Add a parent comment on a day's menu."""
    return _api("POST", f"/tables/{TABLE_MAP['menu_comments']}/records", {
        "records": [{"fields": {
            "date": date, "parent_name": parent_name, "comment": comment,
        }}]})


def get_menu_comments(date: str) -> list:
    """Return all parent comments for *date*, newest first."""
    records = _api("GET", f"/tables/{TABLE_MAP['menu_comments']}/records")
    if not records:
        return []
    comments = [r for r in records.get("records", []) if r["fields"].get("date") == date]
    return sorted(comments, key=lambda r: r.get("id", 0), reverse=True)


# --- Daily Schedule (Table20) ---

ACTIVITY_ORDER = {"nap": 0, "outdoor": 1, "class": 2, "craft": 3}


def set_daily_activity(date: str, activity_type: str, start_time: str,
                       end_time: str, description: str = "",
                       room: str = "", staff_id: int = 1) -> dict | None:
    """Add or update a daily activity block. *activity_type* is nap/outdoor/class/craft.

    Upserts: if a record with the same date + activity_type exists, it is patched.
    """
    existing = _api("GET", f"/tables/{TABLE_MAP['daily_schedule']}/records")
    if existing:
        for r in existing.get("records", []):
            f = r["fields"]
            if f.get("date") == date and f.get("activity_type") == activity_type:
                return _api("PATCH", f"/tables/{TABLE_MAP['daily_schedule']}/records", {
                    "records": [{"id": r["id"], "fields": {
                        "start_time": start_time, "end_time": end_time,
                        "description": description, "room": room, "staff": staff_id,
                    }}]})

    return _api("POST", f"/tables/{TABLE_MAP['daily_schedule']}/records", {
        "records": [{"fields": {
            "date": date, "activity_type": activity_type,
            "start_time": start_time, "end_time": end_time,
            "description": description, "room": room, "staff": staff_id,
        }}]})


def get_daily_schedule(date: str) -> list:
    """Return all activity blocks for *date*, ordered by start time within activity type order."""
    records = _api("GET", f"/tables/{TABLE_MAP['daily_schedule']}/records")
    if not records:
        return []
    items = [r for r in records.get("records", []) if r["fields"].get("date") == date]
    return sorted(items, key=lambda r: (
        ACTIVITY_ORDER.get(r["fields"].get("activity_type", ""), 99),
        r["fields"].get("start_time", ""),
    ))


# --- Contingency / Substitute Teacher Roster (Table21) ---


def add_contingency_teacher(name: str, phone: str, email: str = "",
                            rooms_qualified: str = "", notes: str = "",
                            availability: str = "") -> dict | None:
    """Add a substitute teacher to the contingency roster."""
    return _api("POST", f"/tables/{TABLE_MAP['contingency_teachers']}/records", {
        "records": [{"fields": {
            "name": name, "phone": phone, "email": email,
            "rooms_qualified": rooms_qualified, "notes": notes,
            "availability": availability,
        }}]})


def get_contingency_teachers() -> list:
    """Return all contingency/substitute teachers, sorted by name."""
    records = _api("GET", f"/tables/{TABLE_MAP['contingency_teachers']}/records")
    if not records:
        return []
    return sorted(records.get("records", []),
                  key=lambda r: r["fields"].get("name", "").lower())


def find_contingency_teachers(room: str = "") -> list:
    """Return contingency teachers qualified for *room* (substring match), or all if empty."""
    teachers = get_contingency_teachers()
    if not room:
        return teachers
    room_lower = room.lower()
    return [t for t in teachers
            if room_lower in t["fields"].get("rooms_qualified", "").lower()]


# --- Guardians / Custody / Pickup (Tables 22-24) ---


def create_guardian(fields: dict) -> dict | None:
    """Create a guardian record and return the created record payload."""
    result = _api("POST", f"/tables/{TABLE_MAP['guardians']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def link_child_guardian(child_id_val: int | str, guardian_id_val: int | str,
                        legal_status: str = "custodial", pickup_allowed: bool = True,
                        pickup_password: str = "", court_order_url: str = "",
                        notes: str = "") -> dict | None:
    """Create a child-guardian linkage with custody and pickup controls."""
    result = _api("POST", f"/tables/{TABLE_MAP['child_guardians']}/records", {
        "records": [{"fields": {
            "child": _as_grist_id(child_id_val),
            "guardian": _as_grist_id(guardian_id_val),
            "legal_status": legal_status,
            "pickup_allowed": pickup_allowed,
            "pickup_password": pickup_password,
            "court_order_url": court_order_url,
            "notes": notes,
        }}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_child_guardian_links(child_id_val: int | str) -> list:
    """Return child-guardian link records for a child."""
    records = _api("GET", f"/tables/{TABLE_MAP['child_guardians']}/records")
    if not records:
        return []
    return [r for r in records.get("records", [])
            if str(r["fields"].get("child")) == str(child_id_val)]


def get_guardian_by_id(guardian_id_val: int | str) -> dict | None:
    """Return a guardian record by record ID."""
    records = _api("GET", f"/tables/{TABLE_MAP['guardians']}/records")
    if not records:
        return None
    for r in records.get("records", []):
        if str(r.get("id")) == str(guardian_id_val):
            return r
    return None


def get_child_guardians(child_id_val: int | str) -> list:
    """Return merged guardian + linkage metadata for a child."""
    links = get_child_guardian_links(child_id_val)
    if not links:
        return []
    guardian_ids = {str(link["fields"].get("guardian")) for link in links}
    guardians_resp = _api("GET", f"/tables/{TABLE_MAP['guardians']}/records")
    guardians = guardians_resp.get("records", []) if guardians_resp else []
    by_id = {str(g.get("id")): g for g in guardians if str(g.get("id")) in guardian_ids}

    merged = []
    for link in links:
        guardian_id_str = str(link["fields"].get("guardian"))
        merged.append({
            "link_id": link.get("id"),
            "link": link["fields"],
            "guardian_id": guardian_id_str,
            "guardian": by_id.get(guardian_id_str, {}).get("fields", {}),
        })
    return merged


def update_child_guardian_link(link_id_val: int | str, fields: dict) -> dict | None:
    """Patch fields on a Child_Guardians link record."""
    return _api("PATCH", f"/tables/{TABLE_MAP['child_guardians']}/records", {
        "records": [{"id": _as_grist_id(link_id_val), "fields": fields}]})


def get_pickup_events(child_id_val: int | str | None = None,
                      approved: bool | None = None) -> list:
    """Return pickup events, optionally filtered by child and approval status."""
    records = _api("GET", f"/tables/{TABLE_MAP['pickup_events']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if child_id_val is not None:
        result = [r for r in result if str(r["fields"].get("child")) == str(child_id_val)]
    if approved is not None:
        result = [r for r in result if bool(r["fields"].get("approved")) == bool(approved)]
    return result


def add_pickup_event(child_id_val: int | str, requested_by_guardian: int | str | None,
                     approved: bool, approved_by_staff: int | str | None = None,
                     method: str = "manual", denial_reason: str = "",
                     timestamp: str | None = None, denial_code: str = "",
                     override_used: bool = False, override_reason: str = "",
                     override_approved_by: int | str | None = None) -> dict | None:
    """Create a pickup verification/audit event."""
    from datetime import datetime
    event_time = timestamp or datetime.utcnow().isoformat(timespec="seconds")
    return _api("POST", f"/tables/{TABLE_MAP['pickup_events']}/records", {
        "records": [{"fields": {
            "child": _as_grist_id(child_id_val),
            "requested_by_guardian": _as_grist_id(requested_by_guardian),
            "approved": approved,
            "approved_by_staff": _as_grist_id(approved_by_staff),
            "method": method,
            "timestamp": event_time,
            "denial_reason": denial_reason,
            "denial_code": denial_code,
            "override_used": override_used,
            "override_reason": override_reason,
            "override_approved_by": _as_grist_id(override_approved_by),
        }}]})


# --- Billing / Collections (Tables 25-27) ---


def create_billing_account(fields: dict) -> dict | None:
    """Create a billing account record."""
    result = _api("POST", f"/tables/{TABLE_MAP['billing_accounts']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_billing_accounts(child_id_val: int | str | None = None) -> list:
    """Return billing accounts, optionally filtered by child."""
    records = _api("GET", f"/tables/{TABLE_MAP['billing_accounts']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if child_id_val is not None:
        result = [r for r in result if str(r["fields"].get("child")) == str(child_id_val)]
    return result


def create_billing_account_party(fields: dict) -> dict | None:
    """Create a billing account party rule (split payer)."""
    result = _api("POST", f"/tables/{TABLE_MAP['billing_account_parties']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_billing_account_parties(account_id_val: int | str | None = None,
                                status: str | None = None) -> list:
    """Return billing account party rules, optionally filtered by account/status."""
    records = _api("GET", f"/tables/{TABLE_MAP['billing_account_parties']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if account_id_val is not None:
        result = [r for r in result if str(r["fields"].get("account")) == str(account_id_val)]
    if status:
        result = [r for r in result if str(r["fields"].get("status", "")).lower() == status.lower()]
    return result


def update_billing_account_party(party_id_val: int | str, fields: dict) -> dict | None:
    """Patch fields on a billing account party rule."""
    return _api("PATCH", f"/tables/{TABLE_MAP['billing_account_parties']}/records", {
        "records": [{"id": _as_grist_id(party_id_val), "fields": fields}]})


def create_autopay_attempt(fields: dict) -> dict | None:
    """Create an autopay attempt audit record."""
    result = _api("POST", f"/tables/{TABLE_MAP['autopay_attempts']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_autopay_attempts(invoice_id_val: int | str | None = None,
                         party_id_val: int | str | None = None) -> list:
    """Return autopay attempts, optionally filtered by invoice and/or party."""
    records = _api("GET", f"/tables/{TABLE_MAP['autopay_attempts']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if invoice_id_val is not None:
        result = [r for r in result if str(r["fields"].get("invoice")) == str(invoice_id_val)]
    if party_id_val is not None:
        result = [r for r in result if str(r["fields"].get("party")) == str(party_id_val)]
    return result


def create_invoices(invoice_fields: list[dict]) -> dict | None:
    """Create one or more invoices from a list of fields dicts."""
    return _api("POST", f"/tables/{TABLE_MAP['invoices']}/records", {
        "records": [{"fields": fields} for fields in invoice_fields]})


def get_invoices(status: str | None = None, account_id: int | str | None = None) -> list:
    """Return invoices, optionally filtered by status and/or account."""
    records = _api("GET", f"/tables/{TABLE_MAP['invoices']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if status:
        result = [r for r in result if str(r["fields"].get("status", "")).lower() == status.lower()]
    if account_id is not None:
        result = [r for r in result if str(r["fields"].get("account")) == str(account_id)]
    return result


def get_invoice(invoice_id_val: int | str) -> dict | None:
    """Return a single invoice by ID."""
    invoices = get_invoices()
    for inv in invoices:
        if str(inv.get("id")) == str(invoice_id_val):
            return inv
    return None


def add_payment(fields: dict) -> dict | None:
    """Create a payment record."""
    result = _api("POST", f"/tables/{TABLE_MAP['payments']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_payments(invoice_id_val: int | str | None = None) -> list:
    """Return payment records, optionally filtered by invoice."""
    records = _api("GET", f"/tables/{TABLE_MAP['payments']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if invoice_id_val is not None:
        result = [r for r in result if str(r["fields"].get("invoice")) == str(invoice_id_val)]
    return result


def update_invoice(invoice_id_val: int | str, fields: dict) -> dict | None:
    """Patch fields on an invoice."""
    return _api("PATCH", f"/tables/{TABLE_MAP['invoices']}/records", {
        "records": [{"id": _as_grist_id(invoice_id_val), "fields": fields}]})


# --- Waitlist / Enrollment CRM input (Table 28) ---


def get_waitlist(status: str | None = None) -> list:
    """Return waitlist records, optionally filtered by status."""
    records = _api("GET", f"/tables/{TABLE_MAP['waitlist']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if status:
        result = [r for r in result if str(r["fields"].get("status", "")).lower() == status.lower()]
    return result


def add_waitlist_entry(fields: dict) -> dict | None:
    """Create a waitlist entry."""
    result = _api("POST", f"/tables/{TABLE_MAP['waitlist']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def update_waitlist_entry(entry_id_val: int | str, fields: dict) -> dict | None:
    """Patch a waitlist entry."""
    return _api("PATCH", f"/tables/{TABLE_MAP['waitlist']}/records", {
        "records": [{"id": _as_grist_id(entry_id_val), "fields": fields}]})


# --- Compliance checklists (Tables 31-33) ---


def add_medication_log(fields: dict) -> dict | None:
    """Create a medication administration log record."""
    result = _api("POST", f"/tables/{TABLE_MAP['medication_logs']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_medication_logs(child_id_val: int | str | None = None) -> list:
    """Return medication logs, optionally filtered by child."""
    records = _api("GET", f"/tables/{TABLE_MAP['medication_logs']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if child_id_val is not None:
        result = [r for r in result if str(r["fields"].get("child")) == str(child_id_val)]
    return result


def add_sanitation_check(fields: dict) -> dict | None:
    """Create a sanitation checklist record."""
    result = _api("POST", f"/tables/{TABLE_MAP['sanitation_checks']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_sanitation_checks(status: str | None = None) -> list:
    """Return sanitation checks, optionally filtered by status."""
    records = _api("GET", f"/tables/{TABLE_MAP['sanitation_checks']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if status:
        result = [r for r in result if str(r["fields"].get("status", "")).lower() == status.lower()]
    return result


def add_sleep_safety_check(fields: dict) -> dict | None:
    """Create a sleep safety check record."""
    result = _api("POST", f"/tables/{TABLE_MAP['sleep_safety_checks']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_sleep_safety_checks(child_id_val: int | str | None = None,
                            status: str | None = None) -> list:
    """Return sleep safety checks, optionally filtered by child and/or status."""
    records = _api("GET", f"/tables/{TABLE_MAP['sleep_safety_checks']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if child_id_val is not None:
        result = [r for r in result if str(r["fields"].get("child")) == str(child_id_val)]
    if status:
        result = [r for r in result if str(r["fields"].get("status", "")).lower() == status.lower()]
    return result


# --- Regulatory copilot ingestion + risk scoring (Tables 34-35) ---


def create_regulatory_rule(fields: dict) -> dict | None:
    """Create a regulatory rule version row."""
    result = _api("POST", f"/tables/{TABLE_MAP['regulatory_rules']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def update_regulatory_rule(rule_row_id_val: int | str, fields: dict) -> dict | None:
    """Patch fields on a regulatory rule row."""
    return _api("PATCH", f"/tables/{TABLE_MAP['regulatory_rules']}/records", {
        "records": [{"id": _as_grist_id(rule_row_id_val), "fields": fields}]})


def get_regulatory_rules(rule_key: str | None = None, jurisdiction: str | None = None,
                         category: str | None = None, active_only: bool = True) -> list:
    """Return regulatory rules, optionally filtered by key/jurisdiction/category/active."""
    records = _api("GET", f"/tables/{TABLE_MAP['regulatory_rules']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if rule_key:
        key = rule_key.strip().lower()
        result = [r for r in result if str(r["fields"].get("rule_key", "")).strip().lower() == key]
    if jurisdiction:
        region = jurisdiction.strip().lower()
        result = [r for r in result if str(r["fields"].get("jurisdiction", "")).strip().lower() == region]
    if category:
        cat = category.strip().lower()
        result = [r for r in result if str(r["fields"].get("category", "")).strip().lower() == cat]
    if active_only:
        result = [r for r in result if bool(r["fields"].get("active", False))]
    return result


def get_regulatory_rule_versions(rule_key: str) -> list:
    """Return all versions for a rule_key, newest effective date first."""
    versions = get_regulatory_rules(rule_key=rule_key, active_only=False)
    return sorted(
        versions,
        key=lambda r: (str(r["fields"].get("effective_date", "")), str(r["fields"].get("ingested_at", ""))),
        reverse=True,
    )


def find_regulatory_rule_version(rule_key: str, version: str) -> dict | None:
    """Return a specific regulatory rule version row by key+version."""
    candidates = get_regulatory_rules(rule_key=rule_key, active_only=False)
    version_lc = str(version).strip().lower()
    for row in candidates:
        if str(row["fields"].get("version", "")).strip().lower() == version_lc:
            return row
    return None


def create_regulatory_risk_assessment(fields: dict) -> dict | None:
    """Create a regulatory risk assessment row."""
    result = _api("POST", f"/tables/{TABLE_MAP['regulatory_risk_assessments']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_regulatory_risk_assessments(status: str | None = None,
                                    category: str | None = None) -> list:
    """Return risk assessments, optionally filtered by status/category."""
    records = _api("GET", f"/tables/{TABLE_MAP['regulatory_risk_assessments']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if status:
        status_lc = status.strip().lower()
        result = [r for r in result if str(r["fields"].get("status", "")).strip().lower() == status_lc]
    if category:
        cat_lc = category.strip().lower()
        result = [r for r in result if str(r["fields"].get("category", "")).strip().lower() == cat_lc]
    return result


# --- Ops workflow freshness heartbeat (Table 36) ---


def get_workflow_heartbeats(workflow_key: str | None = None) -> list:
    """Return workflow heartbeat rows, optionally filtered by workflow_key."""
    records = _api("GET", f"/tables/{TABLE_MAP['workflow_heartbeat']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if workflow_key:
        key = str(workflow_key).strip().lower()
        result = [r for r in result if str(r["fields"].get("workflow_key", "")).strip().lower() == key]
    return result


def upsert_workflow_heartbeat(workflow_key: str, fields: dict) -> dict | None:
    """Create or update heartbeat row keyed by workflow_key."""
    if not workflow_key:
        return None
    existing = get_workflow_heartbeats(workflow_key=workflow_key)
    if existing:
        row_id = existing[0].get("id")
        return _api("PATCH", f"/tables/{TABLE_MAP['workflow_heartbeat']}/records", {
            "records": [{"id": _as_grist_id(row_id), "fields": fields}]})
    return _api("POST", f"/tables/{TABLE_MAP['workflow_heartbeat']}/records", {
        "records": [{"fields": {"workflow_key": workflow_key, **fields}}]})


# --- Marketing / SEO / reviews / insurance / competitive (Tables 37-40) ---


def create_marketing_lead(fields: dict) -> dict | None:
    """Create a marketing lead row."""
    result = _api("POST", f"/tables/{TABLE_MAP['marketing_leads']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_marketing_leads(channel: str | None = None, status: str | None = None) -> list:
    """Return marketing leads, optionally filtered by channel/status."""
    records = _api("GET", f"/tables/{TABLE_MAP['marketing_leads']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if channel:
        channel_lc = str(channel).strip().lower()
        result = [r for r in result if str(r.get("fields", {}).get("channel", "")).strip().lower() == channel_lc]
    if status:
        status_lc = str(status).strip().lower()
        result = [r for r in result if str(r.get("fields", {}).get("status", "")).strip().lower() == status_lc]
    return result


def create_review_request(fields: dict) -> dict | None:
    """Create a review request/event row."""
    result = _api("POST", f"/tables/{TABLE_MAP['review_requests']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_review_requests(platform: str | None = None, status: str | None = None) -> list:
    """Return review requests, optionally filtered by platform/status."""
    records = _api("GET", f"/tables/{TABLE_MAP['review_requests']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if platform:
        platform_lc = str(platform).strip().lower()
        result = [r for r in result if str(r.get("fields", {}).get("platform", "")).strip().lower() == platform_lc]
    if status:
        status_lc = str(status).strip().lower()
        result = [r for r in result if str(r.get("fields", {}).get("status", "")).strip().lower() == status_lc]
    return result


def create_insurance_policy(fields: dict) -> dict | None:
    """Create an insurance policy row."""
    result = _api("POST", f"/tables/{TABLE_MAP['insurance_policies']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_insurance_policies(status: str | None = None) -> list:
    """Return insurance policy rows, optionally filtered by status."""
    records = _api("GET", f"/tables/{TABLE_MAP['insurance_policies']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if status:
        status_lc = str(status).strip().lower()
        result = [r for r in result if str(r.get("fields", {}).get("status", "")).strip().lower() == status_lc]
    return result


def update_insurance_policy(policy_id_val: int | str, fields: dict) -> dict | None:
    """Patch fields on an insurance policy row."""
    return _api("PATCH", f"/tables/{TABLE_MAP['insurance_policies']}/records", {
        "records": [{"id": _as_grist_id(policy_id_val), "fields": fields}]})


def create_competitor_snapshot(fields: dict) -> dict | None:
    """Create a competitor snapshot row."""
    result = _api("POST", f"/tables/{TABLE_MAP['competitor_snapshots']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_competitor_snapshots(competitor_name: str | None = None) -> list:
    """Return competitor snapshots, optionally filtered by competitor_name."""
    records = _api("GET", f"/tables/{TABLE_MAP['competitor_snapshots']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if competitor_name:
        name_lc = str(competitor_name).strip().lower()
        result = [r for r in result if str(r.get("fields", {}).get("competitor_name", "")).strip().lower() == name_lc]
    return result


def create_marketing_channel_spend(fields: dict) -> dict | None:
    """Create a marketing channel spend row."""
    result = _api("POST", f"/tables/{TABLE_MAP['marketing_channel_spend']}/records", {
        "records": [{"fields": fields}]})
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def get_marketing_channel_spend(channel: str | None = None,
                                campaign: str | None = None,
                                period_month: str | None = None) -> list:
    """Return marketing spend rows, optionally filtered by channel/campaign/month."""
    records = _api("GET", f"/tables/{TABLE_MAP['marketing_channel_spend']}/records")
    if not records:
        return []
    result = records.get("records", [])
    if channel:
        channel_lc = str(channel).strip().lower()
        result = [r for r in result if str(r.get("fields", {}).get("channel", "")).strip().lower() == channel_lc]
    if campaign:
        campaign_lc = str(campaign).strip().lower()
        result = [r for r in result if str(r.get("fields", {}).get("campaign", "")).strip().lower() == campaign_lc]
    if period_month:
        month_lc = str(period_month).strip().lower()
        result = [r for r in result if str(r.get("fields", {}).get("period_month", "")).strip().lower() == month_lc]
    return result
