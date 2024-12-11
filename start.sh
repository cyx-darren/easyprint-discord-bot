
#!/bin/bash
set -e

echo "Starting deployment process..."
python3 -m pip install --no-cache-dir -r requirements.txt

export PYTHONUNBUFFERED=1
export FLASK_APP=deploy.py

exec gunicorn \
  --workers 1 \
  --threads 8 \
  --timeout 0 \
  --keep-alive 120 \
  --bind "0.0.0.0:${PORT:-8080}" \
  --access-logfile - \
  --error-logfile - \
  --log-level info \
  --preload \
  deploy:app
