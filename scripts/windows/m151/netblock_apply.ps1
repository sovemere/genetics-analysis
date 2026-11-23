# Elevated half of netblock.ps1 apply; run it through netblock.ps1, not directly.
#
# Blocks all outbound traffic on every Windows Firewall profile except for one allowed
# program (Claude Code, so the agent driving the run keeps working), audits every refused
# connection (Security event 5157, which names the program), and schedules an automatic
# restore as SYSTEM so a block can never outlive the run by more than -AutoRestoreHours,
# even across a reboot. What it changed is saved to <StateDir>\state.json for restore.
#
# The scheduled restore runs netblock_restore.ps1 from this checkout. A script that runs as
# SYSTEM from a user-writable path is an elevation route while the task exists; on this
# single-owner machine that is accepted for the hours of a session, and restore removes it.
param(
    [Parameter(Mandatory)][string]$StateDir,
    [string]$AllowProgram = '',
    [double]$AutoRestoreHours = 8
)
$ErrorActionPreference = 'Stop'
$AuditGuid = '{0CCE9226-69AE-11D9-BED3-505054503030}'  # Filtering Platform Connection
$TaskName = 'genetics-netblock-autorestore'
$log = Join-Path $StateDir 'netblock.log'
function Write-Log($m) { "$(Get-Date -Format o) apply: $m" | Add-Content -Path $log -Encoding UTF8 }

try {
    $statePath = Join-Path $StateDir 'state.json'
    if (Test-Path $statePath) { throw 'a block is already applied (state.json exists); restore it first' }
    if ($AllowProgram -and -not (Test-Path $AllowProgram)) { throw "allowed program not found: $AllowProgram" }

    $audit = auditpol /get /subcategory:$AuditGuid /r | Where-Object { $_ } | ConvertFrom-Csv
    $profiles = @(Get-NetFirewallProfile -PolicyStore PersistentStore | ForEach-Object {
            [ordered]@{ Name = "$($_.Name)"; DefaultOutboundAction = "$($_.DefaultOutboundAction)"; LogBlocked = "$($_.LogBlocked)" }
        })
    $restoreAt = (Get-Date).AddHours($AutoRestoreHours)
    $state = [ordered]@{
        id              = [guid]::NewGuid().ToString()
        applied_utc     = (Get-Date).ToUniversalTime().ToString('o')
        auto_restore_at = $restoreAt.ToString('o')
        allow_program   = $AllowProgram
        audit_inclusion = "$($audit.'Inclusion Setting')"
        profiles        = $profiles
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -Path $statePath -Encoding UTF8

    if ($AllowProgram) {
        New-NetFirewallRule -DisplayName 'genetics-netblock: allow Claude Code' -Group 'genetics-netblock' `
            -Direction Outbound -Action Allow -Program $AllowProgram -Profile Any | Out-Null
    }
    auditpol /set /subcategory:$AuditGuid /failure:enable | Out-Null
    Set-NetFirewallProfile -Profile Domain, Private, Public -DefaultOutboundAction Block -LogBlocked True

    $restore = Join-Path $PSScriptRoot 'netblock_restore.ps1'
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
        "-NoProfile -ExecutionPolicy Bypass -File `"$restore`" -StateDir `"$StateDir`" -OnlyId $($state.id) -Reason automatic")
    $trigger = New-ScheduledTaskTrigger -Once -At $restoreAt
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Force | Out-Null

    $allowed = if ($AllowProgram) { $AllowProgram } else { 'nothing' }
    Write-Log "applied $($state.id); allowed: $allowed; automatic restore at $($restoreAt.ToString('o'))"
}
catch { Write-Log "FAILED: $_"; throw }
