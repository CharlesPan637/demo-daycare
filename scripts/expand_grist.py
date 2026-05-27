#!/usr/bin/env python3
"""Expand Grist with staffing, subsidy, enrollment, and compliance data models."""
import os, sys, json
import requests

API_KEY = os.getenv("GRIST_API_KEY")
BASE_URL = os.getenv("GRIST_BASE_URL", "http://127.0.0.1:8096")
DOC_ID = os.getenv("GRIST_DOC_ID", "new~77esxLe65dVuwRr3hSXA52~5")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def api(method, path, data=None):
    url = f"{BASE_URL}/api/docs/{DOC_ID}{path}"
    kwargs = {"headers": HEADERS}
    if data is not None:
        kwargs["json"] = data
    r = requests.request(method, url, **kwargs)
    if r.status_code >= 400:
        print(f"  ERROR {method} {path}: {r.status_code} {r.text[:300]}")
        return None
    return r.json() if r.text else None

def add_table(name, columns):
    print(f"  Creating table: {name}")
    result = api("POST", "/tables", {"tables": [{"columns": columns, "tableName": name}]})
    if result:
        tid = result["tables"][0]["id"]
        print(f"    ID: {tid}")
        return tid
    return None

def add_records(table_id, records):
    return api("POST", f"/tables/{table_id}/records", {"records": records})

# ── Staff_Availability ──────────────────────────────────────
print("\n=== Staff Availability ===")
staff_avail_cols = [
    {"id": "staff", "type": "Ref:Staff"},
    {"id": "day_of_week", "type": "Text"},
    {"id": "start_time", "type": "Text"},
    {"id": "end_time", "type": "Text"},
    {"id": "rooms_qualified", "type": "Text"},
    {"id": "is_on_call", "type": "Bool"},
    {"id": "phone", "type": "Text"},
    {"id": "notes", "type": "Text"},
]
sa_id = add_table("Staff_Availability", staff_avail_cols)

sa_data = [
    {"fields": {"staff": 1, "day_of_week": "Monday", "start_time": "07:30", "end_time": "16:00",
     "rooms_qualified": "Infant, Toddler, Preschool", "is_on_call": False,
     "phone": "(555) 234-1001", "notes": "Lead teacher, opens center"}},
    {"fields": {"staff": 1, "day_of_week": "Tuesday", "start_time": "07:30", "end_time": "16:00",
     "rooms_qualified": "Infant, Toddler, Preschool", "is_on_call": False,
     "phone": "(555) 234-1001", "notes": ""}},
    {"fields": {"staff": 1, "day_of_week": "Wednesday", "start_time": "07:30", "end_time": "16:00",
     "rooms_qualified": "Infant, Toddler, Preschool", "is_on_call": True,
     "phone": "(555) 234-1001", "notes": "On call for afternoon coverage"}},
    {"fields": {"staff": 1, "day_of_week": "Thursday", "start_time": "07:30", "end_time": "16:00",
     "rooms_qualified": "Infant, Toddler, Preschool", "is_on_call": False,
     "phone": "(555) 234-1001", "notes": ""}},
    {"fields": {"staff": 1, "day_of_week": "Friday", "start_time": "07:30", "end_time": "16:00",
     "rooms_qualified": "Infant, Toddler, Preschool", "is_on_call": False,
     "phone": "(555) 234-1001", "notes": ""}},
    {"fields": {"staff": 2, "day_of_week": "Monday", "start_time": "08:00", "end_time": "16:00",
     "rooms_qualified": "Toddler, Preschool, Pre-K", "is_on_call": False,
     "phone": "(555) 234-1002", "notes": "Spanish bilingual"}},
    {"fields": {"staff": 2, "day_of_week": "Tuesday", "start_time": "08:00", "end_time": "16:00",
     "rooms_qualified": "Toddler, Preschool, Pre-K", "is_on_call": True,
     "phone": "(555) 234-1002", "notes": "On call for morning coverage"}},
    {"fields": {"staff": 2, "day_of_week": "Wednesday", "start_time": "08:00", "end_time": "16:00",
     "rooms_qualified": "Toddler, Preschool, Pre-K", "is_on_call": False,
     "phone": "(555) 234-1002", "notes": ""}},
    {"fields": {"staff": 2, "day_of_week": "Thursday", "start_time": "08:00", "end_time": "16:00",
     "rooms_qualified": "Toddler, Preschool, Pre-K", "is_on_call": False,
     "phone": "(555) 234-1002", "notes": ""}},
    {"fields": {"staff": 2, "day_of_week": "Friday", "start_time": "08:00", "end_time": "16:00",
     "rooms_qualified": "Toddler, Preschool, Pre-K", "is_on_call": True,
     "phone": "(555) 234-1002", "notes": "On call Friday afternoons"}},
    {"fields": {"staff": 3, "day_of_week": "Monday", "start_time": "09:00", "end_time": "15:00",
     "rooms_qualified": "All rooms (admin)", "is_on_call": True,
     "phone": "(555) 234-1003", "notes": "Admin float — can cover any room"}},
    {"fields": {"staff": 3, "day_of_week": "Tuesday", "start_time": "09:00", "end_time": "15:00",
     "rooms_qualified": "All rooms (admin)", "is_on_call": False,
     "phone": "(555) 234-1003", "notes": ""}},
    {"fields": {"staff": 3, "day_of_week": "Wednesday", "start_time": "09:00", "end_time": "15:00",
     "rooms_qualified": "All rooms (admin)", "is_on_call": False,
     "phone": "(555) 234-1003", "notes": ""}},
    {"fields": {"staff": 3, "day_of_week": "Thursday", "start_time": "09:00", "end_time": "15:00",
     "rooms_qualified": "All rooms (admin)", "is_on_call": True,
     "phone": "(555) 234-1003", "notes": "Admin on call Thursday"}},
    {"fields": {"staff": 3, "day_of_week": "Friday", "start_time": "09:00", "end_time": "15:00",
     "rooms_qualified": "All rooms (admin)", "is_on_call": False,
     "phone": "(555) 234-1003", "notes": ""}},
]
add_records(sa_id, sa_data)
print("  15 availability records added (3 staff x 5 days)")

# ── Room_Ratios ──────────────────────────────────────────────
print("\n=== Room Ratios ===")
ratio_cols = [
    {"id": "room_name", "type": "Text"},
    {"id": "age_group", "type": "Text"},
    {"id": "min_staff", "type": "Int"},
    {"id": "max_children", "type": "Int"},
    {"id": "staff_child_ratio", "type": "Text"},
    {"id": "current_enrolled", "type": "Int"},
    {"id": "notes", "type": "Text"},
]
rr_id = add_table("Room_Ratios", ratio_cols)

rr_data = [
    {"fields": {"room_name": "Infant Room", "age_group": "0-18 months", "min_staff": 1,
     "max_children": 4, "staff_child_ratio": "1:4", "current_enrolled": 0,
     "notes": "State ratio: 1:4 for infants"}},
    {"fields": {"room_name": "Toddler Room", "age_group": "18-36 months", "min_staff": 1,
     "max_children": 6, "staff_child_ratio": "1:6", "current_enrolled": 2,
     "notes": "Sophia (2), Oliver (2). State ratio: 1:6"}},
    {"fields": {"room_name": "Preschool Room", "age_group": "3-4 years", "min_staff": 1,
     "max_children": 10, "staff_child_ratio": "1:10", "current_enrolled": 4,
     "notes": "Emma (3), Noah (3), Isabella (3), Ava (4). State ratio: 1:10"}},
    {"fields": {"room_name": "Pre-K Room", "age_group": "4-5 years", "min_staff": 1,
     "max_children": 12, "staff_child_ratio": "1:12", "current_enrolled": 2,
     "notes": "Liam (4), Ethan (4). State ratio: 1:12"}},
]
add_records(rr_id, rr_data)
print("  4 room ratio records added")

# ── Subsidies ────────────────────────────────────────────────
print("\n=== Subsidies ===")
subsidy_cols = [
    {"id": "child", "type": "Ref:Children"},
    {"id": "program_name", "type": "Text"},
    {"id": "monthly_amount", "type": "Int"},
    {"id": "reauthorization_date", "type": "Text"},
    {"id": "status", "type": "Text"},
    {"id": "case_worker", "type": "Text"},
    {"id": "case_worker_phone", "type": "Text"},
    {"id": "notes", "type": "Text"},
]
sub_id = add_table("Subsidies", subsidy_cols)

sub_data = [
    {"fields": {"child": 1, "program_name": "CCAP State Subsidy", "monthly_amount": 850,
     "reauthorization_date": "2026-06-15", "status": "Active",
     "case_worker": "Janet Miller", "case_worker_phone": "(555) 456-7001",
     "notes": "Reauthorization requires updated income verification"}},
    {"fields": {"child": 3, "program_name": "CCAP State Subsidy", "monthly_amount": 850,
     "reauthorization_date": "2026-07-01", "status": "Active",
     "case_worker": "Janet Miller", "case_worker_phone": "(555) 456-7001",
     "notes": ""}},
    {"fields": {"child": 5, "program_name": "Head Start (Federal)", "monthly_amount": 1100,
     "reauthorization_date": "2026-08-15", "status": "Active",
     "case_worker": "Robert Kim", "case_worker_phone": "(555) 456-7002",
     "notes": "Annual recertification required"}},
    {"fields": {"child": 7, "program_name": "CCAP State Subsidy", "monthly_amount": 850,
     "reauthorization_date": "2026-06-05", "status": "Active",
     "case_worker": "Janet Miller", "case_worker_phone": "(555) 456-7001",
     "notes": "⚠ Due in 9 days — needs renewal paperwork"}},
]
add_records(sub_id, sub_data)
print("  4 subsidy records added (1 urgent)")

# ── Enrollment_History ──────────────────────────────────────
print("\n=== Enrollment History ===")
enroll_cols = [
    {"id": "month", "type": "Text"},
    {"id": "total_enrolled", "type": "Int"},
    {"id": "new_enrollments", "type": "Int"},
    {"id": "departures", "type": "Int"},
    {"id": "waitlist_count", "type": "Int"},
    {"id": "monthly_revenue", "type": "Int"},
    {"id": "notes", "type": "Text"},
]
eh_id = add_table("Enrollment_History", enroll_cols)

eh_data = [
    {"fields": {"month": "2026-01", "total_enrolled": 6, "new_enrollments": 1,
     "departures": 0, "waitlist_count": 3, "monthly_revenue": 22500,
     "notes": "Sophia enrolled"}},
    {"fields": {"month": "2026-02", "total_enrolled": 6, "new_enrollments": 0,
     "departures": 0, "waitlist_count": 4, "monthly_revenue": 22500,
     "notes": "Stable month"}},
    {"fields": {"month": "2026-03", "total_enrolled": 7, "new_enrollments": 1,
     "departures": 0, "waitlist_count": 4, "monthly_revenue": 26000,
     "notes": "Oliver enrolled"}},
    {"fields": {"month": "2026-04", "total_enrolled": 7, "new_enrollments": 0,
     "departures": 0, "waitlist_count": 3, "monthly_revenue": 26000,
     "notes": "2 families on summer break notice"}},
    {"fields": {"month": "2026-05", "total_enrolled": 8, "new_enrollments": 1,
     "departures": 0, "waitlist_count": 5, "monthly_revenue": 29500,
     "notes": "Full capacity. Summer decline warning: 2 families reducing to part-time June-Aug"}},
]
add_records(eh_id, eh_data)
print("  5 months of enrollment history added")

# ── Incidents ────────────────────────────────────────────────
print("\n=== Incidents ===")
incident_cols = [
    {"id": "child", "type": "Ref:Children"},
    {"id": "date", "type": "Text"},
    {"id": "time", "type": "Text"},
    {"id": "incident_type", "type": "Text"},
    {"id": "description", "type": "Text"},
    {"id": "action_taken", "type": "Text"},
    {"id": "staff", "type": "Ref:Staff"},
    {"id": "parent_notified", "type": "Bool"},
    {"id": "parent_notified_time", "type": "Text"},
    {"id": "follow_up_needed", "type": "Bool"},
]
inc_id = add_table("Incidents", incident_cols)

inc_data = [
    {"fields": {"child": 2, "date": "2026-05-20", "time": "10:15", "incident_type": "Minor Injury",
     "description": "Liam scraped his knee on the playground. Small abrasion, no bleeding.",
     "action_taken": "Cleaned with antiseptic wipe, applied bandage. Child resumed play immediately.",
     "staff": 2, "parent_notified": True, "parent_notified_time": "10:20", "follow_up_needed": False}},
    {"fields": {"child": 6, "date": "2026-05-24", "time": "09:45", "incident_type": "Behavioral",
     "description": "Oliver pushed another child during free play after dispute over toy.",
     "action_taken": "Staff intervened, redirected both children. Oliver was upset but calmed after 5 min of 1:1 time.",
     "staff": 1, "parent_notified": True, "parent_notified_time": "16:00", "follow_up_needed": False}},
]
add_records(inc_id, inc_data)
print("  2 incident records added")

print(f"\n✅ Expansion complete. New tables added to doc {DOC_ID}")
print("Tables: Staff_Availability, Room_Ratios, Subsidies, Enrollment_History, Incidents")
