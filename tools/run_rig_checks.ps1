param([string]$GodotPath = 'godot')
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot 'downloads'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$outLog = Join-Path $logDirectory 'rig-check.log'
$errLog = Join-Path $logDirectory 'rig-check.err.log'

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
if ($consoleGodot) {
    Write-Output "Using console Godot binary: $consoleGodot"
    $GodotPath = $consoleGodot
}

function Quote-Arg([string]$Value) {
    if ($Value -match '\s') { return '"' + $Value + '"' }
    return $Value
}

function Invoke-Godot([string[]]$Arguments, [string]$OutFile, [string]$ErrFile) {
    $quoted = @($Arguments | ForEach-Object { Quote-Arg $_ })
    $proc = Start-Process -FilePath $GodotPath -ArgumentList $quoted -NoNewWindow -Wait -PassThru -RedirectStandardOutput $OutFile -RedirectStandardError $ErrFile
    return $proc.ExitCode
}

# The rig suite asserts the character/broom mechanics headlessly: body scale and
# sockets, broom axes and seat alignment, mount/dismount under turning,
# clearance and combat refusals, replicated mount phase agreement, the masked
# upper-body cast layer, footstep contact events and the wand-release event.
$code = Invoke-Godot @('--headless', '--path', $projectPath, 'res://scenes/test/rig_regression.tscn', '--fixed-fps', '60', '--quit-after', '14000') $outLog $errLog
Get-Content $outLog, $errLog
if ($code -ne 0 -or (Select-String -Path $outLog, $errLog -Pattern 'SCRIPT ERROR|FAIL:' -Quiet) -or -not (Select-String -Path $outLog -Pattern 'RIG RESULT: [1-9]\d* checks, 0 failures' -Quiet)) {
    throw 'Rig regression failed; inspect tools/downloads/rig-check.log.'
}
Write-Output 'Rig regression passed: character, broom and mount.'
