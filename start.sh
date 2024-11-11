#!/bin/bash
set -e

# Log startup information
echo "=== Starting deployment process ===" >&2
echo "Current directory: $(pwd)" >&2
echo "Python version: $(python3 --version)" >&2
echo "Environment variables:" >&2
env | grep -E 'PYTHON|FLASK|GUNICORN|PORT' >&2

# Install requirements
echo "=== Installing requirements ===" >&2
python3 -m pip install --user flask gunicorn

# Start server with logging
echo "=== Starting server ===" >&2
exec gunicorn \
  --preload \
  --workers 1 \
  --threads 4 \
  --timeout 0 \
  --bind "0.0.0.0:${PORT:-8080}" \
  --log-level debug \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  deploy:app 2>&1