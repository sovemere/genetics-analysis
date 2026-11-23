# One session of M15.1's full run on the real export (docs/handoff.md, the M15.1 run sheet).
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows\m151\run_session.ps1 `
#       -Export <path to the export> -Session <1|2|3>
#
# Windows PowerShell (powershell.exe), not the Store build of pwsh: that one is exempt from
# the network block through its own package rule (see netblock.ps1).
#
# Before starting it refuses unless: the network block is applied and netprobe.py proves
# it; the checkout is clean, with no CRLF working copy; and, for sessions 2 and 3, the
# commit and the environment (installed packages, R and HIBAG, Java, the GENETICS_*
# overrides) are what session 1 recorded, since a change stops the saved parts matching or
# mixes tool builds between them. It sets JAVA_HOME to the pinned Java 17.
#
# The run is `genetics run --input <export> --hla-model-opt-in`, with --restart in session 1
# only. Session 1 stops itself at the line printed just after the imputation part is saved;
# a later session stops itself at once if the run is not resuming, since imputation would
# start again from nothing. -StopAfterLine <regex> and -StopAfterHours <h> stop a session
# elsewhere; parts are written whole and renamed into place, so a stop loses only the part
# in progress. -RunToEnd lets session 1 run through.
#
# Writes to -RecordDir (default %LOCALAPPDATA%\genetics-analysis\m151, outside the checkout):
# the run's stdout and stderr, kept whole and never read by an agent, and
# session-<n>.summary.json, which is what the M15.1 record is written from: wall-clock, how
# the session ended, whether it resumed, peak memory of the whole process tree and of each
# program, minimum free memory, whether the block held throughout, and the progress lines
# with each digit replaced by '#', each timed from the session start.
param(
    [Parameter(Mandatory)][string]$Export,
    [Parameter(Mandatory)][ValidateRange(1, 3)][int]$Session,
    [string]$StopAfterLine = '',
    [double]$StopAfterHours = 0,
    [switch]$RunToEnd,
    [string]$RecordDir = (Join-Path $env:LOCALAPPDATA 'genetics-analysis\m151'),
    [string[]]$ExtraArgs = @(),
    # Testing this script only: no block is checked, and the summary says so.
    [switch]$WithoutBlock
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $here '..\..\..')).Path
$genetics = Join-Path $root '.venv\Scripts\genetics.exe'
$python = Join-Path $root '.venv\Scripts\python.exe'
$jre = Join-Path $env:LOCALAPPDATA 'genetics-analysis\tools\java17\jdk-17.0.20.1+1-jre'
$imputationSaved = 'Reading imputed doses once'
$notResuming = 'Saving this run.s parts as they finish'
$resuming = 'Resuming an interrupted run of this export'

function Invoke-Native([scriptblock]$block) {
    # Native stderr must not become a terminating error under Windows PowerShell.
    $saved = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $block 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $saved }
}

function Get-Fingerprint {
    $rscript = if ($env:GENETICS_RSCRIPT) { $env:GENETICS_RSCRIPT } else { (Get-Command Rscript).Source }
    $parts = @(
        (Invoke-Native { uv pip freeze --python $python }) -join "`n"
        (Invoke-Native { & $rscript -e "cat(R.version.string, as.character(packageVersion('HIBAG')))" }) -join ' '
        (Invoke-Native { & (Join-Path $jre 'bin\java.exe') -version }) -join ' '
        "JAVA_HOME=$env:JAVA_HOME GENETICS_BEAGLE_JAR=$env:GENETICS_BEAGLE_JAR GENETICS_RSCRIPT=$env:GENETICS_RSCRIPT GENETICS_DATA_DIR=$env:GENETICS_DATA_DIR"
    )
    $bytes = [Text.Encoding]::UTF8.GetBytes(($parts -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
}

function Get-Tree([int]$rootId, $all) {
    $children = @{}
    foreach ($p in $all) {
        $parent = [int]$p.ParentProcessId
        if (-not $children.ContainsKey($parent)) { $children[$parent] = New-Object Collections.ArrayList }
        [void]$children[$parent].Add($p)
    }
    $tree = New-Object Collections.ArrayList
    $queue = New-Object Collections.Queue
    $self = $all | Where-Object { $_.ProcessId -eq $rootId }
    if ($self) { [void]$tree.Add($self); $queue.Enqueue($rootId) }
    while ($queue.Count) {
        $id = $queue.Dequeue()
        if ($children.ContainsKey($id)) {
            foreach ($c in $children[$id]) { [void]$tree.Add($c); $queue.Enqueue([int]$c.ProcessId) }
        }
    }
    return , $tree
}

function Stop-Tree([int]$rootId) {
    $tree = Get-Tree $rootId @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId)
    for ($i = $tree.Count - 1; $i -ge 0; $i--) {
        Stop-Process -Id $tree[$i].ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# --- before starting -------------------------------------------------------------------
if (-not (Test-Path $Export)) { throw "export not found: $Export" }
if (-not (Test-Path $jre)) { throw "pinned Java 17 not found at $jre; run: genetics tools install" }
New-Item -ItemType Directory -Force $RecordDir | Out-Null
if (-not $WithoutBlock) {
    if (-not (Test-Path (Join-Path $env:LOCALAPPDATA 'genetics-analysis\netblock\state.json'))) {
        throw 'the network block is not applied; run: netblock.ps1 apply'
    }
    & (Join-Path $here 'netblock.ps1') check
}
$env:JAVA_HOME = $jre
$env:PATH = "$jre\bin;$env:PATH"
$dirty = Invoke-Native { git -C $root status --porcelain }
if ($dirty) { throw "the checkout is not clean:`n$($dirty -join "`n")" }
$crlf = @(Invoke-Native { git -C $root ls-files --eol } | Where-Object { $_ -match 'w/(crlf|mixed)' })
if ($crlf) { throw "$($crlf.Count) tracked files have CRLF working copies; rewrite them as LF before session 1 (run sheet item 9)" }
$head = (Invoke-Native { git -C $root rev-parse HEAD }) -join ''
$fingerprint = Get-Fingerprint

$basePath = Join-Path $RecordDir 'base.json'
if ($Session -eq 1) {
    if (Test-Path $basePath) { Move-Item $basePath (Join-Path $RecordDir "base-$(Get-Date -Format yyyyMMdd-HHmmss).json") }
    [ordered]@{ commit = $head; environment_sha256 = $fingerprint; recorded = (Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -Path $basePath -Encoding UTF8
}
else {
    if (-not (Test-Path $basePath)) { throw 'no session 1 record; a later session resumes the parts session 1 saved' }
    $base = Get-Content $basePath -Raw | ConvertFrom-Json
    if ($base.commit -ne $head) { throw "the commit changed since session 1 ($($base.commit) -> $head); the saved parts would not be reused" }
    if ($base.environment_sha256 -ne $fingerprint) { throw 'the environment changed since session 1 (packages, R/HIBAG, Java or a GENETICS_* override)' }
}
if ($Session -eq 1 -and -not $StopAfterLine -and -not $RunToEnd) { $StopAfterLine = $imputationSaved }

# --- the session -----------------------------------------------------------------------
$stderrPath = Join-Path $RecordDir "session-$Session.stderr.log"
$stdoutPath = Join-Path $RecordDir "session-$Session.stdout.log"
$summaryPath = Join-Path $RecordDir "session-$Session.summary.json"
$stamp = Get-Date -Format yyyyMMdd-HHmmss
foreach ($f in @($stderrPath, $stdoutPath, $summaryPath)) { if (Test-Path $f) { Move-Item $f "$f.$stamp" } }

$runArgs = @('run', '--input', "`"$Export`"", '--hla-model-opt-in')
if ($Session -eq 1) { $runArgs += '--restart' }
$runArgs += $ExtraArgs
$start = Get-Date
$proc = Start-Process -FilePath $genetics -ArgumentList $runArgs -WorkingDirectory $root -NoNewWindow -PassThru `
    -RedirectStandardError $stderrPath -RedirectStandardOutput $stdoutPath
$null = $proc.Handle  # keeps the exit code readable after the process ends

$events = New-Object Collections.ArrayList
$script:position = 0; $script:pending = ''
$stoppedBy = $null; $resumed = $false; $partsLine = $null
$peakTotal = 0; $peakAt = 0; $peakByProgram = @{}; $atPeak = @{}; $minFree = [double]::MaxValue
$blockLiftedAt = $null; $lastBlockCheck = Get-Date; $lastSummary = Get-Date

function Read-NewLines {
    if (-not (Test-Path $stderrPath)) { return @() }
    $fs = [IO.File]::Open($stderrPath, 'Open', 'Read', 'ReadWrite')
    try {
        $null = $fs.Seek($script:position, 'Begin')
        $reader = New-Object IO.StreamReader($fs)
        $text = $reader.ReadToEnd()
        $script:position = $fs.Position
    }
    finally { $fs.Dispose() }
    $pieces = ($script:pending + $text) -split "[`r`n]+"
    $script:pending = $pieces[-1]
    return @($pieces | Select-Object -SkipLast 1 | Where-Object { $_.Trim() })
}

function Write-Summary([bool]$final) {
    $now = Get-Date
    [ordered]@{
        session                 = $Session
        commit                  = $head
        options                 = ($runArgs | Where-Object { $_ -like '--*' })
        started                 = $start.ToString('o')
        ended                   = if ($final) { $now.ToString('o') } else { $null }
        wall_clock_min          = [math]::Round(($now - $start).TotalMinutes, 1)
        finished                = $final
        exit_code               = if ($final) { $proc.ExitCode } else { $null }
        stopped_by              = $stoppedBy
        resumed                 = $resumed
        parts_line              = $partsLine
        block_checked_before    = -not $WithoutBlock
        block_lifted_at         = $blockLiftedAt
        peak_tree_working_set_gb = [math]::Round($peakTotal / 1GB, 2)
        peak_tree_at_min        = $peakAt
        at_peak_by_program_gb   = $atPeak
        peak_by_program_gb      = $peakByProgram
        min_free_memory_gb      = if ($minFree -lt [double]::MaxValue) { [math]::Round($minFree / 1GB, 2) } else { $null }
        events                  = $events
    } | ConvertTo-Json -Depth 4 | Set-Content -Path $summaryPath -Encoding UTF8
}

while (-not $proc.HasExited) {
    Start-Sleep -Seconds 5
    $elapsed = [math]::Round(((Get-Date) - $start).TotalMinutes, 2)
    foreach ($line in (Read-NewLines)) {
        $hidden = $line -replace '\d', '#'
        if ($hidden.Length -gt 200) { $hidden = $hidden.Substring(0, 200) + '...' }
        [void]$events.Add([ordered]@{ t_min = $elapsed; line = $hidden })
        if ($line -match $resuming) { $resumed = $true; $partsLine = $hidden }
        if ($line -match $notResuming) {
            $partsLine = $hidden
            if ($Session -gt 1) { $stoppedBy = 'not resuming: stopped before imputation could start again' }
        }
        if (-not $stoppedBy -and $StopAfterLine -and $line -match $StopAfterLine) { $stoppedBy = "line: $StopAfterLine" }
    }
    if (-not $stoppedBy -and $StopAfterHours -gt 0 -and $elapsed -ge $StopAfterHours * 60) { $stoppedBy = "time: $StopAfterHours h" }

    $all = @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, Name, WorkingSetSize, PeakWorkingSetSize)
    $tree = Get-Tree $proc.Id $all
    $total = 0; $now = @{}
    foreach ($p in $tree) {
        $total += [double]$p.WorkingSetSize
        $name = $p.Name.ToLower()
        $now[$name] = [math]::Round(([double]$p.WorkingSetSize + ($now[$name] * 1GB)) / 1GB, 2)
        $peak = [math]::Round([double]$p.PeakWorkingSetSize * 1KB / 1GB, 2)  # this one is in KB
        if (-not $peakByProgram.ContainsKey($name) -or $peakByProgram[$name] -lt $peak) { $peakByProgram[$name] = $peak }
    }
    if ($total -gt $peakTotal) { $peakTotal = $total; $peakAt = $elapsed; $atPeak = $now }
    $free = [double](Get-CimInstance Win32_OperatingSystem -Property FreePhysicalMemory).FreePhysicalMemory * 1KB
    if ($free -lt $minFree) { $minFree = $free }

    if (-not $WithoutBlock -and ((Get-Date) - $lastBlockCheck).TotalSeconds -ge 60) {
        $lastBlockCheck = Get-Date
        $open = @(Get-NetFirewallProfile -PolicyStore PersistentStore | Where-Object { "$($_.DefaultOutboundAction)" -ne 'Block' })
        if ($open -and -not $blockLiftedAt) { $blockLiftedAt = $elapsed }
    }
    if ($stoppedBy) { Stop-Tree $proc.Id; break }
    if (((Get-Date) - $lastSummary).TotalSeconds -ge 60) { $lastSummary = Get-Date; Write-Summary $false }
}
$proc.WaitForExit()
foreach ($line in @(Read-NewLines) + @($script:pending | Where-Object { $_.Trim() })) {
    [void]$events.Add([ordered]@{ t_min = [math]::Round(((Get-Date) - $start).TotalMinutes, 2); line = ($line -replace '\d', '#') })
}
Write-Summary $true
$how = if ($stoppedBy) { "stopped ($stoppedBy)" } else { "ended with exit code $($proc.ExitCode)" }
"session $Session $how after $([math]::Round(((Get-Date) - $start).TotalMinutes, 1)) min; summary: $summaryPath"
if ($blockLiftedAt) { "WARNING: the network block was lifted at minute $blockLiftedAt of this session" }
