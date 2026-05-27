#!/bin/sh
set -e

python telegram_polling.py &

exec gunicorn \
  --bind "0.0.0.0:${PORT:-8097}" \
  --workers "${GUNICORN_WORKERS:-1}" \
  --threads "${GUNICORN_THREADS:-8}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  app:app
