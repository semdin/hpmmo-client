param(
    [string]$GodotPath = 'godot',
    [int]$Seconds = 3900,
    [int]$Port = 7791,
    [string]$Name = 'Soak',
    [switch]$Windowed,
    [switch]$FastRespawn,
    [string]$Spawn = '0,0.6,5',
    [string]$Out = ''
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$workspace = Split-Path -Parent $projectPath
$serverWorld = Join-Path $workspace 'server\world'
$logDirectory = Join-Path $PSScriptRoot 'downloads'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
if ($Out -eq '') { $Out = Join-Path $logDirectory 'phase14-soak.jsonl' }

function Resolve-ConsoleGodot([string]$Path) {
    try { $cmd = Get-Command $Path -ErrorAction Stop } catch { return $null }
    if ($cmd.CommandType -ne 'Application') { return $null }
    $target = $cmd.Source
    try {
        $item = Get-Item -ErrorAction Stop $target
        if ($item.Target) {
            $resolved = $item.Target
            if ($resolved -is [array]) { $resolved = $resolved[0] }
            $target = $resolved
        }
    } catch { }
    if ($target -match '_console\.exe$') { return $target }
    $console = $target -replace '\.exe$', '_console.exe'
    if ($console -ne $target -and (Test-Path $console)) { return $console }
    return $null
}
$consoleGodot = Resolve-ConsoleGodot $GodotPath

function Quote-Arg([string]$Value) {
    if ($Value -match '\s') { return '"' + $Value + '"' }
    return $Value
}

$serverOut = Join-Path $logDirectory 'phase14-soak-server.log'
$serverErr = Join-Path $logDirectory 'phase14-soak-server.err.log'
$clientOut = Join-Path $logDirectory 'phase14-soak-client.log'
$clientErr = Join-Path $logDirectory 'phase14-soak-client.err.log'

# --- server -----------------------------------------------------------------
$serverEnv = @{
    HPMMO_WORLD_PORT = "$Port"
    HPMMO_ALLOW_DEV_JOIN = '1'
    HPMMO_DEV_SPAWN = $Spawn
}
if ($FastRespawn) { $serverEnv['HPMMO_DEV_FAST_RESPAWN'] = '6000' }
foreach ($key in $serverEnv.Keys) {
    [Environment]::SetEnvironmentVariable($key, $serverEnv[$key], 'Process')
}
$serverArgs = @('--headless', '--path', $serverWorld, 'res://server/world_server.tscn')
$server = Start-Process -FilePath $GodotPath -ArgumentList @($serverArgs | ForEach-Object { Quote-Arg $_ }) `
    -NoNewWindow -PassThru -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr

# Wait for the server to bind (its boot prints the port line).
$bound = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $serverOut) {
        if (Select-String -Path $serverOut -Pattern 'listening on' -Quiet) { $bound = $true; break }
    }
    if ($server.HasExited) { break }
}
if (-not $bound) {
    Write-Host 'server did not report a bound UDP port; continuing anyway (log: phase14-soak-server.log)'
}

# --- client -----------------------------------------------------------------
# Headless by default: a soak is a memory measurement and must not leave a game
# window on the desktop. -Windowed runs the low-preset renderer path instead.
$clientArgs = @('--headless', '--path', $projectPath, 'res://scenes/test/phase14_soak.tscn')
if ($Windowed) { $clientArgs = @('--path', $projectPath, 'res://scenes/test/phase14_soak.tscn') }
$clientArgs += @('--', "--port=$Port", "--name=$Name", "--seconds=$Seconds", "--out=$Out")
$sw = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $client = Start-Process -FilePath $GodotPath -ArgumentList @($clientArgs | ForEach-Object { Quote-Arg $_ }) `
        -NoNewWindow -PassThru -RedirectStandardOutput $clientOut -RedirectStandardError $clientErr
    $client.WaitForExit()
    $clientCode = $client.ExitCode
} finally {
    if (-not $server.HasExited) { $server.Kill() }
    $sw.Stop()
}
Write-Host ("soak client exit={0} duration={1:n0}s" -f $clientCode, $sw.Elapsed.TotalSeconds)
Write-Host ("samples: {0}" -f $Out)
Get-Content $clientOut -Tail 4
