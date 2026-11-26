param([switch]$CheckOnly)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $projectRoot '.venv-vision\Scripts\python.exe'
$frontendRoot = Join-Path $projectRoot 'frontend'
$frontendModules = Join-Path $frontendRoot 'node_modules'
$backendRunner = Join-Path $PSScriptRoot 'run_nodal_backend.ps1'
$frontendRunner = Join-Path $PSScriptRoot 'run_nodal_frontend.ps1'
$stateDirectory = Join-Path $env:LOCALAPPDATA 'NODAL\local-demo'
$statePath = Join-Path $stateDirectory 'processes.json'
$mongoServiceName = 'MongoDB'
$frontendUrl = 'http://127.0.0.1:5174'
$backendUrl = 'http://127.0.0.1:5000'

function Get-ListeningProcesses([int]$Port) {
    $results = @()
    try {
        $connections = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
        foreach ($connection in $connections) {
            $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
            $results += [pscustomobject]@{
                Port = $Port
                ProcessId = [int]$connection.OwningProcess
                Name = if ($process) { $process.ProcessName } else { 'unknown' }
            }
        }
    } catch {
        # netstat is a read-only fallback for restricted Windows CIM environments.
        $lines = & netstat.exe -ano -p tcp 2>$null
        foreach ($line in $lines) {
            if ($line -match '^\s*TCP\s+\S+:([0-9]+)\s+\S+\s+LISTENING\s+([0-9]+)\s*$' -and [int]$matches[1] -eq $Port) {
                $processId = [int]$matches[2]
                $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                $results += [pscustomobject]@{
                    Port = $Port
                    ProcessId = $processId
                    Name = if ($process) { $process.ProcessName } else { 'unknown' }
                }
            }
        }
    }
    return $results | Sort-Object ProcessId -Unique
}

function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMilliseconds = 1500) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) { return $false }
        $client.EndConnect($pending)
        return $client.Connected
    } catch { return $false }
    finally { $client.Close() }
}

function Get-MongoService {
    try {
        return Get-Service -Name $mongoServiceName -ErrorAction Stop
    } catch {
        throw "MongoDB Windows service '$mongoServiceName' could not be inspected. Confirm MongoDB Community Server is installed as this service and run the launcher with an account allowed to query Windows services. Details: $($_.Exception.Message)"
    }
}

function Stop-RecordedProcessTree($Entry) {
    $process = Get-Process -Id ([int]$Entry.ProcessId) -ErrorAction SilentlyContinue
    if (-not $process) { return $false }
    $started = $process.StartTime.ToUniversalTime().ToString('o')
    if ($started -ne [string]$Entry.StartTimeUtc) {
        Write-Warning "PID $($Entry.ProcessId) has been reused; leaving it untouched."
        return $false
    }
    & taskkill.exe /PID ([string]$Entry.ProcessId) /T /F 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

try {
    Write-Host 'NODAL local demo startup' -ForegroundColor Green
    Write-Host "Project: $projectRoot"
    Write-Host 'Database target: nodal_phase8_audit (isolated audit mode)'
    Write-Host 'MongoDB URI: mongodb://127.0.0.1:27017'

    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw "The existing vision Python environment was not found: $pythonPath" }
    if (-not (Test-Path -LiteralPath $frontendModules -PathType Container)) { throw "Frontend dependencies are missing at $frontendModules. Install the project's existing dependencies with npm install before starting NODAL." }
    if (-not (Test-Path -LiteralPath $backendRunner -PathType Leaf) -or -not (Test-Path -LiteralPath $frontendRunner -PathType Leaf)) { throw 'A NODAL child-service launcher script is missing from the scripts directory.' }
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'npm.cmd was not found on PATH. Install/use the existing Node.js environment; this launcher does not install packages.' }

    $backendOwners = Get-ListeningProcesses 5000
    $frontendOwners = Get-ListeningProcesses 5174
    foreach ($owner in @($backendOwners) + @($frontendOwners)) {
        Write-Host "Port $($owner.Port) is occupied by $($owner.Name) (PID $($owner.ProcessId))." -ForegroundColor Yellow
    }
    if (-not $backendOwners -and -not $frontendOwners) { Write-Host 'Ports 5000 and 5174 are available.' }
    if (-not $CheckOnly -and ($backendOwners.Count -gt 0 -or $frontendOwners.Count -gt 0)) {
        throw 'No NODAL server was launched. Existing listeners are not reused because their database/runtime configuration cannot be verified here. Inspect or stop the identified process, then retry.'
    }

    $mongoService = Get-MongoService
    Write-Host "MongoDB service: $($mongoService.Name) - $($mongoService.Status)"
    if ($CheckOnly) {
        Write-Host 'CHECK ONLY: no service will be started, no application process will launch, and no database will be contacted.' -ForegroundColor Yellow
    } elseif ($mongoService.Status -ne 'Running') {
        Write-Host 'MongoDB is stopped; requesting service start...'
        try { Start-Service -Name $mongoServiceName -ErrorAction Stop }
        catch { throw "Could not start the MongoDB service. Run Windows as an account with service-start permission, then retry. Details: $($_.Exception.Message)" }
        $deadline = (Get-Date).AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 500
            $mongoService = Get-MongoService
        } while ($mongoService.Status -ne 'Running' -and (Get-Date) -lt $deadline)
        if ($mongoService.Status -ne 'Running') { throw 'MongoDB service did not reach Running state within 30 seconds.' }
        Write-Host 'MongoDB service started.' -ForegroundColor Green
    }

    if ($CheckOnly) {
        Write-Host 'Preflight checks passed; no runtime or database writes were performed.' -ForegroundColor Green
        exit 0
    }

    if (-not (Test-TcpPort '127.0.0.1' 27017)) {
        throw 'MongoDB service is running but 127.0.0.1:27017 is not accepting TCP connections. No app servers were started.'
    }
    Write-Host 'MongoDB TCP endpoint is reachable at 127.0.0.1:27017.' -ForegroundColor Green

    if (Test-Path -LiteralPath $statePath) {
        try {
            $oldState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            foreach ($entry in @($oldState.processes)) {
                $oldProcess = Get-Process -Id ([int]$entry.ProcessId) -ErrorAction SilentlyContinue
                if ($oldProcess -and $oldProcess.StartTime.ToUniversalTime().ToString('o') -eq [string]$entry.StartTimeUtc) {
                    throw "A NODAL launcher-managed process is still running (PID $($entry.ProcessId)). Use STOP_NODAL.bat before starting another copy."
                }
            }
        } catch {
            if ($_.Exception.Message -like 'A NODAL launcher-managed process*') { throw }
            Write-Warning 'Old launcher state could not be read; it will be replaced after preflight. No process was stopped.'
        }
    }

    # This secret is generated per launch, inherited only by the two child runtimes,
    # and is never printed or written to disk.
    $secretBytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($secretBytes) } finally { $rng.Dispose() }
    $env:NODAL_SECRET_KEY = [Convert]::ToBase64String($secretBytes)
    [Array]::Clear($secretBytes, 0, $secretBytes.Length)
    $env:NODAL_AUDIT_MODE = 'true'
    $env:NODAL_DB_NAME = 'nodal_phase8_audit'
    $env:MONGO_URI = 'mongodb://127.0.0.1:27017'
    $env:NODAL_ENV = 'development'
    $env:VITE_API_BASE = 'http://127.0.0.1:5000'

    New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
    $launched = @()
    try {
        $backendProcess = Start-Process -FilePath 'powershell.exe' -WorkingDirectory $projectRoot -PassThru -ArgumentList @(
            '-NoLogo', '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$backendRunner`""
        )
        Start-Sleep -Milliseconds 300
        $backendProcess.Refresh()
        if ($backendProcess.HasExited) { throw 'The Flask terminal exited immediately. Check its window for the startup error.' }
        $launched += [pscustomobject]@{ Name = 'backend'; ProcessId = $backendProcess.Id; StartTimeUtc = $backendProcess.StartTime.ToUniversalTime().ToString('o') }
        $state = [ordered]@{ database = 'nodal_phase8_audit'; mongo_uri = 'mongodb://127.0.0.1:27017'; processes = @($launched) }
        $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
        Write-Host "Flask terminal started (PID $($backendProcess.Id)); waiting for /health..."

        $backendReady = $false
        $backendDeadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $backendDeadline) {
            try {
                $health = Invoke-RestMethod -Uri "$backendUrl/health" -TimeoutSec 3
                if ($health.status -eq 'ok') { $backendReady = $true; break }
            } catch { Start-Sleep -Milliseconds 800 }
        }
        if (-not $backendReady) { throw 'Flask did not return a healthy response within 60 seconds. Check the backend terminal; the launcher will stop only its recorded server process.' }
        Write-Host "Flask is healthy at $backendUrl (database target: nodal_phase8_audit)." -ForegroundColor Green

        $frontendProcess = Start-Process -FilePath 'powershell.exe' -WorkingDirectory $frontendRoot -PassThru -ArgumentList @(
            '-NoLogo', '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$frontendRunner`""
        )
        Start-Sleep -Milliseconds 300
        $frontendProcess.Refresh()
        if ($frontendProcess.HasExited) { throw 'The Vite terminal exited immediately. Check its window for the startup error.' }
        $launched += [pscustomobject]@{ Name = 'frontend'; ProcessId = $frontendProcess.Id; StartTimeUtc = $frontendProcess.StartTime.ToUniversalTime().ToString('o') }
        $state = [ordered]@{ database = 'nodal_phase8_audit'; mongo_uri = 'mongodb://127.0.0.1:27017'; processes = @($launched) }
        $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
        Write-Host "Vite terminal started (PID $($frontendProcess.Id)); waiting for frontend..."

        $frontendReady = $false
        $frontendDeadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $frontendDeadline) {
            try {
                $page = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 3
                if ($page.StatusCode -eq 200) { $frontendReady = $true; break }
            } catch { Start-Sleep -Milliseconds 800 }
        }
        if (-not $frontendReady) { throw 'Vite did not return HTTP 200 within 60 seconds. Check the frontend terminal; the launcher will stop only its recorded server processes.' }
        Write-Host "Frontend is ready at $frontendUrl." -ForegroundColor Green
        Start-Process $frontendUrl | Out-Null
        Write-Host 'Opened NODAL in the default browser.' -ForegroundColor Green
        Write-Host 'Use STOP_NODAL.bat to stop only the Flask and Vite process trees started by this launcher. MongoDB is left running.'
    } catch {
        foreach ($entry in @($launched)) { [void](Stop-RecordedProcessTree $entry) }
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        throw
    }
} catch {
    Write-Host "NODAL startup error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
