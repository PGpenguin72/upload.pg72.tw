#Requires -Version 5
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Upload Service (Windows) ===" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Write-Error ".env not found. Run: Copy-Item .env.example .env"
    exit 1
}

New-Item -ItemType Directory -Force -Path "uploads", "temp" | Out-Null

Write-Host "[1/2] Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt -q

$port = python -c "from config import settings; print(settings.port)"
Write-Host "[2/2] Starting server on http://0.0.0.0:$port ..." -ForegroundColor Green

uvicorn main:app --host 0.0.0.0 --port $port
