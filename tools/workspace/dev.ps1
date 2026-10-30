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
  .\dev.ps1 local             local multiplayer: a dev world server (no accounts, nothing saved) and
                               two game windows joined as test characters (-Names Harry,Draco
                               -Char fluffy: any --test-char preset or a level). Closing the windows
                               stops the server.
  .\dev.ps1 perf              performance probe: a dev world server, -Bots walking headless bots
                               (default 8) and one measuring game window beside a creature pack
                               (tools/capture/perf_probe.gd: idle, camera turn, run, combat). Prints
                               PERF lines; JSON and logs in %TEMP%\hpmmo-perf. -Char: test preset (30).
  .\dev.ps1 sync-world         re-export server\world from the client project + refresh workspace.lock.json
  .\dev.ps1 verify-contracts   fail if contract files drift from workspace.lock.json
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'ready', 'test', 'build', 'start', 'local', 'perf', 'sync-world', 'sync-sim', 'verify-contracts')]
    [string]$Command = 'status',
    [switch]$Client,
    [switch]$Server,
    [string]$Names = 'Harry,Draco',
    [string]$Char = 'fluffy',
    [int]$Port = 7777,
    [int]$Bots = 8
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
        $lines = Invoke-GodotText @('--headless', '--path', $world, '--editor', '--import', '--quit') |
            Select-String -Pattern 'SCRIPT ERROR|ERROR:'
        $lines | Select-Object -First 10
        if ($LASTEXITCODE -ne 0) { throw 'world import failed' }
        # A script that does not parse never fails the import itself: it only
        # prints, and the world then boots without it.
        if ($lines | Where-Object { $_ -match 'SCRIPT ERROR|Parse Error' }) { throw 'world import reported script errors' }
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
        $lines = Invoke-GodotText @('--headless', '--path', $world, 'res://server/world_server.tscn', '--quit-after', '300') |
            Select-String -Pattern 'WorldServer|ERROR|SCRIPT'
        $lines | Select-Object -First 20
        if ($LASTEXITCODE -ne 0) { throw 'world boot smoke failed' }
        if ($lines | Where-Object { $_ -match 'SCRIPT ERROR|Parse Error' }) { throw 'world boot reported script errors' }
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
            $world = Join-Path $serverRepo 'world'
            # The class cache must match the exported files (a sync-world leaves
            # it stale until the world is imported).
            Invoke-GodotText @('--headless', '--path', $world, '--import') | Out-Null
            & $godot --path $world res://server/world_server.tscn
        }
        else {
            $bat = Join-Path $clientRepo 'Launcher.bat'
            if (Test-Path $bat) { & $bat } else { & (Get-Godot) --path $clientRepo }
        }
    }
    'local' {
        # A dev world server: dev joins take the join token as the name, every
        # joiner gets the -Char test character, and nothing is persisted.
        $godot = Get-Godot
        $world = Join-Path $serverRepo 'world'
        $log = Join-Path $env:TEMP 'hpmmo-local-server.log'
        $env:HPMMO_ALLOW_DEV_JOIN = '1'
        $env:HPMMO_DEV_TEST_CHAR = $Char
        $env:HPMMO_WORLD_PORT = "$Port"
        Remove-Item Env:HPMMO_API_URL, Env:HPMMO_SERVICE_TOKEN -ErrorAction SilentlyContinue
        # Both projects' class caches must match the files (a sync leaves the
        # world's stale until it is imported).
        Write-Host '[local] importing the world and the client'
        Invoke-GodotText @('--headless', '--path', $world, '--import') | Out-Null
        Invoke-GodotText @('--headless', '--path', $clientRepo, '--import') | Out-Null
        Write-Host "[local] starting the dev world server on :$Port (log: $log)"
        $worldProc = Start-Process $godot -ArgumentList @('--headless', '--path', "`"$world`"", 'res://server/world_server.tscn') `
            -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -WindowStyle Hidden
        $ready = $false
        for ($i = 0; $i -lt 240 -and -not $worldProc.HasExited; $i++) {
            Start-Sleep -Milliseconds 500
            if ((Test-Path $log) -and (Select-String -Path $log -Pattern "listening on :$Port" -Quiet)) { $ready = $true; break }
        }
        if (-not $ready) {
            if (-not $worldProc.HasExited) { Stop-Process -Id $worldProc.Id -Force }
            throw "the dev world server did not start (see $log)"
        }
        $clients = @()
        $list = @($Names -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        for ($i = 0; $i -lt $list.Count; $i++) {
            Write-Host "[local] joining as $($list[$i]) ($Char)"
            # Each window takes its column of the screen (main_menu --dev-window).
            $clients += Start-Process $godot -PassThru -ArgumentList @('--path', "`"$clientRepo`"", 'res://scenes/main/main_menu.tscn',
                "--dev-join=$($list[$i])", '--port', "$Port", "--dev-window=$i/$($list.Count)")
        }
        Write-Host '[local] close every game window to stop the server'
        $clients | Wait-Process
        if (-not $worldProc.HasExited) { Stop-Process -Id $worldProc.Id -Force }
        Write-Host '[local] server stopped'
    }
    'perf' {
        # Same dev world as `local`, plus walking bots and the measuring probe.
        $godot = Get-Godot
        $world = Join-Path $serverRepo 'world'
        $out = Join-Path $env:TEMP 'hpmmo-perf'
        New-Item -ItemType Directory -Force $out | Out-Null
        $perfChar = if ($PSBoundParameters.ContainsKey('Char')) { $Char } else { '30' }
        $perfPort = if ($PSBoundParameters.ContainsKey('Port')) { $Port } else { 7793 }
        $env:HPMMO_ALLOW_DEV_JOIN = '1'
        $env:HPMMO_DEV_TEST_CHAR = $perfChar
        $env:HPMMO_DEV_SPAWN = 'pack'
        $env:HPMMO_DEV_FAST_RESPAWN = '3000'
        $env:HPMMO_WORLD_PORT = "$perfPort"
        Remove-Item Env:HPMMO_API_URL, Env:HPMMO_SERVICE_TOKEN -ErrorAction SilentlyContinue
        Write-Host '[perf] importing the world and the client'
        Invoke-GodotText @('--headless', '--path', $world, '--import') | Out-Null
        Invoke-GodotText @('--headless', '--path', $clientRepo, '--import') | Out-Null
        $log = Join-Path $out 'server.log'
        Write-Host "[perf] starting the dev world server on :$perfPort (log: $log)"
        $worldProc = Start-Process $godot -ArgumentList @('--headless', '--path', "`"$world`"", 'res://server/world_server.tscn') `
            -RedirectStandardOutput $log -RedirectStandardError "$log.err" -PassThru -WindowStyle Hidden
        $ready = $false
        for ($i = 0; $i -lt 240 -and -not $worldProc.HasExited; $i++) {
            Start-Sleep -Milliseconds 500
            if ((Test-Path $log) -and (Select-String -Path $log -Pattern "listening on :$perfPort" -Quiet)) { $ready = $true; break }
        }
        if (-not $ready) {
            if (-not $worldProc.HasExited) { Stop-Process -Id $worldProc.Id -Force }
            throw "the dev world server did not start (see $log)"
        }
        $probe = 'res://tools/capture/perf_probe.gd'
        $botProcs = @()
        for ($i = 1; $i -le $Bots; $i++) {
            $botProcs += Start-Process $godot -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $out "bot$i.log") -RedirectStandardError (Join-Path $out "bot$i.err.log") `
                -ArgumentList @('--headless', '--path', "`"$clientRepo`"", '-s', $probe, "--dev-join=Bot$i", '--port', "$perfPort", '--walker', '--seconds=170')
        }
        # The bots load the world headless; give them time to be walking.
        if ($Bots -gt 0) { Write-Host "[perf] $Bots bots joining"; Start-Sleep -Seconds 25 }
        $json = Join-Path $out 'perf.json'
        Write-Host '[perf] measuring (about 2 minutes)'
        # Its own log file, not a pipe: a stderr line in a pipe is a terminating
        # error here, and a pipe nobody reads blocks the game on its next print.
        $probeLog = Join-Path $out 'probe.log'
        $probeProc = Start-Process $godot -PassThru -RedirectStandardOutput $probeLog -RedirectStandardError "$probeLog.err" `
            -ArgumentList @('--path', "`"$clientRepo`"", '-s', $probe, '--dev-join=Probe', '--port', "$perfPort", "`"--out=$json`"")
        $probeProc | Wait-Process
        Select-String -Path $probeLog -Pattern '^PERF' | ForEach-Object { $_.Line }
        $botProcs | Where-Object { -not $_.HasExited } | ForEach-Object { Stop-Process -Id $_.Id -Force }
        if (-not $worldProc.HasExited) { Stop-Process -Id $worldProc.Id -Force }
        Write-Host '[perf] server status lines (prof = ms per second / slowest call):'
        Select-String -Path $log -Pattern 'players=([1-9])' | Select-Object -Last 6 | ForEach-Object {
            ($_.Line -split ' \| ')[0] }
        Select-String -Path $log -Pattern 'join peer' | ForEach-Object { $_.Line }
        Write-Host "[perf] results: $json"
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
