#!/usr/bin/env powershell
<#
HPMMO workspace helper.
Canonical source: client/tools/workspace/dev.ps1 - this root copy is generated.

Commands:
  .\dev.ps1 status             pinned revisions, contract-hash check, repo states
  .\dev.ps1 test               client check harness; server service compile + world boot smoke
  .\dev.ps1 build              server deployable package into server\dist (client export = Phase 7)
  .\dev.ps1 start -Client      launch the game
  .\dev.ps1 start -Server      launch the dedicated server world (headless)
  .\dev.ps1 sync-world         re-export server\world from the client project + refresh workspace.lock.json
  .\dev.ps1 verify-contracts   fail if contract files drift from workspace.lock.json
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'test', 'build', 'start', 'sync-world', 'verify-contracts')]
    [string]$Command = 'status',
    [switch]$Client,
    [switch]$Server
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$client = Join-Path $root 'client'
$server = Join-Path $root 'server'
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

function Test-Contracts([switch]$Quiet) {
    $lock = Read-Lock
    if (-not $lock) { if (-not $Quiet) { Write-Host 'no workspace.lock.json' }; return $false }
    $ok = $true
    foreach ($entry in $lock.contracts.PSObject.Properties) {
        $name = $entry.Name
        $want = $entry.Value.hash
        foreach ($repo in @(@('client', $client), @('server', $server))) {
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
    $script = Join-Path $client 'tools\run_game_checks.ps1'
    if (-not (Test-Path $script)) { throw "missing $script" }
    & powershell -ExecutionPolicy Bypass -File $script
    if ($LASTEXITCODE -ne 0) { throw 'client harness failed' }
}

function Invoke-ServerSmoke {
    $svc = Join-Path $server 'services\db_service.py'
    $world = Join-Path $server 'world'
    Write-Host '[server] compile service'
    & $python -m py_compile $svc
    if ($LASTEXITCODE -ne 0) { throw 'service does not compile' }
    $smoke = Join-Path $server 'tests\smoke_service.py'
    if (Test-Path $smoke) {
        Write-Host '[server] service smoke (temp sqlite, health + save-key rejection)'
        & $python $smoke
        if ($LASTEXITCODE -ne 0) { throw 'service smoke failed' }
    }
    if (Test-Path (Join-Path $world 'project.godot')) {
        $godot = Get-Godot
        Write-Host '[server] world import pass'
        & $godot --headless --path $world --editor --import --quit 2>&1 |
            Select-String -Pattern 'SCRIPT ERROR|ERROR:' | Select-Object -First 10
        if ($LASTEXITCODE -ne 0) { throw 'world import failed' }
        Write-Host '[server] world boot smoke (headless, 300 frames)'
        & $godot --headless --path $world res://scenes/server/dedicated_server.tscn --quit-after 300 2>&1 |
            Select-String -Pattern 'Dedicated Server|ERROR|SCRIPT' | Select-Object -First 20
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
        Write-Host ("  client HEAD: {0}" -f (git -C $client rev-parse --short HEAD 2>$null))
        Write-Host ("  server HEAD: {0}" -f (git -C $server rev-parse --short HEAD 2>$null))
        Write-Host '--- contracts ---'
        Test-Contracts | Out-Null
        Write-Host '--- client changes ---'
        git -C $client status --short
        Write-Host '--- server changes ---'
        git -C $server status --short
    }
    'test' {
        Invoke-ClientHarness
        Invoke-ServerSmoke
        Write-Host 'workspace tests passed'
    }
    'build' {
        $pkg = Join-Path $server 'deploy\package_server.ps1'
        if (-not (Test-Path $pkg)) { throw "missing $pkg" }
        & powershell -ExecutionPolicy Bypass -File $pkg
        if ($LASTEXITCODE -ne 0) { throw 'server packaging failed' }
        Write-Host 'server package written to server\dist (client export templates are Phase 7)'
    }
    'start' {
        if ($Server) {
            $godot = Get-Godot
            & $godot --path (Join-Path $server 'world') res://scenes/server/dedicated_server.tscn
        }
        else {
            $bat = Join-Path $client 'Launcher.bat'
            if (Test-Path $bat) { & $bat } else { & (Get-Godot) --path $client }
        }
    }
    'sync-world' {
        $tool = Join-Path $client 'tools\workspace\export_world.py'
        if (-not (Test-Path $tool)) { throw "missing $tool" }
        & $python $tool --client $client --server $server --root $root
        if ($LASTEXITCODE -ne 0) { throw 'world export failed' }
    }
    'verify-contracts' {
        if (-not (Test-Contracts)) { exit 1 }
        Write-Host 'contracts OK'
    }
}
