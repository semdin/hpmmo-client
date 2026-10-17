#!/usr/bin/env powershell
<#
HPMMO workspace helper.
Canonical source: client/tools/workspace/dev.ps1 - this root copy is generated.

Commands:
  .\dev.ps1 ready             THE pre-commit cycle, in order: sync the simulation package
                               (server -> client), regenerate the world file list, export
                               server\world (client -> server), import both projects and run
                               `test`. Refuses to overwrite hand edits made in a generated copy.
                               Ends with what each repo has to commit.
  .\dev.ps1 status             pinned revisions, contract-hash check, repo states
  .\dev.ps1 test               client import check, world import + boot, multiplayer proof (the only kept test)
  .\dev.ps1 build              server deployable package into server\dist (client export = the release pipeline)
  .\dev.ps1 start -Client      launch the game
  .\dev.ps1 start -Server      launch the dedicated server world (headless)
  .\dev.ps1 sync-world         re-export server\world from the client project + refresh workspace.lock.json
  .\dev.ps1 verify-contracts   fail if contract files drift from workspace.lock.json
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'ready', 'test', 'build', 'start', 'sync-world', 'sync-sim', 'verify-contracts')]
    [string]$Command = 'status',
    [switch]$Client,
    [switch]$Server
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$clientRepo = Join-Path $root 'client'
$serverRepo = Join-Path $root 'server'
$lockPath = Join-Path $root 'workspace.lock.json'
$python = 'python'

function Write-Step([string]$Text) {
    Write-Host ''
    Write-Host "[ready] $Text" -ForegroundColor Cyan
}

function Get-Godot {
    if ($env:HPMMO_GODOT) { return $env:HPMMO_GODOT }
    $cmd = Get-Command godot -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return 'godot'
}

function Read-Lock {
    if (Test-Path $lockPath) { return (Get-Content $lockPath -Raw | ConvertFrom-Json) }
    return $null
}

function Test-SimSync {
    $syncTool = Join-Path $clientRepo 'tools\workspace\sync_sim.py'
    if (-not (Test-Path $syncTool)) { return }
    & $python $syncTool --client $clientRepo --server $serverRepo --root $root --check
    if ($LASTEXITCODE -ne 0) { throw 'client simulation package drifted from the server copy (run: dev.ps1 sync-sim)' }
}

function Test-Contracts([switch]$Quiet) {
    $lock = Read-Lock
    if (-not $lock) { if (-not $Quiet) { Write-Host 'no workspace.lock.json' }; return $false }
    $ok = $true
    foreach ($entry in $lock.contracts.PSObject.Properties) {
        $name = $entry.Name
        $want = $entry.Value.hash
        foreach ($repo in @(@('client', $clientRepo), @('server', $serverRepo))) {
            $rel = $entry.Value.($repo[0])
            if (-not $rel) { continue }
            $full = Join-Path $repo[1] $rel
            if (-not (Test-Path $full)) {
                if (-not $Quiet) { Write-Host ("  MISSING  {0}: {1}" -f $repo[0], $rel) }
                $ok = $false
                continue
            }
            $got = (Get-FileHash -Algorithm SHA256 $full).Hash.ToLower()
            if ($got -ne $want) {
                if (-not $Quiet) { Write-Host ("  DRIFT    {0}: {1}" -f $repo[0], $rel) }
                $ok = $false
            }
        }
    }
    if ($ok -and -not $Quiet) { Write-Host '  contracts OK' }
    return $ok
}

## The client must import cleanly (a parse error in any script fails here).
function Invoke-ClientHarness {
    $godot = Get-Godot
    Write-Host '[client] import + script check'
    $errors = Invoke-GodotText @('--headless', '--path', $clientRepo, '--import') |
        Select-String -Pattern 'SCRIPT ERROR|Parse Error'
    if ($errors) { $errors | Select-Object -First 10 | ForEach-Object { "  $_" }; throw 'client import reported script errors' }
}

function Invoke-ServiceBuild {
    $cpp = Join-Path $serverRepo 'services\cpp'
    $buildDir = Join-Path $cpp 'build'
    if (-not (Test-Path (Join-Path $buildDir 'CMakeCache.txt'))) {
        Write-Host '[server] configuring the C++ service (cmake + ninja + clang++)'
        $cmakeArgs = @('-S', $cpp, '-B', $buildDir, '-G', 'Ninja', '-DCMAKE_CXX_COMPILER=clang++', '-DCMAKE_BUILD_TYPE=Release')
        if ($env:HPMMO_PG_ROOT) { $cmakeArgs += "-DPG_ROOT=$env:HPMMO_PG_ROOT" }
        & cmake @cmakeArgs | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'cmake configure failed' }
    }
    & ninja -C $buildDir
    if ($LASTEXITCODE -ne 0) { throw 'service build failed' }
}

function Test-WorldFileList {
    # The declared world file set is generated from the client tree. If it goes
    # stale, the export ships a world missing scripts its scenes preload - the
    # server then fails to spawn a player. Cheaper to fail here.
    & $python (Join-Path $clientRepo 'tools\workspace\gen_world_files.py') --client $clientRepo --check
    if ($LASTEXITCODE -ne 0) { throw 'world file list is stale (run: python client/tools/workspace/gen_world_files.py --client client)' }
}

## Run Godot and hand back its output as plain text lines. Godot prints engine
## warnings (e.g. a GDExtension calling a deprecated API) on stderr, and under
## `$ErrorActionPreference = 'Stop'` PowerShell 5.1 turns every redirected
## stderr line into a terminating error. Failure is still judged by the exit
## code and by the ERROR / SCRIPT lines the callers filter for.
function Invoke-GodotText([string[]]$GodotArgs) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $godot @GodotArgs 2>&1 | ForEach-Object { "$_" }
    } finally {
        $ErrorActionPreference = $previous
    }
}

function Invoke-ServerSmoke {
    $world = Join-Path $serverRepo 'world'
    Test-WorldFileList
    if (Test-Path (Join-Path $world 'project.godot')) {
        $godot = Get-Godot
        # Import before anything boots the world: an asset that is new to the
        # export (e.g. a glb) is not loadable until its import exists.
        Write-Host '[server] world import pass'
        Invoke-GodotText @('--headless', '--path', $world, '--editor', '--import', '--quit') |
            Select-String -Pattern 'SCRIPT ERROR|ERROR:' | Select-Object -First 10
        if ($LASTEXITCODE -ne 0) { throw 'world import failed' }
        Test-SimSync
    }
    $multiplayer = Join-Path $serverRepo 'tests\multiplayer_sim.py'
    if (Test-Path $multiplayer) {
        Write-Host '[server] multiplayer proof (world server + two headless clients)'
        & $python $multiplayer --skip=forged,protection
        if ($LASTEXITCODE -ne 0) { throw 'multiplayer agreement test failed' }
    }
    if (Test-Path (Join-Path $world 'project.godot')) {
        Write-Host '[server] world boot smoke (headless, 300 frames)'
        Invoke-GodotText @('--headless', '--path', $world, 'res://server/world_server.tscn', '--quit-after', '300') |
            Select-String -Pattern 'WorldServer|ERROR|SCRIPT' | Select-Object -First 20
        if ($LASTEXITCODE -ne 0) { throw 'world boot smoke failed' }
    }
}

## What each repo would commit now. New assets come with Godot's .import and
## .uid side files; they belong in the same commit as the asset.
function Show-CommitSummary {
    foreach ($repo in @(@('client', $clientRepo), @('server', $serverRepo))) {
        $lines = @(git -C $repo[1] status --short)
        $branch = git -C $repo[1] branch --show-current
        if ($lines.Count -eq 0) {
            Write-Host ("  {0} ({1}): nothing to commit" -f $repo[0], $branch)
            continue
        }
        Write-Host ("  {0} ({1}): {2} changed path(s)" -f $repo[0], $branch, $lines.Count)
        $lines | ForEach-Object { "    $_" }
    }
}

switch ($Command) {
    'ready' {
        # Keep the root copy current (this file is the canonical one in client).
        $canonical = Join-Path $clientRepo 'tools\workspace\dev.ps1'
        $rootCopy = Join-Path $root 'dev.ps1'
        if ((Test-Path $canonical) -and ((Get-FileHash $canonical).Hash -ne (Get-FileHash $rootCopy).Hash)) {
            Copy-Item $canonical $rootCopy -Force
            Write-Host '[ready] refreshed the root dev.ps1 from client/tools/workspace/dev.ps1'
        }
        Write-Step '1/5 simulation package: server -> client'
        & $python (Join-Path $clientRepo 'tools\workspace\sync_sim.py') --client $clientRepo --server $serverRepo --root $root --guard
        if ($LASTEXITCODE -ne 0) { throw 'sync-sim refused or failed (see above)' }
        Write-Step '2/5 world file list (new client assets/scripts the server needs)'
        & $python (Join-Path $clientRepo 'tools\workspace\gen_world_files.py') --client $clientRepo
        if ($LASTEXITCODE -ne 0) { throw 'world file list generation failed' }
        Write-Step '3/5 world export: client -> server\world'
        & $python (Join-Path $clientRepo 'tools\workspace\export_world.py') --client $clientRepo --server $serverRepo --root $root --guard
        if ($LASTEXITCODE -ne 0) { throw 'world export refused or failed (see above)' }
        Write-Step '4/5 import + checks (client import, world boot, multiplayer)'
        Invoke-ClientHarness
        Invoke-ServerSmoke
        Write-Step '5/5 ready to commit'
        Show-CommitSummary
    }
    'status' {
        $lock = Read-Lock
        Write-Host '=== HPMMO workspace ==='
        if ($lock) {
            Write-Host ("  client pin: {0}   server pin: {1}   godot: {2}" -f $lock.client_revision, $lock.server_revision, $lock.godot_version)
        }
        Write-Host ("  client HEAD: {0}" -f (git -C $clientRepo rev-parse --short HEAD 2>$null))
        Write-Host ("  server HEAD: {0}" -f (git -C $serverRepo rev-parse --short HEAD 2>$null))
        Write-Host '--- contracts ---'
        Test-Contracts | Out-Null
        Write-Host '--- client changes ---'
        git -C $clientRepo status --short
        Write-Host '--- server changes ---'
        git -C $serverRepo status --short
    }
    'test' {
        Invoke-ClientHarness
        Invoke-ServerSmoke
        Write-Host 'workspace tests passed'
    }
    'build' {
        Invoke-ServiceBuild
        $pkg = Join-Path $serverRepo 'deploy\package_server.ps1'
        if (-not (Test-Path $pkg)) { throw "missing $pkg" }
        & powershell -ExecutionPolicy Bypass -File $pkg
        if ($LASTEXITCODE -ne 0) { throw 'server packaging failed' }
        Write-Host 'server package written to server\dist (client export templates are the release pipeline)'
    }
    'start' {
        if ($Server) {
            $godot = Get-Godot
            & $godot --path (Join-Path $serverRepo 'world') res://scenes/server/dedicated_server.tscn
        }
        else {
            $bat = Join-Path $clientRepo 'Launcher.bat'
            if (Test-Path $bat) { & $bat } else { & (Get-Godot) --path $clientRepo }
        }
    }
    'sync-sim' {
        Write-Host '[workspace] syncing the simulation package server -> client'
        & $python (Join-Path $clientRepo 'tools\workspace\sync_sim.py') --client $clientRepo --server $serverRepo --root $root
        if ($LASTEXITCODE -ne 0) { throw 'sync-sim failed' }
    }
    'sync-world' {
        $tool = Join-Path $clientRepo 'tools\workspace\export_world.py'
        if (-not (Test-Path $tool)) { throw "missing $tool" }
        & $python $tool --client $clientRepo --server $serverRepo --root $root
        if ($LASTEXITCODE -ne 0) { throw 'world export failed' }
    }
    'verify-contracts' {
        if (-not (Test-Contracts)) { exit 1 }
        Write-Host 'contracts OK'
    }
}
