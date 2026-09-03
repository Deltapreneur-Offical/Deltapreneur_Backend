#!/usr/bin/env bash
# Local FastAPI — forces Google OAuth redirect URLs for this process tree.
# Windows / shell USER env vars (e.g. GOOGLE_OAUTH_REDIRECT_URI=https://api.yourdomain.com/...)
# override pydantic's .env file; this script wins when you start uvicorn from here.
set -euo pipefail
cd "$(dirname "$0")"

# Activate local venv when present (Git Bash on Windows or Linux/macOS).
if [[ -f venv/Scripts/activate ]]; then
  # shellcheck source=/dev/null
  source venv/Scripts/activate
elif [[ -f .venv/Scripts/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/Scripts/activate
elif [[ -f venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source venv/bin/activate
elif [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

# Always set (do not use ${VAR:-default}: a wrong Windows USER var would still win).
export GOOGLE_OAUTH_REDIRECT_URI="http://127.0.0.1:8000/api/v1/auth/oauth/google/callback"
export GOOGLE_OAUTH_SUCCESS_REDIRECT="http://127.0.0.1:5173/auth/callback"
# Keep reset/verification links and frontend redirects pinned to local HTTP on 127.0.0.1.
export FRONTEND_BASE_URL="http://127.0.0.1:5173"
export BACKEND_BASE_URL="http://127.0.0.1:8000"
export REQUIRE_DOMAIN_VERIFICATION_BEFORE_PURCHASE="false"
# Let development defaults in config.py supply CORS (do not inherit production-only origins).
unset CORS_ALLOW_ORIGINS 2>/dev/null || true

exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
