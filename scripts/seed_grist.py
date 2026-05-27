#!/usr/bin/env python3
"""Seed Grist with demo daycare data."""
import os, sys, json, time
import requests

API_KEY = os.getenv("GRIST_API_KEY")
BASE_URL = os.getenv("GRIST_BASE_URL", "http://127.0.0.1:8096")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

def api(method, path, data=None):
    url = f"{BASE_URL}/api{path}"
    kwargs = {"headers": HEADERS}
    if data is not None:
        kwargs["json"] = data
    r = requests.request(method, url, **kwargs)
    if r.status_code >= 400:
        print(f"  ERROR {method} {path}: {r.status_code} {r.text[:200]}")
        return None
    return r.json() if r.text else None

# --- Create document ---
print("Creating Grist document...")
doc_id = api("POST", "/docs", {"name": "Sunshine Sprouts Daycare"})
if not doc_id:
    print("Failed to create document")
    sys.exit(1)
# Grist returns doc ID as a plain string
if isinstance(doc_id, dict):
    doc_id = doc_id.get("id", "")
print(f"  Created document: {doc_id}")

# --- Helper to add a table with columns ---
def add_table(table_name, columns):
    """columns: list of {'id': str, 'type': str}"""
    print(f"  Adding table: {table_name}")
    # Create table
    result = api("POST", f"/docs/{doc_id}/tables", {"tables": [{"columns": columns, "tableName": table_name}]})
    if result:
        table_id = result["tables"][0]["id"]
        print(f"    Table ID: {table_id}")
        return table_id
    return None

# --- Helper to add records ---
def add_records(table_id, records):
    """records: list of dicts with 'fields' key"""
    result = api("POST", f"/docs/{doc_id}/tables/{table_id}/records", {"records": records})
    return result

# --- Create tables ---
children_cols = [
    {"id": "first_name", "type": "Text"},
    {"id": "last_name", "type": "Text"},
    {"id": "age", "type": "Int"},
    {"id": "age_group", "type": "Text"},
    {"id": "allergies", "type": "Text"},
    {"id": "medications", "type": "Text"},
    {"id": "emergency_contact", "type": "Text"},
    {"id": "emergency_phone", "type": "Text"},
    {"id": "enrollment_date", "type": "Text"},
    {"id": "status", "type": "Text"},
    {"id": "notes", "type": "Text"},
]
children_id = add_table("Children", children_cols)

staff_cols = [
    {"id": "first_name", "type": "Text"},
    {"id": "last_name", "type": "Text"},
    {"id": "role", "type": "Text"},
    {"id": "specialization", "type": "Text"},
    {"id": "certifications", "type": "Text"},
    {"id": "phone", "type": "Text"},
    {"id": "email", "type": "Text"},
]
staff_id = add_table("Staff", staff_cols)

attendance_cols = [
    {"id": "child", "type": "Ref:Children"},
    {"id": "date", "type": "Text"},
    {"id": "check_in", "type": "Text"},
    {"id": "check_out", "type": "Text"},
    {"id": "staff", "type": "Ref:Staff"},
    {"id": "notes", "type": "Text"},
]
attendance_id = add_table("Attendance", attendance_cols)

activities_cols = [
    {"id": "title", "type": "Text"},
    {"id": "description", "type": "Text"},
    {"id": "activity_date", "type": "Text"},
    {"id": "start_time", "type": "Text"},
    {"id": "end_time", "type": "Text"},
    {"id": "location", "type": "Text"},
    {"id": "staff_lead", "type": "Ref:Staff"},
    {"id": "max_children", "type": "Int"},
]
activities_id = add_table("Activities", activities_cols)

milestones_cols = [
    {"id": "child", "type": "Ref:Children"},
    {"id": "date", "type": "Text"},
    {"id": "category", "type": "Text"},
    {"id": "description", "type": "Text"},
    {"id": "staff", "type": "Ref:Staff"},
    {"id": "tags", "type": "Text"},
    {"id": "ai_generated", "type": "Bool"},
]
milestones_id = add_table("Milestones", milestones_cols)

reports_cols = [
    {"id": "child", "type": "Ref:Children"},
    {"id": "date", "type": "Text"},
    {"id": "breakfast", "type": "Text"},
    {"id": "lunch", "type": "Text"},
    {"id": "snack", "type": "Text"},
    {"id": "nap_start", "type": "Text"},
    {"id": "nap_end", "type": "Text"},
    {"id": "mood", "type": "Text"},
    {"id": "activities_summary", "type": "Text"},
    {"id": "milestone_notes", "type": "Text"},
]
reports_id = add_table("Daily_Reports", reports_cols)

if not all([children_id, staff_id, attendance_id, activities_id, milestones_id, reports_id]):
    print("ERROR: Failed to create one or more tables")
    sys.exit(1)

# --- Populate demo data ---

# Staff
print("\nSeeding staff...")
staff_data = [
    {"fields": {"first_name": "Ms. Rachel", "last_name": "Green", "role": "Lead Teacher",
     "specialization": "Early literacy, ECE certified", "certifications": "ECE Level 3",
     "phone": "(555) 234-1001", "email": "rachel@sunshinesprouts.edu"}},
    {"fields": {"first_name": "Mr. Carlos", "last_name": "Ruiz", "role": "Assistant Teacher",
     "specialization": "STEM activities, bilingual", "certifications": "ECE Level 1, Bilingual EN/ES",
     "phone": "(555) 234-1002", "email": "carlos@sunshinesprouts.edu"}},
    {"fields": {"first_name": "Ms. Jessica", "last_name": "Park", "role": "Aide/Admin",
     "specialization": "Admin, parent communication", "certifications": "Admin credential",
     "phone": "(555) 234-1003", "email": "jessica@sunshinesprouts.edu"}},
]
add_records(staff_id, staff_data)
print("  3 staff added")

# Children
print("Seeding children...")
children_data = [
    {"fields": {"first_name": "Emma", "last_name": "Johnson", "age": 3, "age_group": "Preschool",
     "allergies": "None", "medications": "", "emergency_contact": "Sarah Johnson (mother)",
     "emergency_phone": "(555) 345-0001", "enrollment_date": "2025-08-15", "status": "Active",
     "notes": "Loves art, shy at drop-off"}},
    {"fields": {"first_name": "Liam", "last_name": "Martinez", "age": 4, "age_group": "Pre-K",
     "allergies": "Peanuts (severe, EpiPen on site)", "medications": "EpiPen",
     "emergency_contact": "Maria Martinez (mother)", "emergency_phone": "(555) 345-0002",
     "enrollment_date": "2025-06-01", "status": "Active",
     "notes": "High energy, advanced vocabulary"}},
    {"fields": {"first_name": "Sophia", "last_name": "Chen", "age": 2, "age_group": "Toddler",
     "allergies": "Dairy", "medications": "", "emergency_contact": "David Chen (father)",
     "emergency_phone": "(555) 345-0003", "enrollment_date": "2026-01-10", "status": "Active",
     "notes": "Attached to stuffed bunny"}},
    {"fields": {"first_name": "Noah", "last_name": "Williams", "age": 3, "age_group": "Preschool",
     "allergies": "None", "medications": "", "emergency_contact": "James Williams (father)",
     "emergency_phone": "(555) 345-0004", "enrollment_date": "2025-09-01", "status": "Active",
     "notes": "Excellent at puzzles"}},
    {"fields": {"first_name": "Ava", "last_name": "Thompson", "age": 4, "age_group": "Pre-K",
     "allergies": "Eggs", "medications": "", "emergency_contact": "Lisa Thompson (mother)",
     "emergency_phone": "(555) 345-0005", "enrollment_date": "2025-07-15", "status": "Active",
     "notes": "Emerging reader, loves stories"}},
    {"fields": {"first_name": "Oliver", "last_name": "Garcia", "age": 2, "age_group": "Toddler",
     "allergies": "None", "medications": "", "emergency_contact": "Ana Garcia (mother)",
     "emergency_phone": "(555) 345-0006", "enrollment_date": "2026-03-01", "status": "Active",
     "notes": "Just transitioned from infants room"}},
    {"fields": {"first_name": "Isabella", "last_name": "Brown", "age": 3, "age_group": "Preschool",
     "allergies": "Gluten", "medications": "", "emergency_contact": "Michael Brown (father)",
     "emergency_phone": "(555) 345-0007", "enrollment_date": "2025-10-01", "status": "Active",
     "notes": "Speech delay — working with SLP"}},
    {"fields": {"first_name": "Ethan", "last_name": "Davis", "age": 4, "age_group": "Pre-K",
     "allergies": "None", "medications": "", "emergency_contact": "Karen Davis (mother)",
     "emergency_phone": "(555) 345-0008", "enrollment_date": "2025-05-15", "status": "Active",
     "notes": "Leadership qualities, helps younger kids"}},
]
add_records(children_id, children_data)
print("  8 children added")

# Activities (today's schedule)
print("Seeding activities...")
today = "2026-05-27"
activities_data = [
    {"fields": {"title": "Drop-off / Free play", "activity_date": today, "start_time": "08:00",
     "end_time": "08:30", "location": "Classroom", "staff_lead": 1, "max_children": 8,
     "description": "Morning arrival and free play"}},
    {"fields": {"title": "Morning circle", "activity_date": today, "start_time": "08:30",
     "end_time": "09:00", "location": "Circle area", "staff_lead": 1, "max_children": 8,
     "description": "Calendar, weather, songs"}},
    {"fields": {"title": "Art exploration (painting)", "activity_date": today, "start_time": "09:00",
     "end_time": "09:45", "location": "Art station", "staff_lead": 2, "max_children": 8,
     "description": "Finger painting and color mixing"}},
    {"fields": {"title": "Snack time", "activity_date": today, "start_time": "09:45",
     "end_time": "10:00", "location": "Tables", "staff_lead": 3, "max_children": 8,
     "description": "Morning snack"}},
    {"fields": {"title": "Outdoor play", "activity_date": today, "start_time": "10:00",
     "end_time": "10:30", "location": "Playground", "staff_lead": 2, "max_children": 8,
     "description": "Free play on playground equipment"}},
    {"fields": {"title": "Storytime & literacy", "activity_date": today, "start_time": "10:30",
     "end_time": "11:00", "location": "Reading corner", "staff_lead": 1, "max_children": 8,
     "description": "Group storytime and letter recognition"}},
    {"fields": {"title": "Music & movement", "activity_date": today, "start_time": "11:00",
     "end_time": "11:30", "location": "Open area", "staff_lead": 2, "max_children": 8,
     "description": "Songs, dancing, and rhythm activities"}},
    {"fields": {"title": "Lunch", "activity_date": today, "start_time": "11:30",
     "end_time": "12:00", "location": "Tables", "staff_lead": 3, "max_children": 8,
     "description": "Lunch time"}},
    {"fields": {"title": "Nap/rest time", "activity_date": today, "start_time": "12:00",
     "end_time": "14:00", "location": "Cots", "staff_lead": 1, "max_children": 8,
     "description": "Quiet rest period"}},
    {"fields": {"title": "Afternoon snack", "activity_date": today, "start_time": "14:00",
     "end_time": "14:30", "location": "Tables", "staff_lead": 3, "max_children": 8,
     "description": "Afternoon snack"}},
    {"fields": {"title": "STEM exploration", "activity_date": today, "start_time": "14:30",
     "end_time": "15:00", "location": "Discovery table", "staff_lead": 2, "max_children": 8,
     "description": "Hands-on science and building"}},
    {"fields": {"title": "Outdoor play (pm)", "activity_date": today, "start_time": "15:00",
     "end_time": "15:30", "location": "Playground", "staff_lead": 2, "max_children": 8,
     "description": "Afternoon outdoor time"}},
    {"fields": {"title": "Pick-up / Parent handoff", "activity_date": today, "start_time": "15:30",
     "end_time": "16:00", "location": "Classroom", "staff_lead": 1, "max_children": 8,
     "description": "End of day parent communication"}},
]
add_records(activities_id, activities_data)
print("  13 activities added")

# Attendance (today)
print("Seeding attendance...")
attendance_data = [
    {"fields": {"child": i, "date": today, "check_in": f"08:{2+i:02d}",
     "check_out": None, "staff": 1, "notes": ""}}
    for i in range(1, 9)
]
add_records(attendance_id, attendance_data)
print("  8 attendance records added")

# Milestones (sample per child)
print("Seeding milestones...")
milestones_data = [
    {"fields": {"child": 1, "date": today, "category": "Language",
     "description": "Emma used descriptive language to describe her painting — 'it's a purple dinosaur!'",
     "staff": 2, "tags": "Language, Art, Descriptive", "ai_generated": True}},
    {"fields": {"child": 2, "date": today, "category": "Cognitive",
     "description": "Liam counted to 100 during circle time with no assistance",
     "staff": 1, "tags": "Math, Counting, Advanced", "ai_generated": False}},
    {"fields": {"child": 3, "date": "2026-05-26", "category": "Social-Emotional",
     "description": "Sophia shared her bunny with another toddler during rest time — first observed sharing behavior",
     "staff": 1, "tags": "Sharing, Empathy, Milestone", "ai_generated": False}},
    {"fields": {"child": 4, "date": today, "category": "Cognitive",
     "description": "Noah completed a 48-piece puzzle independently in 12 minutes",
     "staff": 2, "tags": "Fine Motor, Problem Solving, Persistence", "ai_generated": True}},
    {"fields": {"child": 5, "date": "2026-05-26", "category": "Language",
     "description": "Ava read 'Brown Bear, Brown Bear' aloud to a small group during free play",
     "staff": 1, "tags": "Reading, Leadership, Confidence", "ai_generated": False}},
    {"fields": {"child": 6, "date": today, "category": "Social-Emotional",
     "description": "Oliver comforted a crying peer by offering a toy — first observed empathy behavior",
     "staff": 3, "tags": "Empathy, Social Skills, Transition Success", "ai_generated": True}},
    {"fields": {"child": 7, "date": today, "category": "Language",
     "description": "Isabella used a 3-word sentence unprompted — 'More juice please' — SLP goal progress",
     "staff": 1, "tags": "Speech, SLP Goal, Communication", "ai_generated": False}},
    {"fields": {"child": 8, "date": today, "category": "Social-Emotional",
     "description": "Ethan organized a group game of 'Simon Says' and explained rules to 5 peers",
     "staff": 2, "tags": "Leadership, Communication, Initiative", "ai_generated": True}},
]
add_records(milestones_id, milestones_data)
print("  8 milestones added")

# Daily reports (today)
print("Seeding daily reports...")
reports_data = [
    {"fields": {"child": 1, "date": today, "breakfast": "Oatmeal + banana (ate well)",
     "lunch": "Chicken pasta + green beans (finished all)", "snack": "Apple slices + graham crackers",
     "nap_start": "12:15", "nap_end": "13:45", "mood": "Happy, engaged",
     "activities_summary": "Art exploration, Storytime, Outdoor play",
     "milestone_notes": "Used descriptive language during art — see milestone log"}},
    {"fields": {"child": 2, "date": today, "breakfast": "Scrambled eggs + toast (ate most)",
     "lunch": "Turkey sandwich + carrots (ate all)", "snack": "Yogurt + berries",
     "nap_start": "12:10", "nap_end": "13:30", "mood": "Energetic, curious",
     "activities_summary": "Morning circle (led counting), Music, STEM exploration",
     "milestone_notes": "Counted to 100 during circle time — see milestone log"}},
    {"fields": {"child": 3, "date": today, "breakfast": "Rice cereal + banana (dairy-free, ate well)",
     "lunch": "Rice + beans + veggies (dairy-free, ate most)", "snack": "Dairy-free crackers + applesauce",
     "nap_start": "12:05", "nap_end": "14:00", "mood": "Calm, content",
     "activities_summary": "Free play, Morning circle, Outdoor play, Nap",
     "milestone_notes": "Comfortable with bunny all day, participated in group"}},
    {"fields": {"child": 4, "date": today, "breakfast": "Pancakes + berries (ate all)",
     "lunch": "Mac and cheese + peas (finished all)", "snack": "Crackers + cheese",
     "nap_start": "12:20", "nap_end": "13:40", "mood": "Focused, happy",
     "activities_summary": "Puzzle station, Storytime, Outdoor play",
     "milestone_notes": "Completed 48-piece puzzle — see milestone log"}},
    {"fields": {"child": 5, "date": today, "breakfast": "Egg-free muffin + fruit (ate well)",
     "lunch": "Egg-free pasta + broccoli (ate most)", "snack": "Pretzels + apple",
     "nap_start": "12:00", "nap_end": "13:35", "mood": "Confident, talkative",
     "activities_summary": "Reading corner (led story), Art, Music & movement",
     "milestone_notes": "Read aloud to peers yesterday — continuing to build confidence"}},
    {"fields": {"child": 6, "date": today, "breakfast": "Oatmeal + peaches (ate well)",
     "lunch": "Chicken + rice + corn (ate most)", "snack": "Crackers + banana",
     "nap_start": "12:10", "nap_end": "14:10", "mood": "Settled, happy",
     "activities_summary": "Free play, Outdoor exploration, Nap",
     "milestone_notes": "Comforted crying peer — see milestone log"}},
    {"fields": {"child": 7, "date": today, "breakfast": "Gluten-free toast + banana (ate well)",
     "lunch": "GF pasta + meat sauce + peas (ate most)", "snack": "GF crackers + applesauce",
     "nap_start": "12:05", "nap_end": "13:50", "mood": "Quiet, engaged",
     "activities_summary": "Art exploration, Morning circle, Storytime",
     "milestone_notes": "3-word sentence unprompted — see milestone log"}},
    {"fields": {"child": 8, "date": today, "breakfast": "Cereal + milk + banana (ate all)",
     "lunch": "Pizza + salad (finished all)", "snack": "Trail mix + apple",
     "nap_start": "12:15", "nap_end": "13:30", "mood": "Confident, helpful",
     "activities_summary": "Led group game, Outdoor play, STEM exploration",
     "milestone_notes": "Organized Simon Says for 5 peers — see milestone log"}},
]
add_records(reports_id, reports_data)
print("  8 daily reports added")

print(f"\nDone! Document ID: {doc_id}")
print(f"Grist URL: http://127.0.0.1:8096/o/docs-5/p/{doc_id}")
