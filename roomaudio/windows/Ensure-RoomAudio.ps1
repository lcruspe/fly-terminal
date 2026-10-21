# Idempotent RoomAudio/AudioMonitor recovery for the current interactive user.
# No microphone mode changes, no forced process termination, no duplicate workers.
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
