#!/usr/bin/env bash
# Patch Cloudflare Turnstile keys on EC2 production .env from deploy secrets.
# Usage (CI): TURNSTILE_SITE_KEY=... TURNSTILE_SECRET_KEY=... bash scripts/patch_ec2_turnstile.sh
set -euo pipefail

ENV_FILE="${1:-/opt/cobrother/backend/.env}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "WARN: ${ENV_FILE} not found — skipping Turnstile patch" >&2
  exit 0
fi

if [[ -z "${TURNSTILE_SITE_KEY:-}" && -z "${TURNSTILE_SECRET_KEY:-}" ]]; then
  echo "WARN: TURNSTILE_SITE_KEY / TURNSTILE_SECRET_KEY not set — skipping Turnstile patch"
  exit 0
fi

cp "${ENV_FILE}" "${ENV_FILE}.bak.turnstile.$(date +%Y%m%d%H%M%S)"

set_kv() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${ENV_FILE}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
  else
    echo "${key}=${value}" >> "${ENV_FILE}"
  fi
}

if [[ -n "${TURNSTILE_SITE_KEY:-}" ]]; then
  set_kv TURNSTILE_SITE_KEY "${TURNSTILE_SITE_KEY}"
fi
if [[ -n "${TURNSTILE_SECRET_KEY:-}" ]]; then
  set_kv TURNSTILE_SECRET_KEY "${TURNSTILE_SECRET_KEY}"
fi

echo "Patched Turnstile keys in ${ENV_FILE}"
grep -E '^TURNSTILE_(SITE|SECRET)_KEY=' "${ENV_FILE}" | sed 's/SECRET_KEY=.*/SECRET_KEY=***redacted***/'
