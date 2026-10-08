param([string]$GodotPath = 'godot')
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot 'downloads'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$importLog = Join-Path $logDirectory 'check-import.log'
$importErr = Join-Path $logDirectory 'check-import.err.log'
$testLog = Join-Path $logDirectory 'check-regression.log'
$testErr = Join-Path $logDirectory 'check-regression.err.log'

# Windows PowerShell does not wait for GUI-subsystem executables, so the
# godot.exe shim (PE subsystem 2) leaves $LASTEXITCODE empty and this script
# would abort after zero work. Prefer the *_console.exe companion build when
# one exists next to the resolved binary.
function Resolve-ConsoleGodot([string]$Path) {
    try {
        $cmd = Get-Command $Path -ErrorAction Stop
    } catch {
        return $null
    }
    if ($cmd.CommandType -ne 'Application') {
        return $null
    }
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
    if ($target -match '_console\.exe$') {
        return $target
    }
    $console = $target -replace '\.exe$', '_console.exe'
    if ($console -ne $target -and (Test-Path $console)) {
        return $console
    }
    return $null
}

$consoleGodot = Resolve-ConsoleGodot $GodotPath
if ($consoleGodot) {
    Write-Output "Using console Godot binary: $consoleGodot"
    $GodotPath = $consoleGodot
}

# Start-Process keeps native stderr out of PowerShell's error stream (PS 5.1
# turns native stderr into terminating errors under $ErrorActionPreference =
# 'Stop') and returns a real exit code; run_game_checks must not abort just
# because the regression printed a FAIL line. -ArgumentList joins elements
# unquoted, so quote any element containing spaces (e.g. a workspace path).
function Quote-Arg([string]$Value) {
    if ($Value -match '\s') {
        return '"' + $Value + '"'
    }
    return $Value
}

function Invoke-Godot([string[]]$Arguments, [string]$OutFile, [string]$ErrFile) {
    $quoted = @($Arguments | ForEach-Object { Quote-Arg $_ })
    $proc = Start-Process -FilePath $GodotPath -ArgumentList $quoted -NoNewWindow -Wait -PassThru -RedirectStandardOutput $OutFile -RedirectStandardError $ErrFile
    return $proc.ExitCode
}

$importCode = Invoke-Godot @('--headless', '--path', $projectPath, '--editor', '--import', '--quit') $importLog $importErr
if ($importCode -ne 0 -or (Select-String -Path $importLog, $importErr -Pattern 'SCRIPT ERROR|ERROR:' -Quiet)) {
    Get-Content $importLog, $importErr
    throw 'Godot import failed.'
}

$testCode = Invoke-Godot @('--headless', '--path', $projectPath, 'res://scenes/test/test_scenario.tscn', '--fixed-fps', '60', '--quit-after', '3600') $testLog $testErr
Get-Content $testLog, $testErr
if ($testCode -ne 0 -or (Select-String -Path $testLog, $testErr -Pattern 'SCRIPT ERROR|ERROR:|leaked at exit|Leaked instance' -Quiet) -or -not (Select-String -Path $testLog -Pattern 'REGRESSION RESULT: [1-9]\d* checks, 0 failures' -Quiet)) {
    throw 'Gameplay regression or shutdown check failed; inspect tools/downloads/check-regression.log.'
}
Write-Output 'Godot import, gameplay regression, and shutdown checks passed.'

# The equipment suite covers ownership, authority gates, GUI gestures and save retries.
$equipmentLog = Join-Path $logDirectory 'check-equipment.log'
$equipmentErr = Join-Path $logDirectory 'check-equipment.err.log'
$equipmentCode = Invoke-Godot @('--headless', '--path', $projectPath, 'res://scenes/test/equipment_regression.tscn', '--fixed-fps', '60', '--quit-after', '3600') $equipmentLog $equipmentErr
Get-Content $equipmentLog, $equipmentErr
if ($equipmentCode -ne 0 -or (Select-String -Path $equipmentLog, $equipmentErr -Pattern 'SCRIPT ERROR|ERROR:|leaked at exit|Leaked instance' -Quiet) -or -not (Select-String -Path $equipmentLog -Pattern 'EQUIPMENT RESULT: [1-9]\d* checks, 0 failures' -Quiet)) {
    throw 'Equipment regression failed; inspect tools/downloads/check-equipment.log.'
}
Write-Output 'Equipment ownership, interaction and persistence checks passed.'
