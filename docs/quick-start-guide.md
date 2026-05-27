# Sunshine Sprouts — Quick Start Guide for Staff

> One-page reference for daily operations. Keep this posted near the sign-in area.
> Version 2.0 — May 2026

---

## Getting Started (Do This Once)

1. Install **Telegram** on your phone (free, iPhone and Android)
2. Search for `@DemoDaycare_bot`
3. Send `/start` — you're registered

---

## Every Morning: Coverage Check & Check-In

**First, check today's staffing:**
```
/staffing
```
Shows which rooms are covered and any ratio alerts.

**Then, as each child arrives:**
```
/checkin emma
/checkin liam
/checkin sophia
/checkin noah
/checkin ava
/checkin oliver
/checkin isabella
/checkin ethan
```

Bot replies: `✅ Emma Johnson checked in at 8:02 AM`

> **Tip:** Use first name only. Lowercase is fine. The bot knows all 8 children.

---

## During the Day: Observations & Moments

### Quick observation (AI-tagged):
```
/observe emma Emma counted to 12 while stacking blocks
```

Bot replies with AI-generated tags and milestone:
```
✅ Observation logged!
🏷 Tags: Fine Motor, Counting, Cognitive
🌟 Milestone: Demonstrates 1:1 correspondence counting up to 12
```

### Portfolio moment (saved to child's scrapbook):
```
/moment emma Photo Purple Dinosaur — Emma painted her first representational artwork today!
```

Use types: `Photo`, `Video`, `Audio`, or `Drawing`

**Voice is fastest:** Hold the mic button in Telegram and speak naturally.

---

## Every Afternoon: Check-Out

```
/checkout emma
/checkout liam
...
```

Bot replies: `🚪 Emma Johnson checked out at 3:45 PM`

---

## Quick Health & Safety Checks

### Daily health overview:
```
/health
```
Shows all allergies across rooms, recent incidents, and vaccine compliance. Use mid-day.

### Child health record:
```
/vaccines ava        ← Ava's full health record (vaccines, allergies, doctors, conditions)
/vaccines            ← All children vaccine compliance summary
```
🔴 = overdue vaccines | ⚠️ = due soon | ✅ = up to date

### Look up a policy instantly:
```
/ask What's our peanut allergy policy?
/ask What's the toddler room ratio?
/ask How do we handle incidents?
```

---

## Parent Questions? Answer in Seconds

| Parent asks | You type |
|-------------|----------|
| "How was Emma today?" | `/report emma` |
| "What milestones is Liam hitting?" | `/milestones liam` |
| "What are they doing right now?" | `/activity` |
| "Can I see Sophia's photos?" | `/portfolio sophia` |
| "Do we have a monthly update?" | `/book sophia` |
| "Is Noah's vaccine up to date? Who's his doctor?" | `/vaccines noah` |
| "What's the snack policy?" | `/ask snack policy` |
| "How do I get notifications?" | `/link Emma Johnson` |

---

## Instant Parent Notifications

When you log an observation or portfolio moment, parents get an instant Telegram notification — no extra steps needed.

**How it works:**
1. A parent sends `/link Emma Johnson` once — first and last name required (tying their Telegram account to their child)
2. After that, every time staff runs `/observe` or `/moment` for their child, they get a real-time notification
3. Parents stay connected to their child's day without asking "how was she?"

```
🌟 New Milestone!
Your child Emma just achieved something special:
📝 Emma built a tower of 12 blocks and counted each one
🏷 Fine Motor, Counting, Cognitive
```

> **Setup tip:** Ask parents to send `/link <first_name> <last_name>` when they first register. Office manager can also set `parent_chat_id` directly in the Grist Children table.

---

## When a Staff Member Calls Out

```
/callout preschool
```
Shows qualified substitutes available today with contact info.

---

## Portfolio & Monthly Books

**Capture a milestone moment:**
```
/moment noah Photo 48-Piece Puzzle — Noah completed his first 48-piece puzzle today!
```

**Browse a child's portfolio:**
```
/portfolio emma
```

**Read this month's book:**
```
/book emma           ← Current month
/book                ← All children's books
```

---

## Command Reference

| Command | Use |
|---------|-----|
| `/start` | Register with the bot |
| `/help` | Show all commands |
| `/checkin <child>` | Record arrival |
| `/checkout <child>` | Record departure |
| `/report <child>` | Full daily report |
| `/milestones <child>` | Developmental history |
| `/activity` | Today's schedule |
| `/observe <child> <note>` | AI-tagged observation |
| `/ask <question>` | Policy or curriculum Q&A |
| `/staffing` | Today's coverage + ratios |
| `/callout <room>` | Find substitutes |
| `/substitutes [room]` | View contingency substitute roster (staff) |
| `/addsub <name> | <phone> | ...` | Add substitute teacher to roster (staff) |
| `/subsidies` | Subsidy status |
| `/forecast` | Enrollment trends |
| `/health` | Allergies + incidents + vaccine compliance |
| `/vaccines <child>` | Full health record (vaccines, allergies, doctors, conditions) |
| `/link <first> <last>` | Link parent's Telegram (both names required) to receive instant notifications |
| `/portfolio <child>` | Milestone moments |
| `/moment <child> <type> <title>` | Add portfolio moment |
| `/book <child> [month]` | Monthly book |

---

## Children Reference

| Child | Age | Room | Allergies | Highlight |
|-------|-----|------|-----------|-----------|
| Emma Johnson | 3 | Preschool | None | Loves art, shy at drop-off |
| Liam Martinez | 4 | Pre-K | Peanuts (severe, EpiPen) | Advanced vocabulary, natural leader |
| Sophia Chen | 2 | Toddler | Dairy | Attached to stuffed bunny |
| Noah Williams | 3 | Preschool | None | Excellent at puzzles |
| Ava Thompson | 4 | Pre-K | Eggs | Emerging reader, loves stories |
| Oliver Garcia | 2 | Toddler | None | Just transitioned from infants |
| Isabella Brown | 3 | Preschool | Gluten | Speech delay — working with SLP |
| Ethan Davis | 4 | Pre-K | None | Helps younger kids, journal writer |

---

## Tips

- **Names are case-insensitive.** `emma` = `Emma` = `EMMA`
- **Voice is faster than typing** for observations and moments
- **Parents get instant notifications** when you log `/observe` or `/moment` — they stay connected all day
- **New parents: have them send `/link <first> <last>`** to register for instant notifications
- **Check `/health` at mid-day** — it catches allergy risks and overdue vaccines
- **Use `/vaccines <child>` for doctor contacts** — family doctor and pediatrician info is in each child's health record
- **Review monthly books** at month end via `/book <child>` before they go to parents
- **If a parent asks for photos,** use `/portfolio <child>` — all milestone moments in one place
- **Check-in/out timestamps are automatic.** No need to type the time
- **Parents get automated reports at 4 PM.** You don't send anything manually
- **For incidents** (injury, behavior), log in Grist Incidents table and use `/health` to verify it's recorded

---

## Need Help?

- **Bot not responding?** Tell the office manager — the server may need a restart
- **Wrong child name error?** Use first name only: emma, liam, sophia, noah, ava, oliver, isabella, ethan
- **AI response is slow?** Common questions are instant. New questions take 10-25 seconds.
- **Need a child's doctor info?** `/vaccines <child>` shows family doctor and pediatrician contacts
- **Parent not getting notifications?** Make sure they've sent `/link <first> <last>` to register their Telegram
- **Admin: subsidy variance alerts not showing?** In n8n, import/activate `subsidy-reconciliation-alert.json` and confirm `API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_ALERT_CHAT_ID` are set
- **Admin: autopay failure alerts not showing?** In n8n, import/activate `autopay-due-invoices-daily.json` and confirm `API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_ALERT_CHAT_ID` are set
- **Anything else?** Type `/help` in the bot or ask the office manager

---

*Keep this page near the check-in area, staff room, and in your phone's photos.*
