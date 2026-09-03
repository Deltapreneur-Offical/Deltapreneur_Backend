# One-shot local dev: RDS SSH tunnel (if needed) + Alembic + Uvicorn.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

. (Join-Path $PSScriptRoot "dev_env.ps1")

$defaultKey = Join-Path $env:USERPROFILE "Downloads\cobrother-prod-key.pem"
if (-not $env:COBROTHER_SSH_KEY -and (Test-Path $defaultKey)) {
    $env:COBROTHER_SSH_KEY = $defaultKey
}

if (-not (Test-DbTunnelPort)) {
    Write-Host "[run_local] Starting RDS tunnel in a new window..." -ForegroundColor Yellow
    Start-Process powershell -WorkingDirectory $PSScriptRoot -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", (Join-Path $PSScriptRoot "run_rds_tunnel.ps1")
    )

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if (Test-DbTunnelPort) { break }
        Start-Sleep -Seconds 1
    }
} else {
    Write-Host "[run_local] RDS tunnel already running on 127.0.0.1:5433" -ForegroundColor Green
}

$resolved = Resolve-DevDatabaseUrl
if ($resolved -match "127\.0\.0\.1:5433") {
    Write-Error "RDS tunnel did not open on 127.0.0.1:5433 and DATABASE_URL_DIRECT is unreachable. Check SSH key (COBROTHER_SSH_KEY) and EC2 access."
}

& (Join-Path $PSScriptRoot "run_dev.ps1")
