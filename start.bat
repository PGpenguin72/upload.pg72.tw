@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo === Upload Service (Windows) ===

if not exist ".env" (
    echo [ERROR] .env not found.
    echo         Run: copy .env.example .env  and fill in the values.
    exit /b 1
)

if not exist "uploads" mkdir uploads
if not exist "temp"    mkdir temp

echo [1/2] Installing dependencies...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERROR] pip install failed.
    exit /b 1
)

echo [2/2] Starting server...
for /f "usebackq" %%P in (`python -c "from config import settings; print(settings.port)"`) do set PORT=%%P
echo       Listening on http://0.0.0.0:%PORT%

uvicorn main:app --host 0.0.0.0 --port %PORT%
