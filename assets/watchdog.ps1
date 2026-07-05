# RadioAI Studio Pro — crash watchdog (spawned BY the app at boot).
# Waits for the app process to exit, then:
#   clean-exit marker fresh (<120s)  -> intentional close -> exit quietly
#   marker stale/absent              -> CRASH -> relaunch after 10s
# Crash-loop guard: 3 restarts within 10 minutes -> give up + log.
# See core/watchdog.py for the full design notes.

param(
    [Parameter(Mandatory=$true)][int]$AppPid,
    [Parameter(Mandatory=$true)][string]$ExePath,
    [Parameter(Mandatory=$true)][string]$MarkerPath,
    [Parameter(Mandatory=$true)][string]$LogPath,
    [Parameter(Mandatory=$true)][string]$RestartLog
)

function Write-WdLog([string]$msg) {
    try {
        Add-Content -Path $LogPath -Encoding UTF8 -Value (
            "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg)
    } catch {}
}

try {
    $proc = Get-Process -Id $AppPid -ErrorAction Stop
} catch {
    Write-WdLog "app pid $AppPid not found at watchdog start - exiting"
    exit 0
}

Write-WdLog "watching pid $AppPid ($ExePath)"
$proc.WaitForExit()

# Give the clean-exit marker writer a moment to flush.
Start-Sleep -Seconds 5

if (Test-Path $MarkerPath) {
    $age = ((Get-Date) - (Get-Item $MarkerPath).LastWriteTime).TotalSeconds
    if ($age -lt 120) {
        Write-WdLog "clean exit detected (marker ${age}s old) - standing down"
        exit 0
    }
}

# Crash-loop guard: count restarts in the last 10 minutes.
$recent = 0
if (Test-Path $RestartLog) {
    $cutoff = (Get-Date).AddMinutes(-10)
    foreach ($line in (Get-Content $RestartLog -Tail 20)) {
        try {
            $ts = [datetime]::ParseExact(
                $line.Substring(0, 19), "yyyy-MM-dd HH:mm:ss", $null)
            if ($ts -gt $cutoff) { $recent++ }
        } catch {}
    }
}
if ($recent -ge 3) {
    Write-WdLog ("CRASH DETECTED but $recent restarts in the last " +
                 "10 min - giving up (crash loop). Operator attention needed.")
    exit 1
}

Write-WdLog "CRASH DETECTED (no fresh clean-exit marker) - relaunching in 10s"
Start-Sleep -Seconds 10
try {
    Add-Content -Path $RestartLog -Encoding UTF8 -Value (
        Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    Start-Process -FilePath $ExePath
    Write-WdLog "relaunched $ExePath"
} catch {
    Write-WdLog "relaunch FAILED: $($_.Exception.Message)"
}
exit 0
