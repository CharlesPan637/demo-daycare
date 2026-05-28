#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/claude/demo-daycare"
BASE_URL="http://127.0.0.1:8097"

cd "$BASE_DIR"
set -a
. ./.env
set +a

echo "[daily_ops] ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "[daily_ops] docker_compose_ps"
docker compose ps

echo "[daily_ops] access_policy_matrix_check"
if ! PYTHONDONTWRITEBYTECODE=1 python3 "$BASE_DIR/scripts/verify_command_access_matrix.py"; then
  echo "[daily_ops] FAIL: access policy matrix verification failed"
  exit 1
fi

health_code=$(curl -s -o /tmp/daily_health.out -w '%{http_code}' "$BASE_URL/health")
unauth_code=$(curl -s -o /tmp/daily_waitlist_unauth.out -w '%{http_code}' "$BASE_URL/waitlist?limit=1")
auth_code=$(curl -s -o /tmp/daily_waitlist_auth.out -w '%{http_code}' -H "X-API-Key: $API_KEY" "$BASE_URL/waitlist?limit=1")
freshness_code=$(curl -s -o /tmp/daily_freshness.out -w '%{http_code}' -H "X-API-Key: $API_KEY" "$BASE_URL/ops/workflows/freshness")
stale_count=$(jq -r '.stale_count // -1' /tmp/daily_freshness.out 2>/dev/null || echo -1)
mt_code=$(curl -s -o /tmp/daily_multitouch.out -w '%{http_code}' -H "X-API-Key: $API_KEY" "$BASE_URL/marketing/attribution/multi-touch?period_month=$(date -u +%Y-%m)&model=position_based")
mt_count=$(jq -r '.count // -1' /tmp/daily_multitouch.out 2>/dev/null || echo -1)
mt_weighted_cpa_shift=$(jq -r '.totals.weighted_cpa_change_vs_prior_month // "null"' /tmp/daily_multitouch.out 2>/dev/null || echo "null")
mt_weighted_conversions=$(jq -r '.totals.weighted_conversions // 0' /tmp/daily_multitouch.out 2>/dev/null || echo 0)

echo "[daily_ops] health_status=$health_code"
echo "[daily_ops] unauth_waitlist_status=$unauth_code"
echo "[daily_ops] auth_waitlist_status=$auth_code"
echo "[daily_ops] workflows_freshness_status=$freshness_code"
echo "[daily_ops] workflows_stale_count=$stale_count"
echo "[daily_ops] multitouch_status=$mt_code"
echo "[daily_ops] multitouch_count=$mt_count"
echo "[daily_ops] multitouch_weighted_cpa_shift=$mt_weighted_cpa_shift"
echo "[daily_ops] multitouch_weighted_conversions=$mt_weighted_conversions"

if [[ "$health_code" != "200" ]]; then
  echo "[daily_ops] FAIL: health expected 200"
  exit 1
fi
if [[ "$unauth_code" != "401" ]]; then
  echo "[daily_ops] FAIL: unauth waitlist expected 401"
  exit 1
fi
if [[ "$auth_code" != "200" ]]; then
  echo "[daily_ops] FAIL: auth waitlist expected 200"
  exit 1
fi
if [[ "$freshness_code" != "200" ]]; then
  echo "[daily_ops] FAIL: workflows freshness expected 200"
  exit 1
fi
if [[ "$stale_count" != "0" ]]; then
  echo "[daily_ops] FAIL: workflows stale_count expected 0"
  exit 1
fi
if [[ "$mt_code" != "200" ]]; then
  echo "[daily_ops] FAIL: multi-touch endpoint expected 200"
  exit 1
fi
if [[ "$mt_count" == "-1" ]]; then
  echo "[daily_ops] FAIL: multi-touch response parse failed"
  exit 1
fi
if [[ "$mt_weighted_conversions" != "0" && "$mt_count" == "0" ]]; then
  echo "[daily_ops] FAIL: weighted conversions present but channel items are empty"
  exit 1
fi
if [[ "$mt_weighted_cpa_shift" != "null" ]]; then
  # Guardrail: large absolute shift likely indicates ingestion anomaly.
  if ! awk -v v="$mt_weighted_cpa_shift" 'BEGIN { a=v<0?-v:v; exit (a <= 1000)?0:1 }'; then
    echo "[daily_ops] FAIL: weighted CPA shift exceeds threshold (1000)"
    exit 1
  fi
fi

echo "[daily_ops] PASS"
