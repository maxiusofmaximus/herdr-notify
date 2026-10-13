<#
.SYNOPSIS
    Operator surface for the supervised herdr-notify gateway.

.DESCRIPTION
    The gateway is never launched by hand. It runs under the scheduled task
    created by tooling/run-gateway-supervised.ps1, which keeps it alive and
    bound to loopback plus the Tailscale address. This script drives that task:
    install/uninstall delegate to the supervisor, the remaining actions act on
    the task and never start the gateway any other way.

.PARAMETER Action
    install | uninstall | start | stop | restart | status | logs

.PARAMETER Port
    Gateway port; must match the installed task (default 8787).

.PARAMETER Lines
    Trailing log lines `logs` shows before following (default 40).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tooling\herdr-notify-service.ps1 install

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tooling\herdr-notify-service.ps1 logs
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('install', 'uninstall', 'start', 'stop', 'restart', 'status', 'logs')]
    [string] $Action,
    [int] $Port = 8787,
    [int] $Lines = 40
)

$ErrorActionPreference = 'Stop'

$TaskName = 'herdr-notify-gateway'
$Root = Split-Path -Parent $PSScriptRoot
$Supervisor = Join-Path $PSScriptRoot 'run-gateway-supervised.ps1'
$LogDir = Join-Path $env:LOCALAPPDATA 'herdr-notify'
$Log = Join-Path $LogDir 'gateway.log'
$VenvPython = Join-Path $Root 'gateway\.venv\Scripts\python.exe'

function Write-Step { param([string] $m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string] $m) Write-Host "    $m" -ForegroundColor Green }
function Write-Note { param([string] $m) Write-Host "    $m" -ForegroundColor Yellow }

function Get-GatewayTask {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

function Test-GatewayListening {
    try {
        return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).Count -gt 0
    } catch {
        return $false
    }
}

function Get-GatewayProcess {
    try {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    } catch {
        $connections = @()
    }
    $ids = @($connections | ForEach-Object { $_.OwningProcess } | Sort-Object -Unique)
    foreach ($id in $ids) {
        try {
            $process = Get-Process -Id $id -ErrorAction Stop
            if ($process.Path -ieq $VenvPython) { $process }
        } catch { }
    }
}

function Start-GatewayService {
    if (-not (Get-GatewayTask)) {
        Write-Note "not installed; run: $PSCommandPath install"
        return $false
    }
    if ((Get-GatewayTask).State -eq 'Running') {
        Write-Ok 'task already running'
        return $true
    }
    Start-ScheduledTask -TaskName $TaskName
    Write-Ok "started task $TaskName"
    return $true
}

function Stop-GatewayService {
    if (Get-GatewayTask) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    $stopped = 0
    foreach ($process in (Get-GatewayProcess)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $stopped++
    }
    if ($stopped -gt 0) { Write-Ok "stopped $stopped gateway process(es)" }
    else { Write-Ok 'no gateway process was listening' }
}

function Show-Status {
    $task = Get-GatewayTask
    $state = if ($task) { $task.State } else { 'not installed' }
    $gateway = if (Test-GatewayListening) { "listening on 127.0.0.1:$Port" } else { "not listening on 127.0.0.1:$Port" }
    Write-Host "task    : $TaskName ($state)"
    Write-Host "gateway : $gateway"
    Write-Host "log     : $Log"
}

switch ($Action) {
    'install' {
        Write-Step "Installing the supervised gateway task on port $Port"
        & $Supervisor -Install -Port $Port
        Write-Note "check with: $PSCommandPath status"
        Write-Note "logs:       $PSCommandPath logs"
    }
    'uninstall' {
        Write-Step 'Removing the supervised gateway task'
        & $Supervisor -Uninstall
    }
    'start' {
        Write-Step 'Starting the gateway'
        [void](Start-GatewayService)
    }
    'stop' {
        Write-Step 'Stopping the gateway'
        Stop-GatewayService
    }
    'restart' {
        Write-Step 'Restarting the gateway'
        Stop-GatewayService
        Start-Sleep -Seconds 1
        [void](Start-GatewayService)
    }
    'status' { Show-Status }
    'logs' {
        if (-not (Test-Path -LiteralPath $Log)) {
            Write-Note "no log yet at $Log"
            return
        }
        Get-Content -LiteralPath $Log -Tail $Lines -Wait
    }
}
