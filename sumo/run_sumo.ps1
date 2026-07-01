# Run SUMO corridor scenario (after SUMO is installed).
# Usage:
#   .\run_sumo.ps1          # GUI
#   .\run_sumo.ps1 -Headless # no GUI

param([switch]$Headless)

$ErrorActionPreference = "Stop"
$SumoDir = $PSScriptRoot

function Find-SumoExe($name) {
    if ($env:SUMO_HOME) {
        $p = Join-Path $env:SUMO_HOME "bin\$name.exe"
        if (Test-Path $p) { return $p }
    }
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($base in @(
        "${env:ProgramFiles(x86)}\Eclipse\Sumo",
        "$env:ProgramFiles\Eclipse\Sumo",
        "$env:LOCALAPPDATA\Sumo"
    )) {
        $p = Join-Path $base "bin\$name.exe"
        if (Test-Path $p) { return $p }
    }
    return $null
}

$netconvert = Find-SumoExe "netconvert"
$sumo = if ($Headless) { Find-SumoExe "sumo" } else { Find-SumoExe "sumo-gui" }

if (-not $netconvert) {
    Write-Host "SUMO not found. Install from: https://eclipse.dev/sumo/" -ForegroundColor Red
    Write-Host "Then set SUMO_HOME (e.g. C:\Program Files (x86)\Eclipse\Sumo) and re-open PowerShell."
    exit 1
}

if (-not (Test-Path "$SumoDir\corridor.net.xml")) {
    Write-Host "Building corridor.net.xml with netconvert..."
    Push-Location $SumoDir
    & $netconvert --node-files corridor.nod.xml --edge-files corridor.edg.xml --output-file corridor.net.xml --junctions.join false --default.lanewidth 3.25 --geometry.min-radius 12
    Pop-Location
}

if (-not $sumo) {
    Write-Host "sumo-gui not found but netconvert exists at: $netconvert"
    exit 1
}

Push-Location $SumoDir
if ($Headless) {
    & $sumo -c corridor.sumocfg --no-step-log
} else {
    & $sumo -c corridor.sumocfg
}
Pop-Location
