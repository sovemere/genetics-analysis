# Elevated half of netblock.ps1 restore, and the action of the automatic-restore task.
#
# Undoes netblock_apply.ps1 exactly from <StateDir>\state.json, removes the scheduled task,
# then exports every outbound connection the firewall refused while the block was on to
# <StateDir>\refused-<id>.csv (program, destination, time; it stays on this machine).
# Safe to run twice: with no state file there is nothing to undo. -OnlyId lets the
# automatic restore leave a newer block alone.
param(
    [Parameter(Mandatory)][string]$StateDir,
    [string]$OnlyId = '',
    [ValidateSet('manual', 'automatic')][string]$Reason = 'manual'
)
$ErrorActionPreference = 'Stop'
$AuditGuid = '{0CCE9226-69AE-11D9-BED3-505054503030}'
$TaskName = 'genetics-netblock-autorestore'
$log = Join-Path $StateDir 'netblock.log'
function Write-Log($m) { "$(Get-Date -Format o) restore: $m" | Add-Content -Path $log -Encoding UTF8 }

$statePath = Join-Path $StateDir 'state.json'
if (-not (Test-Path $statePath)) { Write-Log "nothing to restore ($Reason)"; return }
$state = Get-Content $statePath -Raw | ConvertFrom-Json
if ($OnlyId -and $state.id -ne $OnlyId) { Write-Log "state belongs to a newer block; left alone ($Reason)"; return }

try {
    foreach ($p in $state.profiles) {
        Set-NetFirewallProfile -Name $p.Name -DefaultOutboundAction $p.DefaultOutboundAction -LogBlocked $p.LogBlocked
    }
    Get-NetFirewallRule -Group 'genetics-netblock' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    $inc = $state.audit_inclusion
    $s = if ($inc -match 'Success') { 'enable' } else { 'disable' }
    $f = if ($inc -match 'Failure') { 'enable' } else { 'disable' }
    auditpol /set /subcategory:$AuditGuid /success:$s /failure:$f | Out-Null
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Log "restored $($state.id) ($Reason)"

    $since = [datetime]::Parse($state.applied_utc, $null, [Globalization.DateTimeStyles]::RoundtripKind).ToLocalTime()
    $events = @(Get-WinEvent -FilterHashtable @{ LogName = 'Security'; Id = 5157; StartTime = $since } -ErrorAction SilentlyContinue)
    $rows = foreach ($e in $events) {
        $d = @{}; foreach ($n in ([xml]$e.ToXml()).Event.EventData.Data) { $d[$n.Name] = $n.'#text' }
        if ($d.Direction -eq '%%14593') {
            [pscustomobject]@{ Time = $e.TimeCreated.ToString('o'); ProcessId = $d.ProcessID; Application = $d.Application
                DestAddress = $d.DestAddress; DestPort = $d.DestPort; Protocol = $d.Protocol
            }
        }
    }
    $csv = Join-Path $StateDir "refused-$($state.id).csv"
    @($rows) | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
    $state | Add-Member -NotePropertyName restored_utc -NotePropertyValue (Get-Date).ToUniversalTime().ToString('o')
    $state | Add-Member -NotePropertyName restored_by -NotePropertyValue $Reason
    $state | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $StateDir "state-$($state.id).restored.json") -Encoding UTF8
    Remove-Item $statePath
    Write-Log "exported $(@($rows).Count) refused outbound connections to $csv"
}
catch { Write-Log "FAILED: $_"; throw }
