param([switch]$Stop)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $taskRoot
$taskCompose = @('compose', '--env-file', 'deploy/verify.env', '-p', 'alfa-context-preview', '-f', 'compose.yaml', '-f', 'compose.verify.yaml', '-f', 'compose.preview.yaml')
if ($Stop) {
    & docker @taskCompose down
    if ($LASTEXITCODE -ne 0) { throw 'Preview shutdown failed' }
    Write-Output 'Preview stopped; its volumes are retained.'
    exit
}
& docker @taskCompose up --build -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Preview startup failed' }
& docker @taskCompose exec -T api python -c "from app.config import settings,environment_settings; base=environment_settings(); c=settings(); assert base.demo_mode and not base.llm_api_key and not base.llm_base_url and not base.auto_fetch_rss; print('Preview: isolated environment defaults; RSS '+('enabled through saved admin settings' if c.auto_fetch_rss else 'disabled')+'; LLM calls '+('disabled' if c.demo_mode else 'enabled through saved admin settings'))"
if ($LASTEXITCODE -ne 0) { throw 'Preview isolation check failed' }
Write-Output 'Open http://127.0.0.1:8081/ — demo / demo-alfa-2026'
Write-Output 'Existing preview data are preserved. A new volume starts with synthetic demo data only.'
