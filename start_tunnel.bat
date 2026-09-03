@echo off
set COBROTHER_SSH_KEY=C:\Users\sushm\Downloads\aws-key-temp.pem
powershell -ExecutionPolicy Bypass -File "%~dp0run_rds_tunnel.ps1"
