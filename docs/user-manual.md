# Sunshine Sprouts Early Learning Center — User Manual

> For the daycare office manager. Covers system setup, administration, and all features.
> Version 2.0 — May 2026

---

## 1. What This System Replaces

| Old Way | New Way |
|---------|---------|
| Brightwheel / Kangarootime ($600+/mo) | This system ($0/mo software) |
| Paper sign-in sheets | Telegram check-in/out with timestamps |
| Handwritten observation notes | Voice or text observations, AI-tagged to developmental frameworks |
| Staff answering same parent questions repeatedly | AI assistant answers policy questions instantly |
| Manual daily report writing | Automated daily reports delivered to parents via Telegram |
| Filing cabinet of child records | 15 Grist tables — searchable, exportable, queryable |
| Separate billing, scheduling, payroll tools | Unified stack: Grist + Bot + n8n + Ollama |
| Spreadsheet vaccine tracking with missed deadlines | 8 health history records: vaccines, allergies, doctors, conditions |
| No visual record of child milestones | 29 portfolio moments (photos, videos, audio, drawings) |
| Yearly photo book only | Monthly books with teacher narratives per child |

Everything runs on one server in your center. No child data leaves the building.

---

## 2. System Overview

```
Parents ──Telegram──> @DemoDaycare_bot ──> Grist (15 tables: child records, attendance,
                                              milestones, health history, portfolio, books)
Staff ────Telegram──> @DemoDaycare_bot ──> AI (Ollama phi3:mini) tags observations,
                                              answers policy questions, RAG on regulations
                                              │
                                           n8n (7 automated workflows: daily reports,
                                              staffing checks, subsidy deadline + reconciliation alerts,
                                              autopay failure alerts, enrollment forecasts, weekly health summaries)
                                              │
                                           Minio (photos, observation media, portfolio assets)
```

### Services & URLs

| Service | Purpose | URL |
|---------|---------|-----|
| Grist | All data: children, staff, attendance, health history, portfolio, books | `https://demo-daycare.66.94.122.133.sslip.io:8445` |
| n8n | Workflow automations | `https://demo-daycare.66.94.122.133.sslip.io:8446` |
| Minio | Photo & document storage (S3-compatible) | `http://<server-ip>:8099` (internal) |
| Telegram Bot | Parent & staff interface | `@DemoDaycare_bot` on Telegram |

### Credentials

```
Grist:  admin@daycare.local / DemoDaycare2026!
n8n:    admin@daycare.local / DemoDaycare2026!
Minio:  daycare / DemoDaycare2026!
```

> Change these passwords after installation. See Section 9.

---

## 3. Grist — The Backend Database

Grist is a spreadsheet-database hybrid. Think of Excel with a proper API, running in your browser.

### 3.1 Logging In

1. Open `https://demo-daycare.66.94.122.133.sslip.io:8445`
2. Enter `admin@daycare.local` and password
3. Select the "Sunshine Sprouts Daycare" document

### 3.2 Complete Tables Overview

| Table | Table ID | Records | What It Holds |
|-------|----------|---------|---------------|
| **Children** | Table2 | 8 | Name, age, allergies, medications, emergency contacts, enrollment status, parent_chat_id |
| **Staff** | Table3 | 3 | Name, role, certifications, contact info |
| **Attendance** | Table4 | — | Daily check-in/check-out timestamps per child |
| **Activities** | Table5 | 13 | Daily schedule — time, location, staff lead |
| **Milestones** | Table6 | — | AI-tagged developmental observations |
| **Daily_Reports** | Table7 | — | Meals, naps, mood, activities summary per child per day |
| **Staff_Availability** | Table8 | 15 | Staff schedules by day, room qualifications, on-call flags |
| **Room_Ratios** | Table9 | 4 | State-mandated ratios, room capacity, current enrollment |
| **Subsidies** | Table10 | 4 | CCAP/Head Start tracking, monthly amounts, reauthorization dates |
| **Enrollment_History** | Table11 | 5 | Monthly enrollment trend, new/departed, waitlist, revenue |
| **Incidents** | Table12 | 2 | Injury/behavioral incident log with parent notification tracking |
| **Health_History** | Health_History | 8 | Per-child consolidated health: vaccine status, allergies, family doctor, pediatrician, conditions |
| **Portfolio_Moments** | Table14 | 29 | Rich media milestone moments (photo, video, audio, drawing) |
| **Monthly_Books** | Table15 | 8 | Monthly compilations per child with teacher notes and highlights |

### 3.3 Core Operations

**Adding a New Child:**
1. Open the **Children** table → click "+" to add a row
2. Fill in: first_name, last_name, age, age_group, allergies, medications, emergency_contact, emergency_phone, enrollment_date, status, notes
3. Add health history in the **Health_History** table (see 3.6)

**Adding a New Staff Member:**
1. Open the **Staff** table → click "+"
2. Fill in: first_name, last_name, role, specialization, certifications, phone, email
3. Add their weekly availability in **Staff_Availability**

**Editing the Daily Schedule:**
1. Open the **Activities** table
2. Each row is one time slot. Edit title, start_time, end_time, location, staff_lead

**Viewing Reports & Milestones:**
- **Daily_Reports** — filter by child or date
- **Milestones** — filter by child to see developmental history; filter by category for domain-specific view
- Use Grist's sort and filter widgets at the top of each column

### 3.4 Staff Availability & Room Ratios

**Staff_Availability (Table8):** Each row = one staff member on one day of the week. Tracks start/end times, rooms they're qualified for, on-call status, and contact phone.

**Room_Ratios (Table9):** State-mandated ratios per room. If `current_enrolled` exceeds `max_children` for a room's ratio, the `/staffing` bot command will flag it.

### 3.5 Subsidies & Enrollment

**Subsidies (Table10):** Each row = one child's government subsidy. Tracks program name (CCAP, Head Start), monthly amount, reauthorization deadline, case worker contact, and status. The `/subsidies` command highlights urgent reauthorizations.

**Enrollment_History (Table11):** Monthly snapshot of total enrolled, new enrollments, departures, waitlist count, and monthly revenue. The `/forecast` command reads this table to project trends.

### 3.6 Health History

**Health_History:** One record per child consolidating all health information:

- **Vaccine Status:** Compliance summary with overdue/due-soon alerts (e.g., "Up to date — 6 of 6 vaccines current")
- **Allergen Status:** Food/environmental allergies, severity, and action plans
- **Family Doctor:** Name, phone, and address
- **Pediatrician:** Name, phone, and clinic
- **Other Conditions:** Speech delay, eczema, asthma, seasonal allergies, or other concerns
- **Last Updated:** Review date

The `/vaccines` command reads this table for both per-child health records and all-children compliance summaries. The n8n weekly health summary flags overdue vaccines.

### 3.7 Student Portfolio & Monthly Books

**Portfolio_Moments (Table14):** Rich media milestone moments — the digital scrapbook. Each moment tracks:
- Type: Photo, Video, Audio, or Drawing
- Title, description, date, category, tags
- Media URL (pointing to Minio storage)
- Highlight flag (featured in monthly book)

**Monthly_Books (Table15):** Compiled each month per child with:
- Cover description and highlight summary
- Teacher's personal note
- Cross-references to portfolio moments
- Status: Draft, Published, or Sent

Staff add moments via `/moment`. Parents browse via `/portfolio`. Monthly books are viewed via `/book`.

### 3.8 Exporting & Backup

- Click the three-dot menu on any table → "Export" → CSV or Excel
- Full backup: `docker compose -f /home/claude/demo-daycare/docker-compose.yml exec grist tar -czf /backup/grist-$(date +%Y%m%d).tar.gz /persist/docs`

---

## 4. Telegram Bot — Staff & Parent Interface

### 4.1 Bot Setup (One-Time)

1. The office manager creates the bot via @BotFather on Telegram
2. Send `/newbot` to @BotFather, follow prompts, name it `@DemoDaycare_bot`
3. Copy the token into `.env` as `TELEGRAM_BOT_TOKEN`
4. Restart: `docker compose up -d --build bot`

### 4.2 Parent Enrollment

1. Ask each parent to install Telegram on their phone
2. Parent sends `/start` to `@DemoDaycare_bot`
3. The bot captures their chat ID — they are registered for daily reports
4. Parent sends `/link <first_name> <last_name>` (e.g., `/link Emma Johnson`) to tie their Telegram to their child — both first and last name are required for security
5. After linking, parents receive instant notifications whenever staff logs an `/observe` or `/moment` for their child

**Alternative for office manager:** Set `parent_chat_id` directly in the Children table (Table2) in Grist. The `/link` command is the self-service way.

### 4.3 Complete Command Reference

#### Daily Operations

| Command | Who | What It Does |
|---------|-----|--------------|
| `/start` | Parents & Staff | Register with the bot, receive welcome message |
| `/help` | Everyone | Show all available commands |
| `/checkin <child>` | Staff | Record child arrival with timestamp |
| `/checkout <child>` | Staff | Record child departure with timestamp |

#### Parent Communication

| Command | Who | What It Does |
|---------|-----|--------------|
| `/report <child>` | Parents & Staff | Full daily report: meals, naps, mood, activities, milestones |
| `/milestones <child>` | Parents & Staff | Recent developmental milestones with categories and tags |
| `/activity` | Everyone | Today's schedule with times, locations, and staff leads |
| `/link <first> <last>` | Parents | Link Telegram account to child (requires both first and last name) — enables instant milestone & moment notifications |

#### AI-Powered Features

| Command | Who | What It Does |
|---------|-----|--------------|
| `/observe <child> <note>` | Staff | Log an observation — AI tags developmental category and generates milestone |
| `/ask <question>` | Parents & Staff | AI answers policy, curriculum, and regulation questions (RAG-powered) |

#### AI Agents — Operations

| Command | Who | What It Does |
|---------|-----|--------------|
| `/staffing` | Staff & Admin | Today's coverage by room, ratio compliance, gap alerts |
| `/callout <room>` | Staff & Admin | Find qualified substitutes when a staff member calls out |
| `/substitutes [room]` | Staff & Admin | View contingency substitute roster |
| `/addsub <name> \| <phone> \| ...` | Staff & Admin | Add a substitute teacher to the contingency roster |
| `/subsidies` | Admin | Active subsidies, monthly total, urgent reauthorization deadlines |
| `/forecast` | Admin | 6-month enrollment trend, revenue projection, summer decline warning |

#### AI Agents — Health & Compliance

| Command | Who | What It Does |
|---------|-----|--------------|
| `/health` | Staff & Admin | Cross-room allergies, recent incidents, vaccine compliance summary |
| `/vaccines <child>` | Staff & Parents | Per-child full health record (vaccines, allergies, doctors, conditions) or all-children compliance summary |

#### Portfolio & Memories

| Command | Who | What It Does |
|---------|-----|--------------|
| `/portfolio <child>` | Staff & Parents | Browse child's milestone moments (photos, videos, audio, drawings) |
| `/moment <child> <type> <title> — <desc>` | Staff | Add a portfolio moment (Photo/Video/Audio/Drawing) |
| `/book <child> [month]` | Staff & Parents | Read child's monthly book with highlights and teacher note |

### 4.4 Staff Daily Workflow

```
Morning (7:30-8:30):
  /staffing                    ← Check today's coverage and ratios
  /checkin emma
  /checkin liam
  ... (for each child as they arrive)

During the day:
  /observe emma Emma built a tower of 12 blocks and counted each one
  /observe noah Noah completed a 48-piece puzzle independently
  /moment emma Photo First painting — Emma painted a purple dinosaur today!
  ... (voice or text, whenever you notice something worth recording)
  → Parents get instant Telegram notifications for each observe/moment

Mid-day check:
  /health                      ← Quick allergy/vaccine/incident overview
  /activity                    ← What's coming up next?

Afternoon (3:30-4:00):
  /checkout emma
  /checkout liam
  ... (for each child as they leave)

End of week:
  /book emma                   ← Review Emma's monthly book before it goes to parents
  /vaccines                    ← Check for any new overdue vaccines
```

### 4.5 Using Voice for Observations

1. In Telegram, tap the microphone icon next to the bot's message field
2. Speak your observation naturally
3. Release to send the voice memo
4. The bot transcribes it (Whisper API), tags developmental categories, and saves to Grist

### 4.6 Demo Response Cache

For the demo walkthrough, common queries are pre-cached for instant response:
- "Emma built a tower of 12 blocks" → instant AI-tagged milestone
- "peanut allergy policy" → instant center-specific answer
- `/staffing`, `/subsidies`, `/forecast`, `/health` → pre-computed dashboard responses

---

## 5. n8n — Workflow Automation

### 5.1 Access

Open `https://demo-daycare.66.94.122.133.sslip.io:8446` and log in.

### 5.2 Pre-configured Workflows

| Workflow | Trigger | What It Does |
|----------|---------|--------------|
| **Daily Summary — 4PM Parent Reports** | 4:00 PM weekdays | Collects today's reports per child → sends personalized messages to parents via Telegram |
| **Morning Staffing Coverage Check** | 7:30 AM weekdays | Verifies each room has qualified staff assigned → alerts if ratio would be violated |
| **Subsidy Deadline Alert** | 9:00 AM weekdays | Checks reauthorization dates within 14-day window → alerts admin of urgent renewals |
| **Subsidy Reconciliation Alert** | 9:15 AM weekdays | Checks subsidy claims for variances/unpaid status → alerts admin with claim-level variance details |
| **Autopay Due Invoices** | 8:00 AM weekdays | Runs autopay on due invoices and sends Telegram alert only for failed attempts |
| **Enrollment Forecast** | 1st of month | Compiles enrollment trend, waitlist, capacity utilization → sends summary to admin |
| **Weekly Health Summary** | Friday 4:00 PM | Aggregates allergies, incidents, vaccine compliance, attendance → sends to director |
| **Instant Parent Notifications** | Real-time (webhook) | Called when staff logs `/observe` or `/moment` → bot sends instant Telegram message to linked parents |

### 5.3 Managing Workflows

- **Import:** Settings → Import from File → select JSON from `/home/claude/demo-daycare/n8n-workflows/`
- **Activate/Deactivate:** Toggle the switch on any workflow card
- **Edit schedule:** Click workflow → click Schedule Trigger node → edit cron expression
- **Edit message format:** Click Telegram or HTTP Request node → edit content
- **Test:** Click "Execute Workflow" to run manually

### 5.4 Subsidy Reconciliation Workflow (New)

- **File:** `n8n-workflows/subsidy-reconciliation-alert.json`
- **Required env vars in n8n:** `API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_ID`
- **Import:** n8n → Settings → Import from File → select `subsidy-reconciliation-alert.json`
- **Activate:** open workflow and toggle ON
- **Test:** execute manually; if claims have variance/unpaid status, Telegram alert is sent to `TELEGRAM_ALERT_CHAT_ID`

### 5.5 Autopay Workflow (New)

- **File:** `n8n-workflows/autopay-due-invoices-daily.json`
- **Required env vars in n8n:** `API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_ID`
- **Import:** n8n → Settings → Import from File → select `autopay-due-invoices-daily.json`
- **Activate:** open workflow and toggle ON
- **Behavior:** runs weekday 8:00 AM, attempts autopay for due invoices, alerts only when failures occur

---

## 6. AI Features

### 6.1 How It Works

The system runs a local AI model (phi3:mini, 3.8B parameters via Ollama) on your server. No data leaves the building.

| Feature | Trigger | What AI Does |
|---------|---------|--------------|
| **Milestone Tagging** | `/observe` | Reads observation → categorizes (Physical/Cognitive/Language/Social-Emotional) → generates tags → maps to developmental benchmarks → sends instant Telegram notification to linked parent |
| **Parent & Staff Q&A** | `/ask` | Answers policy questions using keyword-matched regulatory RAG (10 regulation entries covering ratios, allergies, staff quals, naps, outdoor play, incidents, subsidies) |
| **Report Summarization** | n8n daily workflow | Turns raw meal/nap/activity data into warm, parent-friendly narrative |
| **Substitute Matching** | `/callout` | Searches Staff_Availability for on-call or room-qualified staff for a given day |

### 6.2 Regulatory RAG Knowledge Base

The AI can answer questions about:
- Staff-child ratios (Infant 1:4, Toddler 1:6, Preschool 1:10, Pre-K 1:12)
- Allergy and food safety policies
- Staff qualifications and training requirements
- Nap and safe sleep requirements
- Outdoor play policies and weather cancellation rules
- Incident reporting procedures
- Subsidy compliance and reauthorization

### 6.3 Response Time

- **Instant** for 5 demo-cached topics (staffing, subsidies, forecast, health, common Q&A)
- **~3-8 seconds** for regulatory RAG queries
- **~10-25 seconds** for new AI-generated responses (runs on local CPU)
- If Ollama times out, the bot falls back to a helpful message suggesting rephrasing

---

## 7. Portfolio & Monthly Books

### 7.1 Capturing Moments

Staff can log milestone moments throughout the day:

```
/moment emma Photo Purple Dinosaur — Emma painted her first representational artwork today. She used three colors and described it as "a purple dinosaur!"
```

The moment saves to the Portfolio_Moments table with:
- Type, title, description, date, category, tags
- Highlight flagging for monthly book inclusion
- Minio media URL (upload the actual photo/video/audio separately)

**Parents get an instant Telegram notification** when a moment is logged — no waiting for the 4 PM report. The notification includes the moment type, title, and description, plus a link to view the full portfolio.

### 7.2 Viewing Portfolios

Parents browse their child's portfolio via Telegram:
```
/portfolio emma
```
Shows the 8 most recent moments with type emoji (📸🎬🎵🎨), category, date, and description.

### 7.3 Monthly Books

Each month, the system compiles a book per child with:
- A themed title and cover description
- Narrative highlights of the month's key moments
- A personal teacher note
- Cross-references to portfolio moments

View via:
```
/book emma          ← Current month's book
/book emma 2026-04  ← April 2026 book
/book               ← All children's books for current month
```

---

## 8. Minio — Photo & Document Storage

### 8.1 Access

- Console: `http://<server-ip>:9001`
- API: `http://<server-ip>:8099`
- Login: `daycare / DemoDaycare2026!`

### 8.2 Portfolio Media Buckets

Create these buckets for organized portfolio storage:
- `daycare-portfolio` — child milestone photos, videos, audio
- `daycare-documents` — enrollment forms, immunization records, licensing docs
- `daycare-photos` — general classroom and activity photos

Upload files via drag-and-drop or the S3-compatible API.

---

## 9. Maintenance & Troubleshooting

### 9.1 Starting & Stopping

```bash
# Start all 6 services
cd /home/claude/demo-daycare && docker compose up -d

# Stop all services
cd /home/claude/demo-daycare && docker compose down

# Restart a specific service
docker restart daycare-bot
docker restart daycare-grist
```

### 9.2 Monitoring

```bash
# Check all container statuses
docker compose -f /home/claude/demo-daycare/docker-compose.yml ps

# View live logs
docker compose -f /home/claude/demo-daycare/docker-compose.yml logs -f

# Monitor RAM usage
docker stats --format "table {{.Name}}\t{{.MemUsage}}"

# Check bot health (API layer)
curl -s http://127.0.0.1:8097/health

# Check critical workflow freshness (requires API key)
curl -s -H "X-API-Key: $API_KEY" http://127.0.0.1:8097/ops/workflows/freshness
# Returns stale_count and per-workflow age/threshold.
# On first rollout only, seed initial heartbeats once:
# for k in daily_summary_parent_reports staffing_coverage_check subsidy_deadline_alert subsidy_reconciliation_alert autopay_due_invoices waitlist_followup_sla_alert enrollment_forecast_monthly regulatory_rules_ingestion_weekly; do \
#   curl -s -H "Content-Type: application/json" -H "X-API-Key: $API_KEY" \
#   -d "{\"workflow_key\":\"$k\",\"workflow_name\":\"$k\",\"status\":\"success\"}" \
#   http://127.0.0.1:8097/ops/workflows/heartbeat >/dev/null; \
# done

# Daily ops smoke check (auth + access policy matrix)
/home/claude/demo-daycare/scripts/daily_ops_check.sh
# Includes: scripts/verify_command_access_matrix.py
```

### 9.3 Backing Up Data

```bash
# Grist database backup
docker compose -f /home/claude/demo-daycare/docker-compose.yml exec grist tar -czf /backup/grist-$(date +%Y%m%d).tar.gz /persist/docs

# Full project backup (all configs, scripts, data)
tar -czf daycare-full-backup-$(date +%Y%m%d).tar.gz /home/claude/demo-daycare/
```

### 9.4 Seeding & Resetting Data

```bash
# Seed all Grist tables (fresh install)
cd /home/claude/demo-daycare
pip install -r scripts/requirements.txt
python3 scripts/seed_grist.py        # Tables 1-7: core data
python3 scripts/expand_grist.py      # Tables 8-12: agents data
python3 scripts/seed_portfolio.py    # Tables 14-15: portfolio + books

# Full reset (nuke all data)
cd /home/claude/demo-daycare && docker compose down -v && docker compose up -d
# Then re-run all seed scripts above
```

### 9.5 Common Issues

| Problem | Likely Cause | Fix |
|---------|-------------|-----|
| Bot doesn't respond on Telegram | Token is placeholder or invalid | Check `.env` has real token from @BotFather; restart bot container |
| "Child not found" | Typo in name | Use exact first name: emma, liam, sophia, noah, ava, oliver, isabella, ethan |
| AI response is slow (>25s) | Ollama model loading or CPU contention | Pre-cached responses are instant; check `docker stats` for CPU usage |
| `/staffing` shows wrong day | Server clock mismatch | Verify server timezone; the bot uses `datetime.now().weekday()` |
| n8n workflows not triggering | Workflow deactivated | Open n8n UI → check toggle is ON for each workflow |
| Can't access Grist | Container crashed | `docker restart daycare-grist` |
| Portfolio moments missing media | Minio connection or URL issue | Verify Minio is running; check media_url format in Portfolio_Moments table |
| Vaccine overdue alerts not firing | n8n workflow not active | Activate `weekly-health-summary.json` in n8n; verify TELEGRAM_ALERT_CHAT_ID set in .env |
| Subsidy reconciliation alerts not firing | Reconciliation workflow not active or env missing | Activate `subsidy-reconciliation-alert.json`; verify `API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_ALERT_CHAT_ID` in n8n env |
| Autopay failure alerts not firing | Autopay workflow not active or env missing | Activate `autopay-due-invoices-daily.json`; verify `API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_ALERT_CHAT_ID` in n8n env |
| Parent not receiving instant notifications | `/link` not run, or wrong `parent_chat_id` | Have parent send `/link <first> <last>` in Telegram; or check `parent_chat_id` column in Grist Children table |
| "Failed to notify parent" in logs | Parent hasn't linked or chat_id invalid | Verify parent has sent `/start` and `/link`; check their chat_id in Grist |

### 9.6 Changing Passwords

**Grist:** Log in → user profile (top-right icon) → Change Password

**n8n:** Edit `docker-compose.yml` → change `N8N_BASIC_AUTH_PASSWORD` → `docker compose up -d n8n`

**Minio:** Log in to Minio console → Access Keys → change secret key

### 9.7 System Requirements

- Server with 8+ GB RAM (16 GB recommended with other demos)
- 50 GB disk space (Ollama model ~2.2 GB + data + portfolio media)
- Docker and Docker Compose installed
- Internet connection (Telegram API + optional Whisper transcription)

---

## 10. Privacy & Security

- **All child data stays on your server.** Ollama runs locally. No data sent to cloud AI services (except optional Whisper transcription).
- **Parent-to-child access control:** The `parent_chat_id` field in the Children table maps each parent's Telegram to their child. Staff-initiated observations and moments only notify the linked parent.
- **Telegram messages encrypted in transit** over Telegram's protocol.
- **SSL encryption** protects browser access to Grist, n8n, and bot API.
- **Password-protected:** Grist, n8n, and Minio each have separate credentials.
- **Audit trail:** Attendance, incidents, and milestones are all timestamped with staff attribution.

---

## 11. Quick Reference Card

```
Services:
  Grist:    https://demo-daycare.66.94.122.133.sslip.io:8445
  n8n:      https://demo-daycare.66.94.122.133.sslip.io:8446
  Telegram: @DemoDaycare_bot

Credentials:
  admin@daycare.local / DemoDaycare2026!  (Grist + n8n)
  daycare / DemoDaycare2026!              (Minio)

Start:     cd /home/claude/demo-daycare && docker compose up -d
Stop:      cd /home/claude/demo-daycare && docker compose down
Status:    docker compose -f /home/claude/demo-daycare/docker-compose.yml ps
Logs:      docker compose -f /home/claude/demo-daycare/docker-compose.yml logs -f
Backup:    docker compose -f /home/claude/demo-daycare/docker-compose.yml exec grist \
             tar -czf /backup/grist-$(date +%Y%m%d).tar.gz /persist/docs
RAM:       docker stats --format "table {{.Name}}\t{{.MemUsage}}"

19 bot commands:
  /start  /help  /checkin  /checkout  /report  /milestones  /activity
  /observe  /ask  /staffing  /callout  /subsidies  /forecast
  /health  /vaccines  /link  /portfolio  /moment  /book
```

---

*Sunshine Sprouts Early Learning Center — AI-Powered Daycare System*
*Version 2.0 — May 2026*
