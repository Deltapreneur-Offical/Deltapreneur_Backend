# Local FastAPI — forces Google OAuth redirect URLs for this process tree.
#
# Windows User/System env vars override .env (pydantic-settings). If you ever set
# GOOGLE_OAUTH_REDIRECT_URI=https://api.yourdomain.com/... globally, uvicorn would
# send the wrong redirect_uri to Google until you remove that variable or use this script.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

. (Join-Path $PSScriptRoot "dev_env.ps1")

$activate = Join-Path $PSScriptRoot "venv\Scripts\Activate.ps1"
if (-not (Test-Path $activate)) {
    $activate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
}
if (Test-Path $activate) {
    . $activate
}

$env:GOOGLE_OAUTH_REDIRECT_URI = "http://127.0.0.1:8000/api/v1/auth/oauth/google/callback"
$env:GOOGLE_OAUTH_SUCCESS_REDIRECT = "http://127.0.0.1:5173/auth/callback"
$env:LINKEDIN_REDIRECT_URI = "http://127.0.0.1:8000/api/v1/community/linkedin/callback"
$env:FRONTEND_BASE_URL = "http://127.0.0.1:5173"
$env:BACKEND_BASE_URL = "http://127.0.0.1:8000"
$env:BACKGROUND_JOBS_ENABLED = "false"
Remove-Item Env:CORS_ALLOW_ORIGINS -ErrorAction SilentlyContinue

Assert-RdsTunnelReady
Warn-RegistrarCredentials

if (Test-Path ".\.venv\Scripts\alembic.exe") {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & .\.venv\Scripts\alembic.exe upgrade head 2>&1 | Out-Null
    $alembicExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($alembicExit -ne 0) {
        Write-Warning "Alembic upgrade failed (continuing anyway). If API DB errors occur, check DATABASE_URL in .env."
    }
} elseif (Test-Path ".\venv\Scripts\alembic.exe") {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & .\venv\Scripts\alembic.exe upgrade head 2>&1 | Out-Null
    $alembicExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if ($alembicExit -ne 0) {
        Write-Warning "Alembic upgrade failed (continuing anyway). If API DB errors occur, check DATABASE_URL in .env."
    }
}

uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
