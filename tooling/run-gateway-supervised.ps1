<#
.SYNOPSIS
  Keeps the herdr-notify gateway alive, bound ONLY to loopback and the Tailscale address.

.DESCRIPTION
  Supervises the gateway process: if the child exits or is killed, it is started
  again after 5 s. Binds explicit addresses, never 0.0.0.0: the gateway can send
  keys to agents, which is control of this machine. Logs (no secrets) go to
  %LOCALAPPDATA%\herdr-notify\gateway.log.

  Installed as a windowless logon task that also re-arms every minute and restarts
  on failure, so even a supervisor that is killed out from under the task is brought
  back without a new login.

  Install once (no admin needed):
    powershell -ExecutionPolicy Bypass -File tooling\run-gateway-supervised.ps1 -Install
  Remove it:
    powershell -ExecutionPolicy Bypass -File tooling\run-gateway-supervised.ps1 -Uninstall
#>
param([switch]$Install, [switch]$Uninstall, [int]$Port = 8787)

# A helper's non-zero exit and a child's stderr must never abort this script: a
# supervisor that dies on the first hiccup is the bug this file exists to avoid.
$ErrorActionPreference = 'Continue'

$TaskName = 'herdr-notify-gateway'
$MutexName = 'Local\herdr-notify-gateway-supervisor'
$Root = Split-Path -Parent $PSScriptRoot
$Self = $PSCommandPath
$LogDir = Join-Path $env:LOCALAPPDATA 'herdr-notify'
$Log = Join-Path $LogDir 'gateway.log'

function Write-Log([string]$Message) {
    try {
        if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
        Add-Content -LiteralPath $Log -Value "[$(Get-Date -Format s)] $Message" -Encoding UTF8
    } catch { }
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "removed task $TaskName"; return
}

if ($Install) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Self`" -Port $Port"
    $atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date) `
        -RepetitionInterval (New-TimeSpan -Minutes 1) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances Parallel
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $atLogon, $watchdog `
        -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "installed and started task $TaskName"; return
}

# One supervisor per machine. The watchdog trigger may start many instances, and a
# second one would only fight the first for the port; whoever holds the mutex owns
# the gateway and releases it the instant the process dies, so a later instance takes over.
$createdNew = $false
$mutex = [System.Threading.Mutex]::new($true, $MutexName, [ref]$createdNew)
if (-not $createdNew) { $mutex.Dispose(); return }

try {
    $Python = Join-Path $Root 'gateway\.venv\Scripts\python.exe'
    $env:PYTHONPATH = Join-Path $Root 'gateway\src'
    $env:PYTHONUNBUFFERED = '1'
    $env:PYTHONIOENCODING = 'utf-8'

    while ($true) {
        # Tailscale may not be up yet at logon: wait for its address; loopback alone
        # is not enough, but it is always safe to bind.
        $ts = $null
        try { $ts = (& tailscale ip -4 2>$null | Select-Object -First 1) } catch { }
        $hosts = if ($ts) { "127.0.0.1,$ts" } else { '127.0.0.1' }

        Write-Log "starting gateway on $hosts`:$Port"
        $code = 1
        try {
            # Run through cmd so the child's stdout and stderr are appended to the log
            # as plain bytes. Invoking python directly routes its stderr through
            # PowerShell's error stream, and with ErrorActionPreference=Stop a single
            # stderr write (a bind failure, a traceback) tore the supervisor down.
            $child = '"{0}" -m herdr_notify.cli serve --host {1} --port {2} >> "{3}" 2>&1' `
                -f $Python, $hosts, $Port, $Log
            & $env:ComSpec /d /c $child
            $code = $LASTEXITCODE
        } catch {
            Write-Log "supervisor error: $($_.Exception.Message)"
        }
        Write-Log "gateway exited ($code); restarting in 5 s"
        Start-Sleep -Seconds 5
    }
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
