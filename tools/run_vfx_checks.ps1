param([string]$GodotPath = 'godot')
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $PSScriptRoot 'downloads'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$outLog = Join-Path $logDirectory 'vfx-check.log'
$errLog = Join-Path $logDirectory 'vfx-check.err.log'
$importLog = Join-Path $logDirectory 'vfx-import.log'
$importErr = Join-Path $logDirectory 'vfx-import.err.log'

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
# The VFX suite asserts the VFX/audio rebuild the same way the art suite asserts the art
# pass. The file-level facts are checked here; everything that needs a live
# scene (effect scenes present and referenced, atlas metadata matching the
# images, cancellation on death/interruption/transfer, rejected predicted
# feedback, telegraph-driven boss warnings, quality variants under the reduced
# preset, no missing resources at runtime) is asserted inside the Godot scene.
$clientRoot = Split-Path -Parent $PSScriptRoot

# every atlas documented in the generated metadata must exist next to it
$metadataPath = Join-Path $clientRoot 'assets\vfx\metadata.json'
if (-not (Test-Path $metadataPath)) { throw 'assets/vfx/metadata.json is missing (run tools/blender/spell_vfx.py)' }
$metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json
$missingAssets = @()
foreach ($asset in $metadata.assets) {
    if ($asset.path) {
        $full = Join-Path $clientRoot ('assets\vfx\' + $asset.path)
        if (-not (Test-Path $full)) { $missingAssets += $asset.path }
    }
}
if ($missingAssets.Count -gt 0) { throw ("missing VFX assets: " + ($missingAssets -join ', ')) }
Write-Output ("VFX inventory: {0} assets present" -f $metadata.assets.Count)

$meshMetadataPath = Join-Path $clientRoot 'assets\vfx\meshes\meshes_metadata.json'
if (-not (Test-Path $meshMetadataPath)) { throw 'assets/vfx/meshes/meshes_metadata.json is missing' }
$meshMetadata = Get-Content $meshMetadataPath -Raw | ConvertFrom-Json
foreach ($mesh in $meshMetadata.meshes) {
    $full = Join-Path $clientRoot ('assets\vfx\' + $mesh.file)
    if (-not (Test-Path $full)) { throw ("missing VFX mesh: " + $mesh.file) }
}
Write-Output ("VFX meshes: {0} entries present" -f $meshMetadata.meshes.Count)

$soundManifestPath = Join-Path $clientRoot 'assets\audio\sound_library.json'
if (-not (Test-Path $soundManifestPath)) { throw 'assets/audio/sound_library.json is missing (run tools/audio/synth_spell_sfx.py)' }
$sounds = Get-Content $soundManifestPath -Raw | ConvertFrom-Json
$missingSounds = @()
foreach ($property in $sounds.sounds.PSObject.Properties) {
    $full = Join-Path $clientRoot ($property.Value.path -replace '/', '\')
    if (-not (Test-Path $full)) { $missingSounds += $property.Value.path }
}
if ($missingSounds.Count -gt 0) { throw ("missing sounds: " + ($missingSounds -join ', ')) }
Write-Output ("Sound library: {0} sounds present" -f $sounds.sounds.PSObject.Properties.Count)

# the import settings the manifest calls for (loop flag, compression)
& python (Join-Path $clientRoot 'tools\audio\tune_imports.py') --client $clientRoot --check
if ($LASTEXITCODE -ne 0) { throw 'audio import settings drifted from the manifest (run tools/audio/tune_imports.py)' }

# provenance must exist for both halves of the phase
foreach ($doc in @('assets\audio\CREDITS-spell-audio.md', 'assets\vfx\PROVENANCE.txt')) {
    if (-not (Test-Path (Join-Path $clientRoot $doc))) { throw "missing provenance file: $doc" }
}
Write-Output 'Provenance: VFX and audio both record a project-original source script'

# every spell has its effect scene file
foreach ($spell in @('basic_cast', 'stupefy', 'incendio', 'bombarda', 'expelliarmus', 'protego', 'ultimate')) {
    $scene = Join-Path $clientRoot ("scenes\spells\fx_{0}.tscn" -f $spell)
    if (-not (Test-Path $scene)) { throw "missing effect scene for $spell" }
}
foreach ($extra in @('fx_boss_warning.tscn', 'fx_broom_trail.tscn')) {
    if (-not (Test-Path (Join-Path $clientRoot ("scenes\spells\" + $extra)))) { throw "missing effect scene: $extra" }
}
Write-Output 'Effect scenes: seven spells, the broom trail and the boss warning all present'

# ---------------------------------------------------------------- scene checks
$importCode = Invoke-Godot @('--headless', '--path', $projectPath, '--editor', '--import', '--quit') $importLog $importErr
if ($importCode -ne 0 -or (Select-String -Path $importLog, $importErr -Pattern 'SCRIPT ERROR|ERROR:' -Quiet)) {
    Get-Content $importLog, $importErr
    throw 'Godot import failed.'
}

$code = Invoke-Godot @('--headless', '--path', $projectPath, 'res://scenes/test/vfx_regression.tscn', '--fixed-fps', '60', '--quit-after', '5400') $outLog $errLog
Get-Content $outLog, $errLog
if ($code -ne 0 -or (Select-String -Path $outLog, $errLog -Pattern 'SCRIPT ERROR' -Quiet) -or -not (Select-String -Path $outLog -Pattern 'VFX RESULT: [1-9]\d* checks, 0 failures' -Quiet)) {
    throw 'VFX checks failed; inspect tools/downloads/vfx-check.log.'
}
Write-Output 'Spell VFX, sound and lifecycle checks passed.'
