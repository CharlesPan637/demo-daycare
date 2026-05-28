# Incident Runbook and Ownership Matrix

Date: 2026-05-28  
Scope: API (`bot`), Grist data plane, n8n workflows, ingress (`nginx`)

## 1) Severity Model

| Severity | Definition | Example |
|---|---|---|
| Sev-1 | Production outage or critical safety/compliance path unavailable | API down, pickup verification failing globally |
| Sev-2 | Major degradation of a core flow with workaround | autopay failing, subsidy reconcile failing, stale workflow freshness |
| Sev-3 | Non-critical defect or partial feature impact | reporting endpoint regression with fallback available |

## 2) Ownership Matrix

| Area | Primary | Secondary | Escalate To |
|---|---|---|---|
| API/Backend (`bot`) | Backend On-call | Ops On-call | Engineering Lead |
| Workflow Automation (`n8n`) | Ops On-call | Backend On-call | Engineering Lead |
| Data Plane (`grist`) | Ops On-call | Backend On-call | Engineering Lead |
| Edge/Ingress (`nginx`) | Ops On-call | Backend On-call | Engineering Lead |
| Customer/Parent Comms | Operations Lead | Incident Commander | Director |

## 3) Incident Flow

1. Detect and declare severity (`Sev-1/2/3`).
2. Assign incident commander (IC) and owner.
3. Stabilize service first, then diagnose root cause.
4. Post updates every 15 minutes for Sev-1, every 30 minutes for Sev-2.
5. Resolve, verify smoke checks, publish closure summary.

## 4) Copy/Paste Triage Commands

```bash
cd /home/claude/demo-daycare
docker compose ps
docker compose logs --tail=120 bot
docker compose logs --tail=120 n8n
curl -s -i http://127.0.0.1:8097/health
set -a && . ./.env && set +a
curl -s -i -H "X-API-Key: $API_KEY" "http://127.0.0.1:8097/ops/workflows/freshness"
curl -s -i -H "X-API-Key: $API_KEY" "http://127.0.0.1:8097/waitlist?limit=1"
```

## 5) Containment and Rollback

Use the existing release rollback checklist:
- `docs/rollout-rollback-checklist.md`

Fast rollback command sequence:

```bash
cd /home/claude/demo-daycare
docker compose down
cp docker-compose.yml.bak.<timestamp> docker-compose.yml
cp .env.bak.<timestamp> .env
docker compose up -d --build
docker compose ps
```

## 6) Recovery Verification

```bash
cd /home/claude/demo-daycare
curl -s -i http://127.0.0.1:8097/health
set -a && . ./.env && set +a
curl -s -i -H "X-API-Key: $API_KEY" "http://127.0.0.1:8097/waitlist?limit=1"
curl -s -i -H "X-API-Key: $API_KEY" "http://127.0.0.1:8097/subsidy/reconciliation/summary"
curl -s -i -H "X-API-Key: $API_KEY" "http://127.0.0.1:8097/ops/workflows/freshness"
```

## 7) Incident Update Template

```
[Incident Update] <Sev-X> - <short title>
Start Time (UTC): <YYYY-MM-DD HH:MM>
Current Status: <Investigating | Mitigating | Monitoring | Resolved>
Impact: <who/what is affected>
Scope: <api/workflow/data components>
Actions Taken:
- <action 1>
- <action 2>
Next Update ETA: <time>
Owner: <name/role>
```

## 8) Closure Checklist

- [ ] Root cause identified.
- [ ] Service restored and smoke checks passed.
- [ ] Temporary mitigations removed or tracked.
- [ ] Follow-up tickets created with owners/dates.
- [ ] Final incident summary posted.
