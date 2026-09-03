# Shared helpers for local dev scripts (run_dev.ps1, run_local.ps1).

function Test-DbTunnelPort {
    param([int]$Port = 5433)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

function Test-DatabasePortFromUrl {
    param([string]$DatabaseUrl)

    if (-not $DatabaseUrl) { return $false }

    if ($DatabaseUrl -match '@([^:/]+):(\d+)/') {
        $hostName = $matches[1]
        $port = [int]$matches[2]
    } elseif ($DatabaseUrl -match '@([^:/]+)/') {
        $hostName = $matches[1]
        $port = 5432
    } else {
        return $false
    }

    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect($hostName, $port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

function Get-EnvFileValue {
    param([string]$Key)

    if (Test-Path "env:$Key") {
        $fromEnv = (Get-Item "env:$Key").Value
        if ($fromEnv) {
            return $fromEnv.Trim()
        }
    }

    $envFile = Join-Path $PSScriptRoot ".env"
    if (-not (Test-Path $envFile)) {
        return $null
    }

    foreach ($line in Get-Content $envFile) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=\s*(.+?)\s*(?:#.*)?$") {
            return $matches[1].Trim().Trim('"').Trim("'")
        }
    }

    return $null
}

function Get-DatabaseUrl {
    return Get-EnvFileValue -Key "DATABASE_URL"
}

function Get-DirectDatabaseUrl {
    return Get-EnvFileValue -Key "DATABASE_URL_DIRECT"
}

function Resolve-DevDatabaseUrl {
    param([int]$TunnelPort = 5433)

    $databaseUrl = Get-DatabaseUrl
    if (-not $databaseUrl) {
        return $null
    }

    if ($databaseUrl -notmatch "127\.0\.0\.1:${TunnelPort}") {
        $env:DATABASE_URL = $databaseUrl
        return $databaseUrl
    }

    if (Test-DbTunnelPort -Port $TunnelPort) {
        $env:DATABASE_URL = $databaseUrl
        Write-Host ('[dev] RDS tunnel detected on 127.0.0.1:' + $TunnelPort) -ForegroundColor Green
        return $databaseUrl
    }

    $directUrl = Get-DirectDatabaseUrl
    if ($directUrl -and (Test-DatabasePortFromUrl -DatabaseUrl $directUrl)) {
        $env:DATABASE_URL = $directUrl
        Write-Host ('[dev] RDS tunnel unavailable on 127.0.0.1:' + $TunnelPort + ' - using DATABASE_URL_DIRECT') -ForegroundColor Yellow
        return $directUrl
    }

    return $databaseUrl
}

function Warn-RegistrarCredentials {
    $python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        $python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
    }
    if (-not (Test-Path $python)) {
        return
    }

    $configured = & $python -c 'from app.core.config import settings; print("1" if settings.resellerclub_configured() else "0")'
    if ($configured -ne "1") {
        Write-Host ""
        Write-Host "WARNING: ResellerClub credentials are missing from .env." -ForegroundColor Yellow
        Write-Host "  Homepage domain search will return 503 until RESELLERCLUB_LIVE_* keys are set." -ForegroundColor Yellow
        Write-Host "  Copy the Domain registrar block from .env.example." -ForegroundColor Yellow
        Write-Host ""
    }
}

function Assert-RdsTunnelReady {
    param([int]$Port = 5433)

    $resolved = Resolve-DevDatabaseUrl -TunnelPort $Port
    if (-not $resolved) {
        Write-Error "DATABASE_URL is not configured in .env"
    }

    if ($resolved -match "127\.0\.0\.1:${Port}") {
        Write-Host ""
        Write-Host "ERROR: Database tunnel is not running on 127.0.0.1:${Port} and DATABASE_URL_DIRECT is unreachable." -ForegroundColor Red
        Write-Host "  Option A: .\run_rds_tunnel.ps1   (keep that window open)" -ForegroundColor Yellow
        Write-Host "             then run .\run_dev.ps1 again in this window" -ForegroundColor Yellow
        Write-Host "  Option B: Set DATABASE_URL_DIRECT in .env to a reachable RDS host" -ForegroundColor Yellow
        Write-Host ""
        exit 1
    }
}
