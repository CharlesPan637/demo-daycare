# Telegram Command Access Policy Matrix

Date: 2026-05-28

This matrix defines intended access scope for every registered Telegram command in `bot/app.py`.

| Command | Policy | Notes |
|---|---|---|
| `/start` | Public | Registers chat and onboarding text. |
| `/help` | Public | Shows command catalog. |
| `/report <child>` | Child-scoped | Staff or parent linked to that child. |
| `/milestones <child>` | Child-scoped | Staff or parent linked to that child. |
| `/activity` | Staff-only | Operational schedule view. |
| `/checkin <child>` | Staff-only | Attendance write operation. |
| `/checkout <child>` | Staff-only | Attendance write operation. |
| `/observe <child> <note>` | Staff-only | Observation write + parent notify. |
| `/ask <question>` | Mixed | Policy Q&A public; staffing/subsidy/forecast/health dashboard intents staff-only. |
| `/staffing` | Staff-only | Coverage and ratio visibility. |
| `/callout <room>` | Staff-only | Substitute search and callout planning. |
| `/subsidies` | Staff-only | Subsidy status and deadlines. |
| `/forecast` | Staff-only | Enrollment and revenue intelligence. |
| `/health` | Staff-only | Sensitive cross-room health summary. |
| `/vaccines` | Staff-only | All-children compliance summary. |
| `/vaccines <child>` | Child-scoped | Staff or parent linked to that child. |
| `/portfolio <child>` | Child-scoped | Staff or parent linked to that child. |
| `/moment ...` | Staff-only | Portfolio write operation. |
| `/book` | Staff-only | All-children monthly book listing. |
| `/book <child>` | Child-scoped | Staff or parent linked to that child. |
| `/link <first> <last>` | Public | Parent self-link flow with conflict checks. |
| `/schedule ...` | Staff-only | Meeting creation and parent notifications. |
| `/meetings [date]` | Scoped | Staff gets all meetings; parents get only linked child’s parent-teacher meetings. |
| `/announce ...` | Staff-only | Broadcast operation. |
| `/announcements` | Public | Announcement board read. |
| `/logmenu ...` | Staff-only | Menu write operation. |
| `/menu [date]` | Public | Daily menu read. |
| `/menucomment ...` | Public | Parent feedback write operation. |
| `/setschedule ...` | Staff-only | Daily schedule write operation. |
| `/scheduletoday [date]` | Public | Daily schedule read. |
| `/addsub ...` | Staff-only | Substitute roster write operation. |
| `/substitutes [room]` | Staff-only | Substitute roster read. |

## Verification

Run:

`python3 scripts/verify_command_access_matrix.py`

The verifier checks that the expected guard patterns remain present in `bot/app.py`.
