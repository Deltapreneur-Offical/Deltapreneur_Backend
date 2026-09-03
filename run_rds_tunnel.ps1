# SSH tunnel: laptop localhost:5433 -> AWS RDS via EC2 jump host.
# Auto-reconnects when the SSH session drops (sleep, Wi-Fi change, idle timeout).
# Keep this window open while developing locally.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Ec2User = if ($env:COBROTHER_EC2_USER) { $env:COBROTHER_EC2_USER } else { "ubuntu" }
$Ec2Host = if ($env:COBROTHER_EC2_HOST) { $env:COBROTHER_EC2_HOST } else { "65.0.95.43" }
$KeyPath = if ($env:COBROTHER_SSH_KEY) { $env:COBROTHER_SSH_KEY }
elseif (Test-Path "$env:USERPROFILE\Downloads\cobrother-prod-key.pem") { "$env:USERPROFILE\Downloads\cobrother-prod-key.pem" }
else { "$env:USERPROFILE\Downloads\LightsailDefaultKey-ap-south-1.pem" }
# Main DB (restored snapshot with real data). Must match DATABASE_URL_DIRECT in .env.
$RdsHost = if ($env:COBROTHER_RDS_HOST) { $env:COBROTHER_RDS_HOST } else { "database-1-recovery-restore.cno8smi8qae3.ap-south-1.rds.amazonaws.com" }
$LocalPort = if ($env:COBROTHER_RDS_LOCAL_PORT) { $env:COBROTHER_RDS_LOCAL_PORT } else { "5433" }

if (-not (Test-Path $KeyPath)) {
    Write-Error "SSH key not found: $KeyPath. Set COBROTHER_SSH_KEY to your .pem path."
}

$sshArgs = @(
    "-i", $KeyPath,
    "-N",
    "-L", "${LocalPort}:${RdsHost}:5432",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=6",
    "-o", "TCPKeepAlive=yes",
    "-o", "StrictHostKeyChecking=accept-new",
    "${Ec2User}@${Ec2Host}"
)

Write-Host "RDS tunnel watcher - 127.0.0.1:${LocalPort} via ${Ec2User}@${Ec2Host}" -ForegroundColor Cyan
Write-Host "Leave this window open. Reconnects automatically if SSH drops." -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""

$attempt = 0
while ($true) {
    $attempt += 1
    if ($attempt -gt 1) {
        $waitSec = [Math]::Min(30, 3 * ($attempt - 1))
        Write-Host "[tunnel] Reconnecting in ${waitSec}s (attempt $attempt)..." -ForegroundColor Yellow
        Start-Sleep -Seconds $waitSec
    }

    Write-Host "[tunnel] Opening SSH forward on 127.0.0.1:${LocalPort} ..." -ForegroundColor Green
    & ssh @sshArgs
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host "[tunnel] SSH exited cleanly." -ForegroundColor DarkGray
        break
    }

    Write-Host "[tunnel] SSH exited with code $exitCode - will retry." -ForegroundColor Yellow
}
