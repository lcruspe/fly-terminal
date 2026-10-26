# Idempotent RoomAudio/AudioMonitor recovery for the current interactive user.
# Preserve selected microphone mode; restart only stale managers and start missing workers.
$ErrorActionPreference = 'Stop'
$room = Join-Path $env:LOCALAPPDATA 'RoomAudio'
$python = 'D:\Conda\python.exe'
$pythonw = 'D:\Conda\pythonw.exe'
$watch = 'D:\Installed\AudioMonitor\autostart.py'
$log = Join-Path $room 'stack-ensure.log'

function Write-Event([string]$message) {
    Add-Content -LiteralPath $log -Value ("$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message") -Encoding UTF8
}
function Exists-Process([string]$name) {
    foreach ($proc in $script:processes) {
        $line = [string]$proc.CommandLine
        if ($line.IndexOf($name,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
    }
    return $false
}

try {
    $processes = @(Get-CimInstance Win32_Process |
        Where-Object { $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine })
    # Recover a manager that still has a PID but no longer runs its control
    # loop. Newly started processes get a two-minute initialization grace.
    $managerPath = Join-Path $room 'capture_manager.py'
    $heartbeatPath = Join-Path $room 'capture-manager.heartbeat'
    $heartbeatUtc = if (Test-Path -LiteralPath $heartbeatPath -PathType Leaf) {
        (Get-Item -LiteralPath $heartbeatPath).LastWriteTimeUtc
    } else { [datetime]::MinValue }
    $utcNow = [datetime]::UtcNow
    $staleSeconds = ($utcNow - $heartbeatUtc).TotalSeconds
    foreach ($proc in @($processes | Where-Object {
        ([string]$_.CommandLine).IndexOf($managerPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
    })) {
        $ageSeconds = ($utcNow - $proc.CreationDate.ToUniversalTime()).TotalSeconds
        if ($ageSeconds -ge 120 -and $staleSeconds -ge 90) {
            & "$env:WINDIR\System32\taskkill.exe" /PID ([string]$proc.ProcessId) /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Cannot stop stale manager PID=$($proc.ProcessId)"
            }
            Write-Event ("Restart stale capture manager PID=" + $proc.ProcessId +
                         " heartbeat_age_s=" + [Math]::Round($staleSeconds))
            $processes = @($processes | Where-Object { $_.ProcessId -ne $proc.ProcessId })
        }
    }
    $workers = @(
        @{ Path=$watch; Python=$pythonw; Dir=(Split-Path -Parent $watch) },
        @{ Path=(Join-Path $room 'capture_manager.py'); Python=$python; Dir=$room },
        @{ Path=(Join-Path $room 'uploader.py'); Python=$python; Dir=$room }
    )
    foreach ($worker in $workers) {
        if (Exists-Process $worker.Path) { continue }
        if (!(Test-Path -LiteralPath $worker.Path -PathType Leaf) -or
            !(Test-Path -LiteralPath $worker.Python -PathType Leaf)) {
            Write-Event ("Missing program: " + $worker.Path)
            continue
        }
        $argument = '-u "' + $worker.Path + '"'
        $started = Start-Process -FilePath $worker.Python -ArgumentList $argument `
            -WorkingDirectory $worker.Dir -WindowStyle Hidden -PassThru
        Write-Event ("Started " + (Split-Path -Leaf $worker.Path) +
                     " PID=" + $started.Id)
    }
} catch {
    Write-Event ("ERROR " + $_.Exception.Message)
    exit 1
}
