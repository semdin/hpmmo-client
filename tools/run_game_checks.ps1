param([string]$GodotPath = 'godot')
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot 'downloads'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$importLog = Join-Path $logDirectory 'check-import.log'
$testLog = Join-Path $logDirectory 'check-regression.log'

& $GodotPath --headless --path $projectPath --editor --import --quit *> $importLog
if ($LASTEXITCODE -ne 0 -or (Select-String -Path $importLog -Pattern 'SCRIPT ERROR|ERROR:' -Quiet)) {
    Get-Content $importLog
    throw 'Godot import failed.'
}
& $GodotPath --headless --path $projectPath res://scenes/test/test_scenario.tscn --fixed-fps 60 --quit-after 3600 *> $testLog
$testExitCode = $LASTEXITCODE
Get-Content $testLog
if ($testExitCode -ne 0 -or (Select-String -Path $testLog -Pattern 'SCRIPT ERROR|ERROR:|leaked at exit|Leaked instance' -Quiet) -or -not (Select-String -Path $testLog -Pattern 'REGRESSION RESULT: \d+ checks, 0 failures' -Quiet)) {
    throw 'Gameplay regression or shutdown check failed; inspect tools/downloads/check-regression.log.'
}
Write-Output 'Godot import, gameplay regression, and shutdown checks passed.'
