param(
    [string]$GodotPath = 'godot',
    [switch]$Capture
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot 'downloads'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$outLog = Join-Path $logDirectory 'ui-check.log'
$errLog = Join-Path $logDirectory 'ui-check.err.log'
$capLog = Join-Path $logDirectory 'ui-capture.log'
$capErr = Join-Path $logDirectory 'ui-capture.err.log'

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

# ---------------------------------------------------------------- preflight
# The interface pass covers the HUD, interaction and feedback. The file-level facts are
# checked here; everything that needs a live scene (state binding, listener
# lifecycle, tween ordering, refusal reasons, maintenance countdown, input
# focus, settings persistence, onboarding) is asserted inside the Godot scene.
$clientRoot = Split-Path -Parent $PSScriptRoot
$required = @(
    'scripts\ui\game_settings.gd',
    'scripts\ui\ui_focus.gd',
    'scripts\ui\stat_bar.gd',
    'scripts\ui\state_binder.gd',
    'scripts\ui\combat_feedback.gd',
    'scripts\ui\travel_feedback.gd',
    'scripts\ui\maintenance_ui.gd',
    'scripts\ui\onboarding_ui.gd',
    'scripts\ui\settings_ui.gd',
    'scenes\test\ui_regression.tscn',
    'scenes\test\ui_hud_capture.tscn'
)
foreach ($file in $required) {
    if (-not (Test-Path (Join-Path $clientRoot $file))) { throw "missing UI file: $file" }
}
Write-Output ("UI files: {0} present" -f $required.Count)

# Settings must live in user data, never inside the versioned game files.
$settingsSource = Get-Content (Join-Path $clientRoot 'scripts\ui\game_settings.gd') -Raw
if ($settingsSource -notmatch 'user://settings\.cfg') {
    throw 'GameSettings no longer persists to user://settings.cfg'
}
if ($settingsSource -match 'const SETTINGS_PATH := "res://') {
    throw 'GameSettings persists inside res:// (versioned game files)'
}
Write-Output 'Settings persistence: user:// only, no res:// write'

# The rejection vocabulary must come from the shared protocol, not a local copy.
$feedbackSource = Get-Content (Join-Path $clientRoot 'scripts\ui\combat_feedback.gd') -Raw
foreach ($reason in @('REJECT_NO_MANA', 'REJECT_RANGE', 'REJECT_PROTECTED', 'REJECT_NO_TARGET', 'REJECT_MOUNTED', 'REJECT_LINE_OF_SIGHT')) {
    if ($feedbackSource -notmatch "HPProtocol\.$reason") {
        throw "combat feedback does not reference HPProtocol.$reason"
    }
}
Write-Output 'Refusal reasons: taken from HPProtocol.REJECT_*'

# ---------------------------------------------------------------- scene checks
$importCode = Invoke-Godot @('--headless', '--path', $projectPath, '--editor', '--import', '--quit') $outLog $errLog
if ($importCode -ne 0) {
    Get-Content $outLog, $errLog
    throw 'Godot import failed.'
}

$code = Invoke-Godot @('--headless', '--path', $projectPath, 'res://scenes/test/ui_regression.tscn', '--fixed-fps', '60', '--quit-after', '7200') $outLog $errLog
Get-Content $outLog, $errLog
if ($code -ne 0 -or (Select-String -Path $outLog, $errLog -Pattern 'SCRIPT ERROR' -Quiet) -or -not (Select-String -Path $outLog -Pattern 'UI RESULT: [1-9]\d* checks, 0 failures' -Quiet)) {
    throw 'UI checks failed; inspect tools/downloads/ui-check.log.'
}
Write-Output 'UI HUD binding, feedback, focus, settings and onboarding checks passed.'

# ---------------------------------------------------------------- captures
if ($Capture) {
    # Delete last run's shots first: the check below must prove THIS run wrote
    # them, not that an older file was still lying around.
    foreach ($shot in @('ui-hud-combat.png', 'ui-hud-castle.png', 'ui-hud-maintenance.png', 'ui-onboarding.png', 'ui-settings.png')) {
        $stale = Join-Path $logDirectory $shot
        if (Test-Path $stale) { Remove-Item $stale -Force }
    }
    # Windowed: a real renderer is what makes the HUD shots evidence. The
    # quit-after is a safety net - the scene quits itself when it finishes.
    $captureCode = Invoke-Godot @('--path', $projectPath, 'res://scenes/test/ui_hud_capture.tscn', '--quit-after', '7200') $capLog $capErr
    Get-Content $capLog, $capErr
    if ($captureCode -ne 0) { throw 'UI capture run failed.' }
    foreach ($shot in @('ui-hud-combat.png', 'ui-hud-castle.png', 'ui-hud-maintenance.png', 'ui-onboarding.png')) {
        $path = Join-Path $logDirectory $shot
        if (-not (Test-Path $path)) { throw "missing capture: $shot" }
    }
    Write-Output 'UI captures written to tools/downloads (ui-*.png)'
}
