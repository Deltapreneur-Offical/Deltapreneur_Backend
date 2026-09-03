# Start the LOCAL backend WITHOUT running alembic.
#
# This is the safe variant of run_dev.ps1: it resolves the database path
# (tunnel if up, otherwise DATABASE_URL_DIRECT), applies the same dev OAuth /
# URL overrides, and boots uvicorn. It deliberately does NOT run
# `alembic upgrade head`, so un-approved migrations are never applied.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Set-Location (Join-Path $PSScriptRoot "..")

$logDir = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
Start-Transcript -Path (Join-Path $logDir "local-backend.log") -Append | Out-Null

. (Join-Path $PSScriptRoot "..\dev_env.ps1")

$env:GOOGLE_OAUTH_REDIRECT_URI = "http://127.0.0.1:8000/api/v1/auth/oauth/google/callback"
$env:GOOGLE_OAUTH_SUCCESS_REDIRECT = "http://127.0.0.1:5173/auth/callback"
$env:LINKEDIN_REDIRECT_URI = "http://127.0.0.1:8000/api/v1/community/linkedin/callback"
$env:FRONTEND_BASE_URL = "http://127.0.0.1:5173"
$env:BACKEND_BASE_URL = "http://127.0.0.1:8000"
$env:BACKGROUND_JOBS_ENABLED = "false"
Remove-Item Env:CORS_ALLOW_ORIGINS -ErrorAction SilentlyContinue

$resolved = Resolve-DevDatabaseUrl
if ($resolved -match "127\.0\.0\.1:5433" -and -not (Test-DbTunnelPort)) {
    Write-Host "[start-local] Tunnel down and direct RDS unreachable - aborting." -ForegroundColor Red
    exit 1
}
$redacted = $resolved -replace '://[^:]+:[^@]+@', '://***@'
Write-Host "[start-local] DB: $redacted" -ForegroundColor Cyan
Write-Host "[start-local] Starting uvicorn on http://127.0.0.1:8000 (NO alembic run)" -ForegroundColor Green

& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
