param([switch]$KeepRunning)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$taskProject = 'alfa-context-check-' + (Get-Date -Format 'yyyyMMddHHmmss')
$taskCompose = @('compose', '-p', $taskProject, '--env-file', 'deploy/verify.env', '-f', 'compose.yaml', '-f', 'compose.verify.yaml')
$taskOldBase = $env:E2E_BASE_URL
$taskOldBrowsers = $env:PLAYWRIGHT_BROWSERS_PATH
function Invoke-CheckedDocker {
    & docker @taskCompose @args
    if ($LASTEXITCODE -ne 0) { throw "Docker verification failed: $LASTEXITCODE" }
}
try {
    Invoke-CheckedDocker up --build -d --wait
    Invoke-CheckedDocker exec -T api python -c "from app.config import settings; c=settings(); assert c.demo_mode and not c.llm_api_key and not c.llm_test_limit_rub; print('Paid provider disabled')"
    Invoke-CheckedDocker exec -T api alembic check
    $env:E2E_BASE_URL = 'http://localhost:8081'
    if (-not $env:PLAYWRIGHT_BROWSERS_PATH) { $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $taskRoot 'tmp/playwright' }
    Push-Location -LiteralPath (Join-Path $taskRoot 'frontend')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules/.bin/playwright.ps1')) {
            & npm ci --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'Browser test dependencies failed' }
        }
        & npx playwright install chromium --only-shell
        if ($LASTEXITCODE -ne 0) { throw 'Browser installation failed' }
        & npm run test:e2e -- --workers=1
        if ($LASTEXITCODE -ne 0) { throw 'Browser acceptance failed' }
    } finally { Pop-Location }
    & (Join-Path $taskRoot '.venv/Scripts/python.exe') scripts/verify_settings.py --project $taskProject
    if ($LASTEXITCODE -ne 0) { throw 'Settings persistence check failed' }
    & (Join-Path $taskRoot '.venv/Scripts/python.exe') scripts/verify_recovery.py --project $taskProject
    if ($LASTEXITCODE -ne 0) { throw 'Queue recovery check failed' }
    & (Join-Path $taskRoot '.venv/Scripts/python.exe') scripts/verify_backup.py --project $taskProject
    if ($LASTEXITCODE -ne 0) { throw 'Backup restore check failed' }
    Write-Output "Verified isolated project: $taskProject on http://localhost:8081"
} finally {
    $env:E2E_BASE_URL = $taskOldBase
    $env:PLAYWRIGHT_BROWSERS_PATH = $taskOldBrowsers
    if (-not $KeepRunning) { & docker @taskCompose down }
    Write-Output "Verification project: $taskProject (volumes retained; main project untouched)"
}
