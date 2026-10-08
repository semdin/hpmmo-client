#!/usr/bin/env powershell
<#
HPMMO workspace helper.
Canonical source: client/tools/workspace/dev.ps1 - this root copy is generated.

Commands:
  .\dev.ps1 status             pinned revisions, contract-hash check, repo states
  .\dev.ps1 test               client check harness; server service compile + world boot smoke
  .\dev.ps1 build              server deployable package into server\dist (client export = the release pipeline)
  .\dev.ps1 start -Client      launch the game
  .\dev.ps1 start -Server      launch the dedicated server world (headless)
  .\dev.ps1 sync-world         re-export server\world from the client project + refresh workspace.lock.json
  .\dev.ps1 verify-contracts   fail if contract files drift from workspace.lock.json
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'test', 'build', 'start', 'sync-world', 'sync-sim', 'verify-contracts')]
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

function Invoke-ClientHarness {
    $script = Join-Path $clientRepo 'tools\run_game_checks.ps1'
    if (-not (Test-Path $script)) { throw "missing $script" }
    & powershell -ExecutionPolicy Bypass -File $script
    if ($LASTEXITCODE -ne 0) { throw 'client harness failed' }
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

function Invoke-ServerSmoke {
    $world = Join-Path $serverRepo 'world'
    Test-WorldFileList
    Invoke-ServiceBuild
    Write-Host '[server] legacy python service compile (kept as fallback reference)'
    & $python -m py_compile (Join-Path $serverRepo 'services\db_service.py')
    if ($LASTEXITCODE -ne 0) { throw 'legacy service does not compile' }
    $integration = Join-Path $serverRepo 'tests\integration_api.py'
    if (Test-Path $integration) {
        Write-Host '[server] persistence integration tests (PostgreSQL + C++ service, self-contained)'
        & $python $integration
        if ($LASTEXITCODE -ne 0) { throw 'integration tests failed' }
    }
    $multiplayer = Join-Path $serverRepo 'tests\multiplayer_sim.py'
    if (Test-Path $multiplayer) {
        Write-Host '[server] multiplayer proof (world server + two headless clients)'
        & $python $multiplayer --skip=forged,protection
        if ($LASTEXITCODE -ne 0) { throw 'multiplayer agreement test failed' }
    }
    if (Test-Path (Join-Path $world 'project.godot')) {
        $godot = Get-Godot
        Write-Host '[server] world import pass'
        & $godot --headless --path $world --editor --import --quit 2>&1 |
            Select-String -Pattern 'SCRIPT ERROR|ERROR:' | Select-Object -First 10
        if ($LASTEXITCODE -ne 0) { throw 'world import failed' }
        Test-SimSync
        Write-Host '[server] world boot smoke (headless, 300 frames)'
        & $godot --headless --path $world res://server/world_server.tscn --quit-after 300 2>&1 |
            Select-String -Pattern 'WorldServer|ERROR|SCRIPT' | Select-Object -First 20
        if ($LASTEXITCODE -ne 0) { throw 'world boot smoke failed' }
    }
}

switch ($Command) {
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
