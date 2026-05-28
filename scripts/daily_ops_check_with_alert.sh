#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/claude/demo-daycare"
CHECK_SCRIPT="$BASE_DIR/scripts/daily_ops_check.sh"
LOG_FILE="$BASE_DIR/backups/daily_ops.log"
FORCE_FAIL="${FORCE_FAIL_DAILY_OPS_CHECK:-0}"
DEBUG_ALERT="${DAILY_OPS_ALERT_DEBUG:-0}"

cd "$BASE_DIR"
set -a
. ./.env
set +a

check_ok=0
if [[ "$FORCE_FAIL" == "1" ]]; then
  echo "[daily_ops] FORCED_FAIL enabled for alert-path test" >> "$LOG_FILE"
else
  if "$CHECK_SCRIPT" >> "$LOG_FILE" 2>&1; then
    check_ok=1
  fi
fi

if [[ "$check_ok" == "1" ]]; then
  exit 0
fi

ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
host=$(hostname)
reason="daily_ops_check_failed"
if [[ "$FORCE_FAIL" == "1" ]]; then
  reason="forced_failure_test"
fi
alert_text="🚨 daily_ops_check FAILED (${reason}) at ${ts} on ${host}. See ${LOG_FILE}"

resp=$(curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_ALERT_CHAT_ID}" \
  -d "text=${alert_text}" || true)

if [[ "$DEBUG_ALERT" == "1" ]]; then
  echo "$resp"
fi

exit 1
