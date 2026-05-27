# Changelog — v1.0.0-p0

Date: 2026-05-28

## Added
- P0 API contracts for guardians/custody, pickup verification/events, billing allocation/autopay, subsidy claims/reconciliation, and waitlist workflows.
- API key auth enforcement for protected endpoints (`X-API-Key`) with public health route.
- Telegram staff authorization hardening via `STAFF_CHAT_IDS`.
- P0 migration coverage for required Grist tables/columns.
- n8n workflows:
  - `Subsidy Reconciliation Alert — 9:15AM Daily`
  - `Autopay Due Invoices — 8:00AM Weekdays`

## Changed
- Bot runtime migrated from Flask development server to `gunicorn` in container startup.
- Compose runtime updated with explicit gunicorn settings for bot service.
- Operational docs added/updated for API contracts and rollout/rollback checks.

## Validated
- `docker compose config` passes.
- Full startup smoke checks pass (`/health` 200, auth gate 401/200 behavior correct).
- Rollback drill completed successfully (`down`/`up` recovery verified).
- n8n workflow import + activation verified; runtime dependency checks for bot and Telegram alert path succeeded.
