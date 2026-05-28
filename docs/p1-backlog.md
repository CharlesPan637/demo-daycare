# P1 Backlog

Date: 2026-05-28
Release baseline: `v1.0.0-p0`

## Progress Update (2026-05-28)
- **Enrollment CRM automation (core)** is now implemented:
  - waitlist CRM fields (`tour_date`, `follow_up_sla_hours`, `next_follow_up_at`, `conversion_score`, `retention_risk_score`, `lost_reason`)
  - tour scheduling endpoint (`POST /waitlist/{entry_id}/schedule-tour`)
  - due follow-up endpoint (`GET /waitlist/followups/due`)
  - pipeline summary endpoint (`GET /waitlist/pipeline/summary`)
  - active n8n SLA alert workflow (`Waitlist Follow-up SLA Alert — 10:00AM Weekdays`)
- **Enrollment CRM automation (deepening follow-up)** completed on 2026-05-28:
  - waitlist scoring endpoint (`POST /waitlist/scoring/run`) computes conversion and retention-risk with reason codes
  - pipeline summary now includes stale stage counts, conversion score buckets, follow-ups due by stage, and top sources
  - stage playbook workflow now runs scoring before daily escalation actions (`Waitlist Stage Playbook — 10:30AM Weekdays`)
- Remaining P1 operational hardening now shifts to non-domain platform tickets (P1-01…P1-10).
- **Forecasting uplift (core)** is now implemented:
  - `/forecast` now uses live waitlist inputs (no hardcoded waitlist assumptions)
  - anomaly detection vs prior 3-month baseline
  - churn proxy from waitlist `retention_risk_score`
  - breakeven estimate from configurable monthly-cost and per-child revenue assumptions
  - monthly n8n forecast workflow updated and active (`Enrollment Forecast — 1st of Month`)
- **Forecasting hardening (follow-up)** completed on 2026-05-28:
  - removed hardcoded breakeven/revenue fallback defaults from `/forecast`
  - added explicit `licensed_capacity` assumptions in `GET /forecast/assumptions`
  - updated monthly n8n forecast logic to use assumptions + live room ratios/history fallbacks (no fixed-capacity default path)
- **Regulatory copilot uplift (core)** is now implemented:
  - versioned rule ingestion endpoint (`POST /regulatory/rules/ingest`)
  - traceability endpoints for rule list and per-rule versions
  - dynamic regulatory Q&A endpoint (`GET /regulatory/ask`) and `/ask` command integration
  - audit risk scoring endpoints (`GET /regulatory/audit/risk-summary`, `POST /regulatory/audit/risk-assessments/run`)
  - weekly n8n ingestion+risk workflow active (`Regulatory Rules Ingestion — Mondays 8:45AM`)
- **Workflow freshness visibility (P1-08 core)** is now implemented:
  - heartbeat ingest endpoint (`POST /ops/workflows/heartbeat`)
  - freshness status endpoint (`GET /ops/workflows/freshness`)
  - critical workflow heartbeat steps added and activated in n8n
  - daily ops check now fails on stale workflow freshness (`stale_count != 0`)

## Ticket Template Fields
- **ID**
- **Title**
- **Owner**
- **Estimate**
- **Dependencies**
- **Scope**
- **Acceptance Criteria**

---

## P1-01
- **ID:** P1-01
- **Title:** Add OpenAPI spec + request validation middleware
- **Owner:** Backend
- **Estimate:** 3d
- **Dependencies:** None
- **Scope:** Publish `/openapi.json` and enforce schema validation on all P0 endpoints.
- **Acceptance Criteria:**
  - Invalid payloads return `400` with field-level validation errors.
  - `/openapi.json` reflects all implemented routes and parameters.
  - CI check fails on schema/handler drift.
- **Status:** Core implementation completed on 2026-05-28.

## P1-02
- **ID:** P1-02
- **Title:** Add pagination + sorting to list endpoints
- **Owner:** Backend
- **Estimate:** 2d
- **Dependencies:** P1-01
- **Scope:** Support `limit`, `offset`, `sort_by`, `sort_dir` on:
  - `GET /waitlist`
  - `GET /pickup/events`
  - `GET /subsidy/claims`
  - `GET /billing/invoices/{id}/autopay/attempts`
- **Acceptance Criteria:**
  - Deterministic default ordering.
  - Response includes `count`, `limit`, `offset`.
  - Out-of-range parameters return `400` with validation details.
- **Status:** Core implementation completed on 2026-05-28.

## P1-03
- **ID:** P1-03
- **Title:** Add idempotency keys on critical write endpoints
- **Owner:** Backend
- **Estimate:** 3d
- **Dependencies:** P1-01
- **Scope:** Add `Idempotency-Key` support for:
  - `POST /pickup/events`
  - `POST /billing/invoices/generate`
  - `POST /billing/invoices/{invoice_id}/autopay/run`
  - `POST /subsidy/claims`
  - `POST /subsidy/reconcile/{claim_id}`
  - `POST /waitlist`
- **Acceptance Criteria:**
  - Replayed requests within TTL return same logical result.
  - Duplicate rows are not created.
  - Idempotency behavior documented in API contract.
- **Status:** Core implementation completed on 2026-05-28.

## P1-04
- **ID:** P1-04
- **Title:** Standardize error envelope + correlation ID
- **Owner:** Backend
- **Estimate:** 2d
- **Dependencies:** P1-01
- **Scope:** Return unified error payload and request correlation metadata.
- **Acceptance Criteria:**
  - All non-2xx responses include `error.code`, `error.message`, `request_id`.
  - `X-Request-Id` is returned on every response.
  - Request ID is present in server logs.
- **Status:** Core implementation completed on 2026-05-28.

## P1-05
- **ID:** P1-05
- **Title:** Add per-key rate limiting for protected API routes
- **Owner:** Backend
- **Estimate:** 2d
- **Dependencies:** P1-04
- **Scope:** Introduce configurable rate limits by `X-API-Key`.
- **Acceptance Criteria:**
  - Excess requests return `429` with retry hint.
  - `/health` excluded from throttling.
  - Throttle events include key hash + route in logs.
- **Status:** Core implementation completed on 2026-05-28.

## P1-06
- **ID:** P1-06
- **Title:** Support dual-key API rotation window
- **Owner:** Backend + Ops
- **Estimate:** 1.5d
- **Dependencies:** P1-05
- **Scope:** Accept active and next key concurrently during controlled rotation.
- **Acceptance Criteria:**
  - Both keys work during configured window.
  - Old key can be revoked immediately.
  - Rotation runbook updated and tested once.
- **Status:** Core implementation completed on 2026-05-28 (dual-key support + runbook update).

## P1-07
- **ID:** P1-07
- **Title:** Add automated end-to-end regression suite
- **Owner:** QA + Backend
- **Estimate:** 4d
- **Dependencies:** P1-01, P1-03
- **Scope:** Cover critical P0 flows:
  - pickup verify + denied/override events
  - invoice allocation + autopay attempts
  - subsidy claim + reconcile + summary
  - waitlist create/advance/list
  - auth gate behavior (`401`/`200`)
- **Acceptance Criteria:**
  - Suite runs in CI and blocks merge on failure.
  - Test artifacts include HTTP status + payload assertions.
- **Status:** Core implementation completed on 2026-05-28 (unittest suite + CI workflow).

## P1-08
- **ID:** P1-08
- **Title:** Add workflow freshness endpoint for ops visibility
- **Owner:** Backend + Ops
- **Estimate:** 2d
- **Dependencies:** P1-07
- **Scope:** Expose status endpoint for critical n8n workflows.
- **Acceptance Criteria:**
  - Endpoint reports last success timestamp per workflow.
  - Flags stale workflows beyond threshold.
  - Daily ops script can consume endpoint for red/yellow/green state.
- **Status:** Core implementation completed on 2026-05-28.

## P1-09
- **ID:** P1-09
- **Title:** Complete incident runbook and ownership matrix
- **Owner:** Ops
- **Estimate:** 1d
- **Dependencies:** None
- **Scope:** Finalize on-call and response procedure.
- **Acceptance Criteria:**
  - Runbook includes severity levels, responders, and escalation path.
  - Rollback and recovery commands are copy/paste-ready.
  - Communication template for incident updates included.
- **Status:** Core implementation completed on 2026-05-28 (`docs/incident-runbook.md`).

## P1-10
- **ID:** P1-10
- **Title:** Add strict data normalization guardrails for Grist writes
- **Owner:** Backend
- **Estimate:** 2d
- **Dependencies:** P1-01
- **Scope:** Enforce enum/date/number normalization before write operations.
- **Acceptance Criteria:**
  - Invalid enum/date/number rejected with actionable `400` errors.
  - Stored statuses are canonical (no mixed-case variants).
  - Backfill script provided for legacy inconsistencies.
- **Status:** Core implementation completed on 2026-05-28 (guardrails + backfill script).

## P1-11
- **ID:** P1-11
- **Title:** Enrollment CRM automation (tour pipeline + SLA + conversion summary)
- **Owner:** Backend + Ops
- **Estimate:** 3d
- **Dependencies:** None
- **Scope:** Extend waitlist lifecycle with SLA-managed follow-ups, tour scheduling, and pipeline metrics.
- **Acceptance Criteria:**
  - Waitlist stores CRM fields for follow-up cadence and scoring.
  - API supports scheduling tours and listing overdue follow-ups.
  - Pipeline summary endpoint returns stage counts, conversion rate, due-followup count, and risk buckets.
  - n8n alert workflow notifies staff on overdue follow-ups.
- **Status:** Core implementation completed on 2026-05-28.

---

## Suggested Execution Order
1. P1-01
2. P1-04
3. P1-02
4. P1-03
5. P1-10
6. P1-05
7. P1-06
8. P1-07
9. P1-08
10. P1-09
11. P1-11 (completed core)
