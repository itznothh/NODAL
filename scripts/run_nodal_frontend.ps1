$ErrorActionPreference = 'Stop'
$frontendRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\frontend')).Path
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) {
    Write-Error 'npm.cmd was not found on PATH.'
    Read-Host 'Press Enter to close this frontend window'
    exit 1
}

$env:VITE_API_BASE = 'http://127.0.0.1:5000'
Set-Location $frontendRoot
Write-Host 'NODAL Vite - API http://127.0.0.1:5000 - strict port 5174' -ForegroundColor Green
& $npm.Source run dev -- --host 127.0.0.1 --port 5174 --strictPort
if ($LASTEXITCODE -ne 0) {
    Write-Host "Vite exited with code $LASTEXITCODE." -ForegroundColor Red
    Read-Host 'Press Enter to close this frontend window'
    exit $LASTEXITCODE
}
