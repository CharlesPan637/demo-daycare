# P0 API Contract

Authentication:
- Header required on all non-public routes: `X-API-Key: <API_KEY>`
- During controlled key rotation, `X-API-Key: <API_KEY_NEXT>` is also accepted until `API_KEY_NEXT_ACTIVE_UNTIL`.
- Public route: `GET /health`

Base URL (local): `http://127.0.0.1:8097`

## Required Environment Variables
- `API_KEY`
- `API_KEY_NEXT` (optional, for rotation window)
- `API_KEY_NEXT_ACTIVE_UNTIL` (optional ISO datetime, e.g. `2026-06-01T18:00:00Z`)
- `GRIST_API_KEY`
- `GRIST_DOC_ID`
- `GRIST_BASE_URL`
- `STAFF_CHAT_IDS`

---

## Guardians & Custody

### Create/link guardian
`POST /children/{child_id}/guardians`

Request:
```json
{
  "guardian": { "first_name": "Jane", "last_name": "Doe", "phone": "+1-555-000-1111" },
  "link": { "legal_status": "custodial", "pickup_allowed": true, "pickup_password": "1234" }
}
```

Response `201`:
```json
{ "status": "linked", "child_id": "1", "guardian_id": 12, "link_id": 7 }
```

### List child guardians
`GET /children/{child_id}/guardians`

Response `200`:
```json
{ "child_id": "1", "child_name": "Emma Johnson", "guardians": [] }
```

### Patch child-guardian link
`PATCH /children/{child_id}/guardians/{guardian_id}`

Request:
```json
{ "pickup_allowed": false, "notes": "Court-reviewed" }
```

Response `200`:
```json
{ "status": "updated", "party_id": "..." }
```

---

## Pickup Enforcement & Audit

### Verify pickup eligibility
`POST /pickup/verify`

Request:
```json
{ "child_id": 1, "guardian_id": 12, "pickup_password": "1234" }
```

Response `200`:
```json
{ "allowed": true, "reason": "ok", "link_id": 7 }
```

### Log pickup event
`POST /pickup/events`

Denied example:
```json
{
  "child_id": 1,
  "approved": false,
  "denial_code": "pickup_not_allowed",
  "denial_reason": "Policy restriction"
}
```

Override-approved example:
```json
{
  "child_id": 1,
  "approved": true,
  "override_used": true,
  "override_reason": "Manual ID verified",
  "override_approved_by": 1
}
```

Validation:
- If `approved=false`, `denial_code` is required.
- `denial_code` must be one of:
  - `guardian_not_linked`
  - `legal_restriction`
  - `pickup_not_allowed`
  - `pickup_password_mismatch`
  - `identity_mismatch`
  - `court_order_restriction`
  - `other`
- If `override_used=true`, require both `override_reason` and `override_approved_by`.

### List pickup events
`GET /pickup/events?child_id=1&approved=true&from=2026-05-01T00:00:00&to=2026-05-31T23:59:59`

Response `200`:
```json
{ "count": 2, "events": [] }
```

---

## Billing Split, Allocation, Autopay

### Create split-billing party
`POST /billing/accounts/{account_id}/parties`

Request:
```json
{
  "guardian": 12,
  "payer_label": "Primary Parent",
  "share_pct": 100,
  "fixed_amount": 0,
  "priority": 10,
  "auto_debit": true,
  "status": "active"
}
```

Response `201`:
```json
{ "status": "created", "party_id": 1 }
```

### Patch split-billing party
`PATCH /billing/accounts/{account_id}/parties/{party_id}`

Request:
```json
{ "auto_debit": "false", "priority": "5", "status": "ACTIVE" }
```

Response `200`:
```json
{ "status": "updated", "party_id": "1", "fields": { "...": "..." } }
```

### Generate invoices
`POST /billing/invoices/generate`

Request:
```json
{
  "invoices": [
    {
      "account": "1",
      "period_start": "2026-07-01",
      "period_end": "2026-07-31",
      "due_date": "2026-08-10",
      "total_due": "1234.56"
    }
  ]
}
```

Response `201`:
```json
{ "status": "created", "count": 1, "invoice_ids": [3] }
```

### Compute allocations
`POST /billing/invoices/{invoice_id}/allocate`

Response `200`:
```json
{
  "invoice_id": "3",
  "account_id": "1",
  "total_due": 1234.56,
  "allocation_count": 1,
  "allocations": []
}
```

### Run autopay
`POST /billing/invoices/{invoice_id}/autopay/run`

Optional request body:
```json
{
  "dry_run": false,
  "simulate_fail_party_ids": [1]
}
```

Response `200`:
```json
{
  "invoice_id": "3",
  "dry_run": false,
  "attempt_count": 1,
  "attempts": []
}
```

Behavior:
- Attempts only for `auto_debit=true` and active parties.
- Writes `Autopay_Attempts` audit rows for every attempt.
- Posts payments for successful attempts.
- Updates invoice status to `paid` or `partial`.

### List autopay attempts
`GET /billing/invoices/{invoice_id}/autopay/attempts`

Response `200`:
```json
{ "invoice_id": "3", "count": 1, "attempts": [] }
```

---

## Subsidy Reconciliation

### Create claim
`POST /subsidy/claims`

Request:
```json
{
  "claim_month": "2026-06",
  "child": "1",
  "program": "CCAP",
  "expected_amount": "900",
  "status": "SUBMITTED"
}
```

Response `201`:
```json
{ "status": "created", "claim_id": 2 }
```

### List claims
`GET /subsidy/claims?claim_month=2026-06&status=variance&program=CCAP`

Response `200`:
```json
{ "count": 1, "claims": [] }
```

### Reconcile claim
`POST /subsidy/reconcile/{claim_id}`

Request:
```json
{ "received_amount": 850, "notes": "Short by 50" }
```

Response `200`:
```json
{
  "status": "reconciled",
  "claim_id": "2",
  "fields": { "received_amount": 850.0, "variance": -50.0, "status": "variance" }
}
```

### Reconciliation summary
`GET /subsidy/reconciliation/summary?claim_month=2026-06`

Response `200`:
```json
{
  "claim_month": "2026-06",
  "count": 1,
  "totals": { "expected_amount": 900.0, "received_amount": 850.0, "variance": -50.0 },
  "variance_buckets": { "exact": 0, "overpaid": 0, "underpaid": 1, "unpaid": 0 },
  "claims": []
}
```

---

## Waitlist

### Create waitlist entry
`POST /waitlist`

Request:
```json
{
  "child_first_name": "Ava",
  "child_last_name": "Lee",
  "desired_start_date": "2026-09-01",
  "status": "new",
  "priority_score": "7"
}
```

Response `201`:
```json
{ "status": "created", "entry_id": 10 }
```

### Advance waitlist
`POST /waitlist/{entry_id}/advance`

Response `200`:
```json
{ "status": "advanced", "entry_id": "10", "new_status": "contacted" }
```

### List waitlist
`GET /waitlist?status=new`

Response `200`:
```json
{ "count": 3, "entries": [] }
```

---

## Marketing Analytics

### Attribution summary
`GET /marketing/attribution/summary`

Response `200`:
```json
{
  "lead_count": 3,
  "review_count": 3,
  "channels": [
    {
      "channel": "google",
      "lead_count": 2,
      "converted_count": 1,
      "conversion_rate": 0.5
    }
  ],
  "campaigns": [
    {
      "campaign": "summer",
      "lead_count": 2,
      "converted_count": 1,
      "conversion_rate": 0.5
    }
  ]
}
```

### SEO summary
`GET /marketing/seo/summary`

Response `200`:
```json
{
  "lead_count": 3,
  "review_count": 3,
  "lead_trend_by_month": [
    { "month": "2026-04", "count": 2 },
    { "month": "2026-05", "count": 1 }
  ],
  "received_review_trend_by_month": [
    { "month": "2026-04", "count": 1 },
    { "month": "2026-05", "count": 1 }
  ],
  "channel_mix": [
    { "channel": "google", "lead_count": 2 }
  ],
  "campaign_performance": [
    {
      "campaign": "summer",
      "lead_count": 2,
      "converted_count": 1,
      "conversion_rate": 0.5
    }
  ]
}
```

### Marketing spend ingestion
`POST /marketing/spend`

Request:
```json
{
  "channel": "google",
  "campaign": "summer-2026",
  "period_month": "2026-04",
  "spend_amount": 300,
  "currency": "USD",
  "clicks": 120,
  "impressions": 5400
}
```

Response `201`:
```json
{ "status": "created", "spend_id": 1 }
```

### Spend efficiency summary (CPL/CPA)
`GET /marketing/attribution/spend-summary?period_month=2026-04`

Response `200`:
```json
{
  "count": 2,
  "items": [
    {
      "channel": "google",
      "campaign": "summer-2026",
      "spend_amount": 300.0,
      "lead_count": 2,
      "converted_count": 1,
      "cpl": 150.0,
      "cpa": 300.0
    }
  ],
  "totals": {
    "spend_amount": 420.0,
    "lead_count": 2,
    "converted_count": 1,
    "blended_cpl": 210.0,
    "blended_cpa": 420.0
  }
}
```

### Spend trend (MoM CPL/CPA)
`GET /marketing/attribution/spend-trend`

Response `200`:
```json
{
  "count": 3,
  "items": [
    {
      "period_month": "2026-04",
      "spend_amount": 420.0,
      "lead_count": 2,
      "converted_count": 1,
      "blended_cpl": 210.0,
      "blended_cpa": 420.0,
      "mom_cpl_change": null,
      "mom_cpa_change": null
    },
    {
      "period_month": "2026-05",
      "spend_amount": 560.0,
      "lead_count": 2,
      "converted_count": 1,
      "blended_cpl": 280.0,
      "blended_cpa": 560.0,
      "mom_cpl_change": 70.0,
      "mom_cpa_change": 140.0
    }
  ]
}
```

### Attribution touchpoint ingestion
`POST /marketing/attribution/touchpoints`

Request:
```json
{
  "lead_id": 1,
  "channel": "google",
  "campaign": "summer-2026",
  "touch_type": "ad_click",
  "occurred_at": "2026-05-01T09:00:00",
  "utm_source": "google",
  "utm_medium": "cpc",
  "utm_campaign": "summer-2026"
}
```

Response `201`:
```json
{ "status": "created", "touchpoint_id": 1 }
```

### Multi-touch weighted attribution
`GET /marketing/attribution/multi-touch?period_month=2026-05&model=position_based`

Response `200`:
```json
{
  "period_month": "2026-05",
  "model": "position_based",
  "count": 1,
  "items": [
    {
      "channel": "facebook",
      "weighted_conversions": 1.0,
      "spend_amount": 180.0,
      "weighted_cpa": 180.0
    }
  ],
  "totals": {
    "weighted_conversions": 1.0,
    "weighted_cpa": 560.0,
    "prior_month": "2026-04",
    "prior_weighted_cpa": 420.0,
    "weighted_cpa_change_vs_prior_month": 140.0
  }
}
```

### Attribution weight controls
`GET /marketing/attribution/weights`

Response `200`:
```json
{
  "first_touch": 0.4,
  "middle_touch_total": 0.2,
  "last_touch": 0.4,
  "sum": 1.0
}
```

`POST /marketing/attribution/weights`

Request:
```json
{
  "first_touch": 0.3,
  "middle_touch_total": 0.4,
  "last_touch": 0.3
}
```

Response `200`:
```json
{
  "status": "updated",
  "first_touch": 0.3,
  "middle_touch_total": 0.4,
  "last_touch": 0.3,
  "sum": 1.0
}
```
