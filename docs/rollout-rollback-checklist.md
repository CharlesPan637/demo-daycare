# P0 Rollout and Rollback Checklist

## 1) Pre-rollout (must pass)

- [ ] `cd /home/claude/demo-daycare`
- [ ] `docker compose config` returns no errors.
- [ ] `.env` contains required keys: `API_KEY`, `STAFF_CHAT_IDS`, `GRIST_API_KEY`, `GRIST_DOC_ID`, `TELEGRAM_BOT_TOKEN`.
- [ ] For key rotation windows, set optional keys:
  - [ ] `API_KEY_NEXT=<new_key>`
  - [ ] `API_KEY_NEXT_ACTIVE_UNTIL=<ISO datetime, e.g. 2026-06-01T18:00:00Z>`
- [ ] Backup current compose/env before changes:
  - [ ] `cp docker-compose.yml docker-compose.yml.bak.$(date +%Y%m%d-%H%M%S)`
  - [ ] `cp .env .env.bak.$(date +%Y%m%d-%H%M%S)`

## 2) Rollout

- [ ] Pull/build latest code and images.
- [ ] Start stack:
  - [ ] `docker compose up -d --build`
- [ ] Verify containers are running:
  - [ ] `docker compose ps`
  - [ ] Expected healthy services: `grist`, `bot`, `ollama`, `n8n`, `minio`, `nginx`.

## 3) Post-rollout smoke checks

- [ ] Public health endpoint:
  - [ ] `curl -s -i http://127.0.0.1:8097/health`
  - [ ] Expect `HTTP/1.1 200`.
- [ ] Auth gate blocks missing key:
  - [ ] `curl -s -i http://127.0.0.1:8097/waitlist`
  - [ ] Expect `401 Unauthorized`.
- [ ] Authenticated API request works:
  - [ ] `set -a && . ./.env && set +a`
  - [ ] `curl -s -i -H "X-API-Key: $API_KEY" "http://127.0.0.1:8097/waitlist?limit=1"`
  - [ ] Expect `200 OK`.
- [ ] Bot logs show no startup exceptions:
  - [ ] `docker compose logs --tail=80 bot`

## 4) Rollback triggers

Rollback immediately if any of the following occur after rollout:

- [ ] API health fails for more than 2 minutes.
- [ ] Authenticated requests return `5xx` repeatedly.
- [ ] `bot` container crash-loops.
- [ ] Critical flows fail: pickup verify/events, invoice allocation/autopay, subsidy reconciliation.

## 5) Rollback steps

- [ ] Stop new rollout:
  - [ ] `docker compose down`
- [ ] Restore previous config:
  - [ ] `cp docker-compose.yml.bak.<timestamp> docker-compose.yml`
  - [ ] `cp .env.bak.<timestamp> .env`
- [ ] Start previous known-good version:
  - [ ] `docker compose up -d --build`
- [ ] Re-run smoke checks from section 3.

## 6) Release sign-off

- [ ] Smoke checks passed.
- [ ] No critical errors in `docker compose logs --tail=200 bot`.
- [ ] Team notified of rollout status and rollback point.

## 7) API Key Rotation Runbook (P1-06)

- [ ] Prepare new key in `.env`:
  - [ ] Keep current `API_KEY` unchanged.
  - [ ] Set `API_KEY_NEXT` to the new key.
  - [ ] Set `API_KEY_NEXT_ACTIVE_UNTIL` to an explicit UTC expiry time.
- [ ] Reload service:
  - [ ] `docker compose up -d bot`
- [ ] Test both keys during the window:
  - [ ] `curl -s -i -H "X-API-Key: $API_KEY" http://127.0.0.1:8097/waitlist?limit=1`
  - [ ] `curl -s -i -H "X-API-Key: $API_KEY_NEXT" http://127.0.0.1:8097/waitlist?limit=1`
  - [ ] Expect both to return `200`.
- [ ] Cut over immediately when ready:
  - [ ] Promote new key into `API_KEY`.
  - [ ] Clear `API_KEY_NEXT` and `API_KEY_NEXT_ACTIVE_UNTIL`.
  - [ ] `docker compose up -d bot`
- [ ] Verify old key is revoked:
  - [ ] `curl -s -i -H "X-API-Key: <old_key>" http://127.0.0.1:8097/waitlist?limit=1`
  - [ ] Expect `401`.
