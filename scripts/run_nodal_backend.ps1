$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $projectRoot '.venv-vision\Scripts\python.exe'

if ($env:NODAL_AUDIT_MODE -ne 'true' -or $env:NODAL_DB_NAME -ne 'nodal_phase8_audit' -or
    $env:MONGO_URI -ne 'mongodb://127.0.0.1:27017' -or $env:NODAL_ENV -ne 'development' -or
    [string]::IsNullOrWhiteSpace($env:NODAL_SECRET_KEY)) {
    Write-Error 'Refusing Flask startup: expected isolated Phase 8 audit environment is incomplete or incorrect.'
    Read-Host 'Press Enter to close this backend window'
    exit 1
}

Set-Location $projectRoot
$env:FLASK_DEBUG = '0'
Write-Host 'NODAL Flask - isolated database nodal_phase8_audit - debug/reload disabled' -ForegroundColor Green
& $pythonPath -m flask --app backend.app:app run --host 127.0.0.1 --port 5000 --no-debugger --no-reload
if ($LASTEXITCODE -ne 0) {
    Write-Host "Flask exited with code $LASTEXITCODE." -ForegroundColor Red
    Read-Host 'Press Enter to close this backend window'
    exit $LASTEXITCODE
}
