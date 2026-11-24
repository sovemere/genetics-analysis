# M15.1's network block, option A (docs/handoff.md, the M15.1 run sheet): Windows Firewall
# refuses every outbound connection on this machine except the coding agent's own, so the
# run and every program it starts (Python, Java and Beagle, PLINK, R and HIBAG) cannot reach
# the network, and each refusal is logged with the program that tried. Tested 2026-11-23
# with Claude Code; the agent is Google Antigravity since 2026-11-25.
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows\m151\netblock.ps1 <command>
#
#   apply    UAC prompt; block, audit refusals, schedule an automatic restore
#            (-AutoRestoreHours, default 8: longer than any session, so it never lifts
#            mid-run). Exempts the agent this is run from, found among its parent
#            processes: Antigravity (Antigravity.exe and its language_server.exe, which
#            makes the agent's model calls) or Claude Code (claude.exe). Or -AllowProgram
#            <path>[;<path>...], or -AllowProgram none. A rule exempts an executable path,
#            not a process tree, so the run's programs started by an exempt agent are still
#            refused.
#   check    prove the block from the run's interpreters, contacting no host (netprobe.py)
#   status   whether a block is applied, and when it lifts by itself
#   restore  UAC prompt; undo apply exactly and export what was refused
#   report   the last restore's refusals, split into the run's programs and everything else
#
# Known and accepted: DNS lookups still leave through Windows' DNS client service, which a
# built-in rule allows and the agent needs; a lookup can carry a host name, never data,
# and the connection after it is refused and logged. The Store build of PowerShell is
# exempt through its own package rule; the pipeline never starts PowerShell, and programs
# started from it were refused in the test.
param(
    [Parameter(Mandatory, Position = 0)][ValidateSet('apply', 'check', 'status', 'restore', 'report')][string]$Command,
    [string]$AllowProgram = '',
    [double]$AutoRestoreHours = 8
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $here '..\..\..')).Path
$stateDir = Join-Path $env:LOCALAPPDATA 'genetics-analysis\netblock'
New-Item -ItemType Directory -Force $stateDir | Out-Null
$statePath = Join-Path $stateDir 'state.json'
$log = Join-Path $stateDir 'netblock.log'
$runPrograms = '\\(python|pythonw|genetics|uv|java|javaw|plink|plink2|rscript|rterm|r)\.exe$'

# The agent's executables among this script's parent processes, nearest first: claude.exe,
# or Antigravity's language_server.exe and Antigravity.exe. Both of Antigravity's hold their
# own connections, so both are exempted. Nothing found returns an empty list.
function Find-AgentExes {
    $found = [System.Collections.Generic.List[string]]::new()
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$PID"
    while ($p) {
        $path = $p.ExecutablePath
        $isAgent = ($p.Name -ieq 'claude.exe') -or ($p.Name -ieq 'Antigravity.exe') -or
            ($p.Name -ieq 'language_server.exe' -and $path -match '\\antigravity\\')
        if ($isAgent -and $path -and -not $found.Contains($path)) { $found.Add($path) }
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)"
    }
    return , $found.ToArray()
}

function Invoke-Elevated([string]$script, [string[]]$scriptArgs, [string]$verb) {
    $before = if (Test-Path $log) { @(Get-Content $log).Count } else { 0 }
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$script`"") + $scriptArgs
    # No -Wait: it would wait on every process the elevated script leaves behind.
    Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList $argList | Out-Null
    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (-not (Test-Path $log)) { continue }
        $new = @(Get-Content $log | Select-Object -Skip $before | Where-Object { $_ -match " ${verb}: " })
        if ($new | Where-Object { $_ -match 'FAILED' }) { $new; throw "$verb failed; see $log" }
        if ($verb -eq 'apply' -and $new) { return $new }
        if ($verb -eq 'restore' -and ($new | Where-Object { $_ -match 'exported|nothing to restore' })) { return $new }
    }
    throw "no result from the elevated $verb after 5 minutes; was the UAC prompt approved?"
}

function Get-Status {
    $profiles = @(Get-NetFirewallProfile -PolicyStore PersistentStore)
    $blocked = @($profiles | Where-Object { "$($_.DefaultOutboundAction)" -eq 'Block' }).Count -eq $profiles.Count
    $state = if (Test-Path $statePath) { Get-Content $statePath -Raw | ConvertFrom-Json } else { $null }
    [pscustomobject]@{
        applied         = [bool]$state
        all_profiles_block_outbound = $blocked
        allowed         = if ($state) { $state.allow_program } else { $null }
        applied_utc     = if ($state) { $state.applied_utc } else { $null }
        auto_restore_at = if ($state) { $state.auto_restore_at } else { $null }
    }
}

switch ($Command) {
    'apply' {
        if (Test-Path $statePath) { throw "a block is already applied; see: netblock.ps1 status" }
        $allow = if ($AllowProgram -eq 'none') { '' } elseif ($AllowProgram) { $AllowProgram } else {
            $agent = Find-AgentExes
            if (-not $agent) { throw 'not run from Antigravity or Claude Code: pass -AllowProgram <path>[;<path>...], or -AllowProgram none' }
            $agent -join ';'
        }
        Invoke-Elevated (Join-Path $here 'netblock_apply.ps1') @(
            '-StateDir', "`"$stateDir`"", '-AllowProgram', "`"$allow`"", '-AutoRestoreHours', "$AutoRestoreHours") 'apply'
    }
    'restore' {
        Invoke-Elevated (Join-Path $here 'netblock_restore.ps1') @('-StateDir', "`"$stateDir`"") 'restore'
    }
    'status' { Get-Status | Format-List }
    'check' {
        $py = Join-Path $root '.venv\Scripts\python.exe'
        & $py -I (Join-Path $here 'netprobe.py')
        if ($LASTEXITCODE -ne 0) { throw 'the block is NOT in force: at least one probe was not refused' }
        'block in force: every probe refused'
    }
    'report' {
        $last = Get-ChildItem $stateDir -Filter 'state-*.restored.json' | Sort-Object LastWriteTime | Select-Object -Last 1
        if (-not $last) { throw 'no restored block to report on' }
        $state = Get-Content $last.FullName -Raw | ConvertFrom-Json
        $rows = @(Import-Csv (Join-Path $stateDir "refused-$($state.id).csv"))
        $run = @($rows | Where-Object { $_.Application -match $runPrograms })
        $probes = @($run | Where-Object { $_.DestAddress -eq '192.0.2.1' })
        $attempts = @($run | Where-Object { $_.DestAddress -ne '192.0.2.1' })
        "block $($state.id): applied $($state.applied_utc), restored $($state.restored_utc) ($($state.restored_by))"
        "refused in all: $($rows.Count); by the run's programs: $($run.Count), of which check probes: $($probes.Count)"
        "connection attempts by the run's programs other than probes: $($attempts.Count)"
        if ($attempts) { $attempts | Group-Object Application | Select-Object Count, Name | Format-Table -AutoSize }
        # The run's interpreter is the same python.exe an agent's own commands use, so match
        # refusals to a session by the process ids run_session.ps1 recorded.
        $summaries = @(Get-ChildItem (Join-Path $env:LOCALAPPDATA 'genetics-analysis\m151') -Filter 'session-*.summary.json' -ErrorAction SilentlyContinue)
        foreach ($f in $summaries) {
            $pids = @((Get-Content $f.FullName -Raw | ConvertFrom-Json).tree_pids | ForEach-Object { "$_" })
            $mine = @($attempts | Where-Object { $pids -contains $_.ProcessId })
            "$($f.Name): refusals of the run's own processes (other than probes): $($mine.Count)"
        }
    }
}
