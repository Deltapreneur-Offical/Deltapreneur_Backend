# Recreate local venv (Python 3.11) and install backend dependencies.
# Requires PostgreSQL on localhost:5432 (see .env TEST_DATABASE_URL).
#
# Usage (PowerShell):
#   cd cobrother_backend
#   .\scripts\setup_local_test_env.ps1
#
# Then run tests:
#   .\venv\Scripts\python.exe -m pytest app/tests -q

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$python = "C:\Users\adity\AppData\Local\Programs\Python\Python311\python.exe"
if (-not (Test-Path $python)) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    throw "Python 3.11 not found. Install Python 3.11 and retry."
}

Write-Host "Using Python: $python"

if (Test-Path venv) {
    Write-Host "Removing broken venv..."
    Remove-Item -Recurse -Force venv
}

Write-Host "Creating venv..."
& $python -m venv venv

$venvPy = Join-Path $PWD "venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip setuptools wheel
& $venvPy -m pip install -r requirements.txt

Write-Host "Ensuring test database exists..."
& $venvPy -c @"
import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv
load_dotenv('.env')
url = os.getenv('TEST_DATABASE_URL', '')
if not url:
    raise SystemExit('TEST_DATABASE_URL missing in .env')
# postgresql://user:pass@host:port/dbname
parts = url.replace('postgresql+asyncpg://', 'postgresql://').replace('postgresql://', '')
userpass, hostdb = parts.split('@', 1)
user, password = userpass.split(':', 1)
hostport, dbname = hostdb.split('/', 1)
host, port = hostport.split(':', 1)
conn = psycopg2.connect(host=host, port=int(port), user=user, password=password, dbname='postgres')
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()
cur.execute('SELECT 1 FROM pg_database WHERE datname=%s', (dbname,))
if not cur.fetchone():
    cur.execute(f'CREATE DATABASE {dbname}')
    print(f'Created database {dbname}')
else:
    print(f'Database {dbname} already exists')
cur.close(); conn.close()
"@

Write-Host "Running migrations on dev database..."
& $venvPy -m alembic upgrade head

Write-Host "Running migrations on test database..."
$testUrl = (Get-Content .env | Where-Object { $_ -match '^TEST_DATABASE_URL=' }) -replace '^TEST_DATABASE_URL=',''
if ($testUrl) {
    $env:DATABASE_URL = $testUrl
    & $venvPy -m alembic upgrade head
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
}

Write-Host "Done. Activate with: .\venv\Scripts\Activate.ps1"
Write-Host "Run tests with: .\venv\Scripts\python.exe -m pytest app/tests -q"
