<#
.SYNOPSIS
    Removes the Claude Custom Gateway scheduled task and its install directory.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\uninstall.ps1 -KeepConfig
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'claude-custom-gateway'),
    [string]$TaskName = 'ClaudeCustomGateway',
    [switch]$KeepConfig
)

$ErrorActionPreference = 'Stop'

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
    Start-Sleep -Seconds 2
} else {
    Write-Host "Scheduled task '$TaskName' not found."
}

if (Test-Path $InstallDir) {
    if ($KeepConfig) {
        foreach ($item in @('venv', 'logs', 'gateway_task.py')) {
            $path = Join-Path $InstallDir $item
            if (Test-Path $path) { Remove-Item -Recurse -Force $path }
        }
        Write-Host "Removed $InstallDir (kept config.env)."
    } else {
        Remove-Item -Recurse -Force $InstallDir
        Write-Host "Removed $InstallDir."
    }
}