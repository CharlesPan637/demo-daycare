#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT_PATH="${BASE_DIR}/docs/openapi.json"
TMP_PATH="$(mktemp)"
trap 'rm -f "${TMP_PATH}"' EXIT

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -x "${BASE_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${BASE_DIR}/.venv/bin/python"
fi

"${PYTHON_BIN}" "${BASE_DIR}/scripts/generate_openapi_snapshot.py" --output "${TMP_PATH}" >/dev/null

if [[ ! -f "${SNAPSHOT_PATH}" ]]; then
  echo "[openapi_drift] FAIL: missing snapshot file at ${SNAPSHOT_PATH}"
  echo "[openapi_drift] Hint: run scripts/generate_openapi_snapshot.py to create it."
  exit 1
fi

if ! cmp -s "${TMP_PATH}" "${SNAPSHOT_PATH}"; then
  echo "[openapi_drift] FAIL: OpenAPI snapshot drift detected."
  echo "[openapi_drift] Regenerate with: python3 scripts/generate_openapi_snapshot.py"
  diff -u "${SNAPSHOT_PATH}" "${TMP_PATH}" | sed -n '1,120p' || true
  exit 1
fi

echo "[openapi_drift] PASS: docs/openapi.json matches current route/schema surface."
