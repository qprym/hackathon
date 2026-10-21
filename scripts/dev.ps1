$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create .venv and install backend/requirements.lock first.' }
$env:DATABASE_URL = 'sqlite:///' + (Join-Path $taskRoot 'alfa.db').Replace('\', '/')
$env:INLINE_WORKER = 'true'
$env:SEED_DEMO = 'true'
$env:DEMO_MODE = 'true'
Set-Location (Join-Path $taskRoot 'backend')
& $taskPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000
