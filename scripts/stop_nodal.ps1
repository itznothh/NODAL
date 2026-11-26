$ErrorActionPreference = 'Stop'
$statePath = Join-Path $env:LOCALAPPDATA 'NODAL\local-demo\processes.json'

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host 'No launcher state was found. No processes were stopped.' -ForegroundColor Yellow
    exit 0
}

try {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($state.database -ne 'nodal_phase8_audit' -or $state.mongo_uri -ne 'mongodb://127.0.0.1:27017') {
        throw 'Launcher state does not match the expected isolated Phase 8 runtime; refusing to stop any process.'
    }
    foreach ($entry in @($state.processes)) {
        $process = Get-Process -Id ([int]$entry.ProcessId) -ErrorAction SilentlyContinue
        if (-not $process) {
            Write-Host "$($entry.Name): already stopped."
            continue
        }
        $started = $process.StartTime.ToUniversalTime().ToString('o')
        if ($started -ne [string]$entry.StartTimeUtc) {
            Write-Warning "PID $($entry.ProcessId) has been reused; leaving it untouched."
            continue
        }
        & taskkill.exe /PID ([string]$entry.ProcessId) /T /F
        if ($LASTEXITCODE -eq 0) { Write-Host "$($entry.Name): stopped process tree rooted at PID $($entry.ProcessId)." }
        else { Write-Warning "$($entry.Name): taskkill returned $LASTEXITCODE for PID $($entry.ProcessId)." }
    }
    Remove-Item -LiteralPath $statePath -Force
    Write-Host 'MongoDB was left running because it may be shared by other local applications.' -ForegroundColor Green
} catch {
    Write-Host "NODAL shutdown error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
