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
staffing_code=$(curl -s -o /tmp/daily_staffing.out -w '%{http_code}' -H "X-API-Key: $API_KEY" "$BASE_URL/staffing/risk-summary")
staffing_unresolved=$(jq -r '.unresolved_predicted_gap_rooms // -1' /tmp/daily_staffing.out 2>/dev/null || echo -1)
staffing_rebalancing_actions=$(jq -r '.schedule_optimization.rebalancing_actions // 0' /tmp/daily_staffing.out 2>/dev/null || echo 0)
staffing_shift_extension_actions=$(jq -r '.schedule_optimization.shift_extension_actions // 0' /tmp/daily_staffing.out 2>/dev/null || echo 0)
staffing_unresolved_max=${STAFFING_UNRESOLVED_MAX:-0}
pickup_code=$(curl -s -o /tmp/daily_pickup_events.out -w '%{http_code}' -H "X-API-Key: $API_KEY" "$BASE_URL/pickup/events?approved=true&limit=50&offset=0&sort_by=timestamp&sort_dir=desc")
pickup_count=$(jq -r '.count // -1' /tmp/daily_pickup_events.out 2>/dev/null || echo -1)
pickup_verified_count=$(jq -r '[.events[]?.fields | select((.document_type // "") != "" and (.document_id_last4 // "") != "" and (.presented_name // "") != "")] | length' /tmp/daily_pickup_events.out 2>/dev/null || echo -1)
pickup_verified_min=${PICKUP_VERIFIED_MIN:-1}
parent_scope_probe=$(curl -s -H "Authorization: Bearer $GRIST_API_KEY" "http://127.0.0.1:8096/api/docs/$GRIST_DOC_ID/tables/Table2/records")
parent_scope_child_name=$(printf "%s" "$parent_scope_probe" | jq -r '
  [ .records[]?.fields ] as $rows
  | ($rows | map(.first_name // "")) as $all_names
  | [ $rows[] | select((.parent_chat_id // "") != "") | .first_name // "" ] as $linked_names
  | ([ $linked_names[] as $n | select(([$all_names[] | select(. == $n)] | length) == 1) | $n ][0]) // ""
' 2>/dev/null || echo "")
parent_scope_chat_id=$(printf "%s" "$parent_scope_probe" | jq -r '
  [ .records[]?.fields ] as $rows
  | ($rows | map(.first_name // "")) as $all_names
  | [ $rows[] | select((.parent_chat_id // "") != "") | .first_name // "" ] as $linked_names
  | ([ $linked_names[] as $n | select(([$all_names[] | select(. == $n)] | length) == 1) | $n ][0]) as $unique_name
  | ([ $rows[] | select((.first_name // "") == ($unique_name // "")) | .parent_chat_id // "" ][0]) // ""
' 2>/dev/null || echo "")
parent_scope_child_slug=$(printf "%s" "$parent_scope_child_name" | tr '[:upper:]' '[:lower:]')
waitlist_orch_code=$(curl -s -o /tmp/daily_waitlist_orch_coverage.out -w '%{http_code}' -H "X-API-Key: $API_KEY" "$BASE_URL/waitlist/orchestration/coverage")
waitlist_high_risk_missing_next_action=$(jq -r '.high_risk_missing_next_action // -1' /tmp/daily_waitlist_orch_coverage.out 2>/dev/null || echo -1)
if [[ -n "$parent_scope_child_slug" ]]; then
  parent_scope_deny_code=$(curl -s -o /tmp/daily_parent_scope_deny.out -w '%{http_code}' -H "X-API-Key: $API_KEY" "$BASE_URL/portfolio/$parent_scope_child_slug?strict_parent_scope=true&limit=1")
  parent_scope_allow_code=$(curl -s -o /tmp/daily_parent_scope_allow.out -w '%{http_code}' -H "X-API-Key: $API_KEY" -H "X-Parent-Chat-Id: $parent_scope_chat_id" "$BASE_URL/portfolio/$parent_scope_child_slug?strict_parent_scope=true&limit=1")
  parent_scope_portfolio_code=$(curl -s -o /tmp/daily_parent_scope_portfolio.out -w '%{http_code}' -H "X-API-Key: $API_KEY" -H "X-Parent-Chat-Id: $parent_scope_chat_id" "$BASE_URL/portfolio/$parent_scope_child_slug?strict_parent_scope=true&limit=1")
  parent_scope_portfolio_limit=$(jq -r '.limit // -1' /tmp/daily_parent_scope_portfolio.out 2>/dev/null || echo -1)
else
  parent_scope_deny_code="NA"
  parent_scope_allow_code="NA"
  parent_scope_portfolio_code="NA"
  parent_scope_portfolio_limit="-1"
fi

echo "[daily_ops] health_status=$health_code"
echo "[daily_ops] unauth_waitlist_status=$unauth_code"
echo "[daily_ops] auth_waitlist_status=$auth_code"
echo "[daily_ops] workflows_freshness_status=$freshness_code"
echo "[daily_ops] workflows_stale_count=$stale_count"
echo "[daily_ops] multitouch_status=$mt_code"
echo "[daily_ops] multitouch_count=$mt_count"
echo "[daily_ops] multitouch_weighted_cpa_shift=$mt_weighted_cpa_shift"
echo "[daily_ops] multitouch_weighted_conversions=$mt_weighted_conversions"
echo "[daily_ops] staffing_status=$staffing_code"
echo "[daily_ops] staffing_unresolved_predicted_gap_rooms=$staffing_unresolved"
echo "[daily_ops] staffing_rebalancing_actions=$staffing_rebalancing_actions"
echo "[daily_ops] staffing_shift_extension_actions=$staffing_shift_extension_actions"
echo "[daily_ops] staffing_unresolved_max=$staffing_unresolved_max"
echo "[daily_ops] pickup_events_status=$pickup_code"
echo "[daily_ops] pickup_events_count=$pickup_count"
echo "[daily_ops] pickup_verified_metadata_count=$pickup_verified_count"
echo "[daily_ops] pickup_verified_min=$pickup_verified_min"
echo "[daily_ops] parent_scope_probe_child=$parent_scope_child_name"
echo "[daily_ops] parent_scope_deny_status=$parent_scope_deny_code"
echo "[daily_ops] parent_scope_allow_status=$parent_scope_allow_code"
echo "[daily_ops] parent_scope_portfolio_status=$parent_scope_portfolio_code"
echo "[daily_ops] parent_scope_portfolio_limit=$parent_scope_portfolio_limit"
echo "[daily_ops] waitlist_orchestration_coverage_status=$waitlist_orch_code"
echo "[daily_ops] waitlist_high_risk_missing_next_action=$waitlist_high_risk_missing_next_action"

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
if [[ "$staffing_code" != "200" ]]; then
  echo "[daily_ops] FAIL: staffing risk-summary endpoint expected 200"
  exit 1
fi
if [[ "$staffing_unresolved" == "-1" ]]; then
  echo "[daily_ops] FAIL: staffing risk-summary parse failed"
  exit 1
fi
if (( staffing_unresolved > staffing_unresolved_max )); then
  echo "[daily_ops] FAIL: staffing unresolved predicted gaps exceed threshold"
  exit 1
fi
if [[ "$pickup_code" != "200" ]]; then
  echo "[daily_ops] FAIL: pickup events endpoint expected 200"
  exit 1
fi
if [[ "$pickup_count" == "-1" || "$pickup_verified_count" == "-1" ]]; then
  echo "[daily_ops] FAIL: pickup events response parse failed"
  exit 1
fi
if (( pickup_verified_count < pickup_verified_min )); then
  echo "[daily_ops] FAIL: insufficient pickup events with verification metadata"
  exit 1
fi
if [[ -z "$parent_scope_child_slug" || -z "$parent_scope_chat_id" ]]; then
  echo "[daily_ops] FAIL: no linked child found for parent scope guardrail"
  exit 1
fi
if [[ "$parent_scope_deny_code" != "403" ]]; then
  echo "[daily_ops] FAIL: strict parent scope deny check expected 403"
  exit 1
fi
if [[ "$parent_scope_allow_code" != "200" ]]; then
  echo "[daily_ops] FAIL: strict parent scope allow check expected 200"
  exit 1
fi
if [[ "$parent_scope_portfolio_code" != "200" || "$parent_scope_portfolio_limit" != "1" ]]; then
  echo "[daily_ops] FAIL: strict parent scope portfolio check expected 200 with limit=1"
  exit 1
fi
if [[ "$waitlist_orch_code" != "200" ]]; then
  echo "[daily_ops] FAIL: waitlist orchestration coverage expected 200"
  exit 1
fi
if [[ "$waitlist_high_risk_missing_next_action" == "-1" ]]; then
  echo "[daily_ops] FAIL: waitlist orchestration coverage parse failed"
  exit 1
fi
if (( waitlist_high_risk_missing_next_action > 0 )); then
  echo "[daily_ops] FAIL: high-risk waitlist leads missing next action"
  exit 1
fi

echo "[daily_ops] PASS"
