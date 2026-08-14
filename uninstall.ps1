# Remove the jwkit copy installed by install.ps1, without removing dependencies
# or jwkit's configuration and downloaded data.
#
#   irm https://raw.githubusercontent.com/majal/jwkit/main/uninstall.ps1 | iex

$ErrorActionPreference = "Stop"
$JwkitHome = if ($env:JWKIT_HOME) { $env:JWKIT_HOME } else { Join-Path $HOME ".jwkit" }
$DefaultHome = Join-Path $HOME ".jwkit"
$Tools = @("ffrife", "jwdl", "jwvideo-mux", "slverse")

function Stop-Uninstall($msg) { Write-Host "jwkit uninstall: $msg" -ForegroundColor Red; exit 1 }
function Write-Ok($msg) { Write-Host $msg -ForegroundColor Green }

if ([string]::IsNullOrWhiteSpace($JwkitHome) -or $JwkitHome -eq (Split-Path $HOME -Qualifier) -or $JwkitHome -eq $HOME) {
    Stop-Uninstall "refusing unsafe JWKIT_HOME: $JwkitHome"
}

if ((Test-Path $JwkitHome) -and $JwkitHome -ne $DefaultHome) {
    $hasFootprint = (Test-Path (Join-Path $JwkitHome "jwkit-update.cmd"))
    foreach ($tool in $Tools) { $hasFootprint = $hasFootprint -and (Test-Path (Join-Path $JwkitHome $tool)) }
    if (-not $hasFootprint) { Stop-Uninstall "refusing to remove custom JWKIT_HOME without an installer footprint: $JwkitHome" }
}

$statePath = Join-Path $JwkitHome ".jwkit-install-state.json"
$installedPackageIds = @()
if (Test-Path $statePath) {
    try { $installedPackageIds = @((Get-Content $statePath -Raw | ConvertFrom-Json).dependencies) } catch { }
}

$currentUserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($currentUserPath) {
    $target = $JwkitHome.TrimEnd("\\", "/")
    $remaining = @($currentUserPath -split ';' | Where-Object { $_ -and $_.TrimEnd("\\", "/") -ine $target })
    $newPath = $remaining -join ';'
    if ($newPath -ne $currentUserPath) {
        [System.Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Ok "Removed $JwkitHome from your user PATH"
    }
}

if (Test-Path $JwkitHome) {
    Remove-Item -Recurse -Force $JwkitHome
    Write-Ok "Removed installed jwkit copy at $JwkitHome"
} else {
    Write-Host "No installed jwkit copy found at $JwkitHome"
}

foreach ($packageId in $installedPackageIds) {
    if ($packageId) {
        Write-Host "Removing installer-added dependency: $packageId"
        try { winget uninstall --id $packageId -e --accept-source-agreements } catch { Write-Host "Could not remove $packageId; leaving it installed." -ForegroundColor Yellow }
    }
}

Write-Host "Kept all ~/.config/jwkit settings and downloads. Existing dependencies not recorded as installer-added were kept."
