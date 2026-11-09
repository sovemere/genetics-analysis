# Builds GeneticsDashboard.exe at the repository root from GeneticsDashboard.cs, using the
# C# compiler that ships with Windows (.NET Framework 4). The .exe is gitignored (*.exe).
# Also makes "GeneticsDashboard (verify first).lnk" beside it, which starts the launcher with
# --verify so a double-click can check every saved run before the dashboard opens
# (gitignored: GeneticsDashboard*.lnk).
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows\build_launcher.ps1

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $here '..\..')).Path
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) {
    throw "The .NET Framework 4 C# compiler was not found at $csc"
}
$out = Join-Path $root 'GeneticsDashboard.exe'
& $csc /nologo /target:exe /optimize+ "/out:$out" (Join-Path $here 'GeneticsDashboard.cs')
if ($LASTEXITCODE -ne 0) {
    throw "csc failed with exit code $LASTEXITCODE"
}
Write-Output "Built $out"

$link = Join-Path $root 'GeneticsDashboard (verify first).lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $out
$shortcut.Arguments = '--verify'
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Check every saved run, then open the genetics dashboard'
$shortcut.Save()
Write-Output "Built $link"
