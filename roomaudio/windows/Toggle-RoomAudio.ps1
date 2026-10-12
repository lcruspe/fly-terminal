param([ValidateSet("Toggle","Start","Stop","Status")][string]$Action="Toggle")
$ErrorActionPreference="Stop"
$room=Join-Path $env:LOCALAPPDATA "RoomAudio"
$audioRoot="D:\Installed\AudioMonitor"
$python="D:\Conda\python.exe"
$pythonw="D:\Conda\pythonw.exe"
$log=Join-Path $room "stack-toggle.log"

function Say([string]$message){
    try{Add-Content -LiteralPath $log -Value ("$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') "+$message) -Encoding UTF8}catch{}
    Write-Host $message
}
function StackProcesses{
    $names=@("python.exe","pythonw.exe","powershell.exe","pwsh.exe","cmd.exe","ffmpeg.exe","mediamtx.exe")
    @(Get-CimInstance Win32_Process | Where-Object {
        if ($_.ProcessId -eq $PID -or -not $_.CommandLine -or $_.Name -notin $names){return $false}
        $c=[string]$_.CommandLine
        $isRoom=($c -match '(?i)[\\/]RoomAudio[\\/](?:capture_manager|capture_ks|capture_voice|uploader)\.py\b') -or
                ($c -match '(?i)[\\/]RoomAudio[\\/](?:capture|upload)\.ps1\b') -or
                ($_.Name -ieq "ffmpeg.exe" -and $c -match '(?i)[\\/]RoomAudio[\\/]buffer')
        $isAudio=($c -match '(?i)[\\/]Installed[\\/]AudioMonitor[\\/](?:autostart\.py|web[\\/](?:server|record_control)\.py)') -or
                 ($_.Name -ieq "mediamtx.exe" -and $c -match '(?i)[\\/]Installed[\\/]AudioMonitor[\\/]') -or
                 ($_.Name -ieq "ffmpeg.exe" -and $c -match '(?i)[\\/]Installed[\\/]AudioMonitor[\\/]')
        return ($isRoom -or $isAudio)
    })
}
function StopStack{
    for($attempt=0;$attempt -lt 4;$attempt++){
        $all=@(StackProcesses)
        if($all.Count -eq 0){break}
        $ids=@{};foreach($p in $all){$ids[[int]$p.ProcessId]=$true}
        $roots=@($all | Where-Object {-not $ids.ContainsKey([int]$_.ParentProcessId)})
        if($roots.Count -eq 0){$roots=$all}
        $roots=@($roots | Sort-Object @{Expression={if($_.CommandLine -match '(?i)AudioMonitor[\\/]autostart\.py'){0}else{1}}})
        foreach($p in $roots){
            try{
                & "$env:WINDIR\System32\taskkill.exe" /PID ([string]$p.ProcessId) /T /F 2>&1 | Out-Null
                Say ("Stopped "+$p.Name+" PID="+$p.ProcessId)
            }catch{Say ("Already stopped PID="+$p.ProcessId)}
        }
        Start-Sleep -Seconds 1
    }
    $left=@(StackProcesses)
    if($left.Count -ne 0){throw "Failed to stop PID: $(($left | ForEach-Object ProcessId) -join ',')"}
    Say "RoomAudio and AudioMonitor STOPPED. Microphone capture is inactive."
}
function StartStack{
    foreach($path in @($python,$pythonw,(Join-Path $room "capture_manager.py"),(Join-Path $room "uploader.py"),(Join-Path $audioRoot "autostart.py"))){
        if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw "Missing file: $path"}
    }
    if(@(StackProcesses).Count){StopStack}
    try{
        $watch=Start-Process -FilePath $pythonw -ArgumentList ('"'+(Join-Path $audioRoot "autostart.py")+'"') -WorkingDirectory $audioRoot -WindowStyle Hidden -PassThru
        Say ("AudioMonitor watchdog started PID="+$watch.Id)
        foreach($name in @("capture_manager.py","uploader.py")){
            $worker=Start-Process -FilePath $python -ArgumentList ('-u "'+(Join-Path $room $name)+'"') -WorkingDirectory $room -WindowStyle Hidden -PassThru
            Say ($name+" started PID="+$worker.Id)
        }
        Start-Sleep -Seconds 5
        $procs=@(StackProcesses)
        $capture=@($procs | Where-Object {$_.CommandLine -match '(?i)[\\/]capture_manager\.py\b'}).Count -gt 0
        $upload=@($procs | Where-Object {$_.CommandLine -match '(?i)[\\/]uploader\.py\b'}).Count -gt 0
        $audio=@($procs | Where-Object {$_.CommandLine -match '(?i)[\\/]AudioMonitor[\\/]autostart\.py\b'}).Count -gt 0
        if(-not ($capture -and $upload -and $audio)){throw "Invalid startup: capture=$capture uploader=$upload AudioMonitor=$audio"}
        Say "RoomAudio + AudioMonitor RUNNING. Recording modes use the saved configuration."
    }catch{StopStack;throw}
}
try{
    switch($Action){
        "Status" {
            $p=@(StackProcesses)
            if($p.Count -eq 0){Say "RoomAudio + AudioMonitor STOPPED"}
            else{Say ("Audio services running: "+$p.Count+" processes");$p|Select-Object ProcessId,Name,CommandLine|Format-Table -Wrap}
        }
        "Stop" {StopStack}
        "Start" {StartStack}
        "Toggle" {if(@(StackProcesses).Count){StopStack}else{StartStack}}
    }
}catch{Say ("ERROR: "+$_.Exception.Message);exit 1}