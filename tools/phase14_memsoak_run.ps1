# Phase 14 D14-3 diagnosis driver.
#
# Runs the resource-class soak recorder (scripts/test/phase14_memsoak.gd) against
# a FROZEN client tree and a FROZEN server world, so a long measurement is not
# taken while another workstream edits the live sim. The client's synced
# addons/hpmmo_sim is copied over the server world's copy first: that is the
# direction dev.ps1 sync-sim uses, and it guarantees both ends run the same
# protocol.gd.
#
# Usage: phase14_memsoak_run.ps1 [-Seconds 1800] [-Port 7791] [-Windowed] [-Name MemSoak]
param(
    [int]$Seconds = 1800,
    [int]$Port = 7791,
    [switch]$Windowed,
    [string]$Name = 'MemSoak',
    [string]$ClientTree = 'C:\Users\mehme\hpmmo-measure\client'
)
$ErrorActionPreference = 'Stop'
$ROOT = 'C:\Users\mehme\Desktop\sem\projects\game'
$FROZEN_C = $ClientTree
$FROZEN_S = 'C:\Users\mehme\hpmmo-measure\server-world\world'
$GODOT = 'C:\Users\mehme\AppData\Local\Microsoft\WinGet\Packages\GodotEngine.GodotEngine_Microsoft.Winget.Source_8wekyb3d8bbwe\Godot_v4.7.2-stable_win64_console.exe'
$OUT = Join-Path $ROOT 'client\tools\downloads'

New-Item -ItemType Directory -Force -Path $OUT | Out-Null

# probe sources live in the live tree, are copied into the frozen tree per run
Copy-Item "$ROOT\client\scripts\test\phase14_memsoak.gd" "$FROZEN_C\scripts\test\" -Force
Copy-Item "$ROOT\client\scenes\test\phase14_memsoak.tscn" "$FROZEN_C\scenes\test\" -Force
Copy-Item "$ROOT\client\scripts\test\phase14_soak.gd" "$FROZEN_C\scripts\test\" -Force
Copy-Item "$ROOT\client\scenes\test\phase14_soak.tscn" "$FROZEN_C\scenes\test\" -Force
# NOTE: the frozen server world keeps its own addon copy. Verified compatible
# with the frozen client (same PROTOCOL_VERSION 6, same SimAuthority surface);
# copying the client copy over it was tried and made the server fail to parse,
# so it is deliberately NOT done here.

$serverOut = Join-Path $OUT "phase14-memsoak-$Name-server.log"
$serverErr = Join-Path $OUT "phase14-memsoak-$Name-server.err.log"
$clientOut = Join-Path $OUT "phase14-memsoak-$Name-client.log"
$clientErr = Join-Path $OUT "phase14-memsoak-$Name-client.err.log"
$memOut = Join-Path $OUT "phase14-memsoak-$Name.jsonl"

$env:HPMMO_WORLD_PORT = "$Port"
$env:HPMMO_ALLOW_DEV_JOIN = '1'
$env:HPMMO_DEV_SPAWN = '0,0.6,5'
$env:HPMMO_DEV_FAST_RESPAWN = '6000'

Write-Host "starting frozen server world on $Port ..."
$server = Start-Process -FilePath $GODOT -ArgumentList @('--headless', '--path', $FROZEN_S, 'res://server/world_server.tscn') `
    -NoNewWindow -PassThru -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr
$bound = $false
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $serverOut) {
        if (Select-String -Path $serverOut -Pattern 'listening on' -Quiet) { $bound = $true; break }
    }
    if ($server.HasExited) { break }
}
if (-not $bound) {
    Write-Host "WARNING: server did not report a bound UDP port; see $serverOut"
    Get-Content $serverOut -Tail 20
}

$clientArgs = @('--path', $FROZEN_C, 'res://scenes/test/phase14_memsoak.tscn')
if (-not $Windowed) { $clientArgs = @('--headless') + $clientArgs }
$clientArgs += @('--', "--port=$Port", "--name=$Name", "--seconds=$Seconds",
    "--out=$memOut.actions.jsonl", "--mem-out=$memOut", "--sample=5")

Write-Host "starting client: $($clientArgs -join ' ')"
$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $client = Start-Process -FilePath $GODOT -ArgumentList @($clientArgs | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) `
        -NoNewWindow -PassThru -RedirectStandardOutput $clientOut -RedirectStandardError $clientErr
    $client.WaitForExit()
    $clientCode = $client.ExitCode
} finally {
    if (-not $server.HasExited) { $server.Kill() }
    $sw.Stop()
}
Write-Host ("memsoak client exit={0} duration={1:n0}s log={2}" -f $clientCode, $sw.Elapsed.TotalSeconds, $clientOut)
Get-Content $clientOut -Tail 3
