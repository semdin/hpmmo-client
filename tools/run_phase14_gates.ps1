param(
    [string]$GodotPath = 'godot',
    [string[]]$Only = @()
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot 'downloads'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

# Same console-binary resolution as run_game_checks.ps1: the GUI-subsystem
# godot.exe leaves $LASTEXITCODE empty under Windows PowerShell.
function Resolve-ConsoleGodot([string]$Path) {
    try {
        $cmd = Get-Command $Path -ErrorAction Stop
    } catch {
        return $null
    }
    if ($cmd.CommandType -ne 'Application') { return $null }
    $target = $cmd.Source
    try {
        $item = Get-Item -ErrorAction Stop $target
        if ($item.Target) {
            $resolved = $item.Target
            if ($resolved -is [array]) { $resolved = $resolved[0] }
            $target = $resolved
        }
    } catch {
    }
    if ($target -match '_console\.exe$') { return $target }
    $console = $target -replace '\.exe$', '_console.exe'
    if ($console -ne $target -and (Test-Path $console)) { return $console }
    return $null
}

$consoleGodot = Resolve-ConsoleGodot $GodotPath
if ($consoleGodot) { $GodotPath = $consoleGodot }

function Quote-Arg([string]$Value) {
    if ($Value -match '\s') { return '"' + $Value + '"' }
    return $Value
}

function Invoke-Proc([string]$File, [string[]]$Arguments, [string]$OutFile, [string]$ErrFile) {
    $quoted = @($Arguments | ForEach-Object { Quote-Arg $_ })
    $proc = Start-Process -FilePath $File -ArgumentList $quoted -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $OutFile -RedirectStandardError $ErrFile
    return $proc.ExitCode
}

$summary = @()
$GATES = [ordered]@{
    'game'    = @('run_game_checks.ps1',    'REGRESSION RESULT: \d+ checks, 0 failures')
    'phase9'  = @('run_phase9_checks.ps1',  'PHASE9 RESULT: \d+ checks, 0 failures')
    'phase10' = @('run_phase10_checks.ps1', 'PHASE10 RESULT: \d+ checks, 0 failures')
    'phase12' = @('run_phase12_checks.ps1', 'PHASE12 RESULT: \d+ checks, 0 failures')
    'phase13' = @('run_phase13_checks.ps1', 'PHASE13 RESULT: \d+ checks, 0 failures')
}
foreach ($name in $GATES.Keys) {
    if ($Only.Count -gt 0 -and $Only -notcontains $name) { continue }
    $script = $GATES[$name][0]
    $pattern = $GATES[$name][1]
    $out = Join-Path $logDirectory ("phase14-gate-{0}.log" -f $name)
    $err = Join-Path $logDirectory ("phase14-gate-{0}.err.log" -f $name)
    Write-Host ("=== gate {0}: {1} ===" -f $name, $script)
    $code = Invoke-Proc 'powershell' @('-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot $script), '-GodotPath', $GodotPath) $out $err
    $line = (Select-String -Path $out -Pattern $pattern | Select-Object -Last 1).Line
    if (-not $line) { $line = (Select-String -Path $out -Pattern 'RESULT:.*failures' | Select-Object -Last 1).Line }
    if (-not $line) { $line = 'NO RESULT LINE (exit ' + $code + ')' }
    $summary += ("{0}: exit={1} :: {2}" -f $name, $code, $line.Trim())
}

# castle_walkthrough.tscn is named as a gate in the Phase 14 task list and has no
# ps1 wrapper; run it the way its own header documents.
if ($Only.Count -eq 0 -or $Only -contains 'castle') {
    $out = Join-Path $logDirectory 'phase14-gate-castle.log'
    $err = Join-Path $logDirectory 'phase14-gate-castle.err.log'
    Write-Host '=== gate castle: castle_walkthrough.tscn ==='
    $code = Invoke-Proc $GodotPath @('--headless', '--path', $projectPath,
        'res://scenes/test/castle_walkthrough.tscn', '--fixed-fps', '60', '--quit-after', '9000') $out $err
    $line = (Select-String -Path $out -Pattern 'WALKTHROUGH|RESULT:.*failures' | Select-Object -Last 1).Line
    if (-not $line) { $line = 'NO RESULT LINE (exit ' + $code + ')' }
    $summary += ("castle: exit={0} :: {1}" -f $code, $line.Trim())
}

Write-Host ''
Write-Host '=== PHASE14 GATE SUMMARY ==='
$sumPath = Join-Path $logDirectory 'phase14-gates-summary.log'
if (Test-Path $sumPath) { Remove-Item $sumPath -Force }
foreach ($line in $summary) { Write-Host $line; Add-Content -Path $sumPath -Value $line }
