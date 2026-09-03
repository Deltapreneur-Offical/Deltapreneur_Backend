#!/bin/sh
set -e

echo "==> CoBrother backend starting..."

echo "==> Running database migrations..."
alembic upgrade head

echo "==> Starting FastAPI on port 8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
