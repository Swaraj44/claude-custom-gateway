<#
.SYNOPSIS
    Installs Claude Custom Gateway as a Windows Task Scheduler task running as the current user.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1 -AtStartup
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'claude-custom-gateway'),
    [string]$Python = '',
    [string]$TaskName = 'ClaudeCustomGateway',
    [switch]$AtStartup,
    [switch]$NoStart
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$User = "$env:USERDOMAIN\$env:USERNAME"

function Test-Python([string[]]$Cmd) {
    $ErrorActionPreference = 'Continue'
    if (-not (Get-Command $Cmd[0] -ErrorAction SilentlyContinue)) { return $false }
    $rest = @($Cmd | Select-Object -Skip 1)
    $null = & $Cmd[0] @rest -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments, [string]$What) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

$pyCmd = $null
if ($Python) {
    if (-not (Test-Python @($Python))) { throw "'$Python' is not a working Python 3.9+ interpreter" }
    $pyCmd = @($Python)
} else {
    foreach ($candidate in @('py -3', 'python', 'python3')) {
        $parts = $candidate -split ' '
        if (Test-Python $parts) { $pyCmd = $parts; break }
    }
}
if (-not $pyCmd) { throw 'Python 3.9+ not found. Install it from https://www.python.org/downloads/ or pass -Python <path>' }

$credential = $null
if ($AtStartup) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { throw '-AtStartup needs an elevated (Run as administrator) PowerShell' }
    $credential = Get-Credential -UserName $User -Message 'Windows password for the account the gateway runs as'
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Stopping existing task '$TaskName'..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$venv = Join-Path $InstallDir 'venv'
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }

Write-Host "Creating virtualenv in $venv ..."
$pyRest = @($pyCmd | Select-Object -Skip 1)
Invoke-Checked $pyCmd[0] ($pyRest + @('-m', 'venv', $venv)) 'Creating the virtualenv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
$venvPythonw = Join-Path $venv 'Scripts\pythonw.exe'

Write-Host 'Installing the gateway and its dependencies...'
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check', $Root) 'pip install'

$launcher = Join-Path $InstallDir 'gateway_task.py'
Copy-Item -Force (Join-Path $PSScriptRoot 'gateway_task.py') $launcher

$config = Join-Path $InstallDir 'config.env'
$newKey = $null
if (-not (Test-Path $config)) {
    $newKey = [guid]::NewGuid().ToString('N')
    $text = (Get-Content -Raw (Join-Path $PSScriptRoot 'config.env')) -replace 'CLAUDE_SERVICE_API_KEY=change-me', "CLAUDE_SERVICE_API_KEY=$newKey"
    [IO.File]::WriteAllText($config, $text, (New-Object Text.UTF8Encoding $false))
}

$action = New-ScheduledTaskAction -Execute $venvPythonw -Argument ('"{0}"' -f $launcher) -WorkingDirectory $InstallDir
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew
$description = 'Claude Custom Gateway - REST/OpenAI-compatible gateway to the Claude Code CLI'

if ($AtStartup) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description $description -User $User -Password $credential.GetNetworkCredential().Password `
        -RunLevel Limited -Force | Out-Null
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Description $description -Principal $principal -Force | Out-Null
}
Write-Host "Registered scheduled task '$TaskName' (runs as $User $(if ($AtStartup) { 'at boot' } else { 'at logon' }))."

$port = 6069
$portMatch = Select-String -Path $config -Pattern '^\s*CLAUDE_SERVICE_PORT\s*=\s*(\d+)' | Select-Object -First 1
if ($portMatch) { $port = [int]$portMatch.Matches[0].Groups[1].Value }

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $TaskName
    $healthy = $false
    for ($i = 0; $i -lt 30 -and -not $healthy; $i++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$port/health"
            $healthy = $true
            Write-Host "Gateway is up. Claude CLI: $($health.claude_cli)"
        } catch { }
    }
    if (-not $healthy) {
        Write-Warning "Gateway did not answer on port $port yet. Check $(Join-Path $InstallDir 'logs\gateway.log')"
    }
}

Write-Host ''
Write-Host "Config:   $config"
if ($newKey) { Write-Host "API key:  $newKey  (generated; change it in the config if you like)" }
Write-Host "Logs:     $(Join-Path $InstallDir 'logs\gateway.log')"
Write-Host "Web UI:   http://127.0.0.1:$port/"
Write-Host "OpenAI:   http://127.0.0.1:$port/v1"
Write-Host "Restart:  Stop-ScheduledTask $TaskName; Start-ScheduledTask $TaskName"
Write-Host "Remove:   powershell -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'uninstall.ps1')`""