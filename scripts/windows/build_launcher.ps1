# Builds GeneticsDashboard.exe at the repository root from GeneticsDashboard.cs, using the
# C# compiler that ships with Windows (.NET Framework 4). The .exe is gitignored (*.exe).
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
