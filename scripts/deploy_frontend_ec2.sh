#!/usr/bin/env bash
# Deploy frontend dist to EC2 nginx root. Run on EC2 after uploading dist.zip to /tmp.
set -euo pipefail

ZIP="${1:-/tmp/dist.zip}"
DEST="/opt/cobrother/frontend/dist"

if [[ ! -f "${ZIP}" ]]; then
  echo "Usage: $0 [/tmp/dist.zip]" >&2
  exit 1
fi

sudo mkdir -p "${DEST}"
sudo rm -rf "${DEST:?}"/*
sudo unzip -o "${ZIP}" -d "${DEST}/"
# bashupload zips often contain a top-level dist/ folder
if [[ -d "${DEST}/dist" ]]; then
  sudo mv "${DEST}/dist/"* "${DEST}/"
  sudo rmdir "${DEST}/dist" 2>/dev/null || true
fi
sudo chown -R ubuntu:ubuntu /opt/cobrother/frontend
sudo nginx -t
sudo systemctl reload nginx

echo "Deployed to ${DEST}"
ls -la "${DEST}/index.html"
grep -E 'route-platform-analytics' "${DEST}/index.html" || true
