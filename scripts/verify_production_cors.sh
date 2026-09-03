#!/usr/bin/env bash
# Quick smoke test after deploy — CORS + API reachability from production SPA origins.
set -euo pipefail

check_pair() {
  local origin="$1"
  local base="$2"
  echo "Checking CORS from origin=${origin} → ${base}"

  health_headers="$(curl -sS -D - -o /dev/null -H "Origin: ${origin}" "${base}/health")"
  echo "${health_headers}" | grep -qi "access-control-allow-origin: ${origin}" || {
    echo "FAIL: /health missing Access-Control-Allow-Origin for ${origin}" >&2
    return 1
  }

  preflight="$(curl -sS -D - -o /dev/null -X OPTIONS \
    -H "Origin: ${origin}" \
    -H "Access-Control-Request-Method: POST" \
    -H "Access-Control-Request-Headers: authorization,content-type" \
    "${base}/api/v1/cart/checkout/verify")"
  echo "${preflight}" | grep -qi "access-control-allow-origin: ${origin}" || {
    echo "FAIL: cart/checkout/verify preflight missing CORS headers for ${origin}" >&2
    return 1
  }
}

check_pair "${FRONTEND_BASE_URL:-https://cobrother.com}" "${BACKEND_BASE_URL:-https://backend.cobrother.com}"
check_pair "${HUB_FRONTEND_BASE_URL:-https://hubregistrar.com}" "${HUB_BACKEND_BASE_URL:-https://backend.hubregistrar.com}"
check_pair "https://www.hubregistrar.com" "${HUB_BACKEND_BASE_URL:-https://backend.hubregistrar.com}"

echo "OK: CORS reachable for CoBrother and HubRegistrar SPA origins"
