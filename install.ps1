# jwkit installer for Windows.
#
#   irm https://raw.githubusercontent.com/majal/jwkit/main/install.ps1 | iex
#
# Installs Python/ffmpeg/git if missing (via winget), downloads jwkit to
# %USERPROFILE%\.jwkit, adds it to your PATH, and sets up a jwkit-update
# command. Safe to re-run to update jwkit in place - but unlike install.sh
# (a real git checkout, so local edits are detected and preserved), this
# downloads a fresh zip and replaces %USERPROFILE%\.jwkit's contents
# outright, so any direct edits made there are discarded. Keep changes of
# your own outside that folder, or in your own git clone pointed at via
# JWKIT_HOME.

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/majal/jwkit"
$RepoZip = "$RepoUrl/archive/refs/heads/main.zip"
$JwkitHome = if ($env:JWKIT_HOME) { $env:JWKIT_HOME } else { Join-Path $HOME ".jwkit" }
$Tools = @("ffinpaint", "ffrife", "ffv", "jwdl", "jwkit-provenance", "jwpl", "jwvideo-mux", "register-jwplay-launcher", "slverse")
$InstalledPackageIds = @()
# jwdl and jwvideo-mux import tomllib, which is Python 3.11+.
$PythonPackageId = "Python.Python.3.13"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host $msg -ForegroundColor Green }
function Write-Warn($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host $msg -ForegroundColor Red }

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Test-RealPython {
    # Command *existence* proves nothing on a fresh Windows box: the
    # Microsoft Store ships python.exe/python3.exe stubs in WindowsApps that
    # "exist" but only print "Python was not found" (exit 9009). So run the
    # candidate and ask it for its version instead.
    param([string]$Exe, [string[]]$PreArgs = @())
    if (-not (Test-Command $Exe)) { return $false }
    $oldEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $Exe @PreArgs -c "import sys; print(int(sys.version_info >= (3, 11)))" 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq "1")
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $oldEap
    }
}

function Test-PythonUsable {
    return (Test-RealPython "py" @("-3")) -or (Test-RealPython "python")
}

function Install-WingetPackage($id) {
    # $ErrorActionPreference = "Stop" only catches terminating PowerShell
    # errors - it does NOT catch a non-zero exit code from a native .exe
    # like winget.exe, so a failed install (network blip, pending-reboot
    # lock, UAC declined, ...) used to be silently treated as success and
    # the script kept going, right through writing shims that call a
    # binary that was never actually installed.
    winget install --id $id -e --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget install --id $id failed (exit code $LASTEXITCODE)"
    }
}

Write-Step "Setting up jwkit"

try {
    # --- Dependencies ---
    Write-Step "Checking for winget (Windows Package Manager)"
    if (-not (Test-Command winget)) {
        Write-Err "winget isn't available on this machine."
        Write-Err "Install 'App Installer' from the Microsoft Store, then re-run this script:"
        Write-Err "  https://aka.ms/getwinget"
        exit 1
    }

    Write-Step "Checking Python, ffmpeg, git"
    $havePython = Test-PythonUsable
    if (-not $havePython) {
        Write-Warn "Installing Python (a usable Python 3.11+ wasn't found; the Microsoft Store python.exe stub doesn't count)..."
        Install-WingetPackage $PythonPackageId
        $InstalledPackageIds += $PythonPackageId
    }
    if (-not (Test-Command ffmpeg)) {
        Write-Warn "Installing ffmpeg..."
        Install-WingetPackage "Gyan.FFmpeg"
        $InstalledPackageIds += "Gyan.FFmpeg"
    }
    if (-not (Test-Command git)) {
        Write-Warn "Installing git..."
        Install-WingetPackage "Git.Git"
        $InstalledPackageIds += "Git.Git"
    }
    if ($InstalledPackageIds.Count -eq 0) {
        Write-Ok "Already have Python, ffmpeg, and git."
    }

    # Refresh PATH in this session so newly-installed tools are usable
    # without reopening the terminal.
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"

    if (-not (Test-PythonUsable)) {
        throw "Python 3.11+ still isn't runnable after setup. Install it from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH'), then re-run this installer."
    }

    # --- Fetch jwkit ---
    Write-Step "Getting jwkit"
    $statePath = Join-Path $JwkitHome ".jwkit-install-state.json"
    $previousDependencies = @()
    if (Test-Path $statePath) {
        try { $previousDependencies = @((Get-Content $statePath -Raw | ConvertFrom-Json).dependencies) } catch { }
    }
    if (Test-Path $JwkitHome) {
        $dotGit = Join-Path $JwkitHome ".git"
        if (Test-Path $dotGit) {
            # A real git checkout at $JwkitHome (e.g. hand-set up by a
            # developer pointing JWKIT_HOME at their own clone) - mirror
            # install.sh's own guard rather than blowing away uncommitted
            # work the way the normal zip-based wipe-and-replace below does.
            $gitStatus = & git -C $JwkitHome status --porcelain 2>$null
            if ($gitStatus) {
                Write-Warn "Local changes found in $JwkitHome (it's a git checkout); leaving it untouched."
                Write-Warn "Commit, stash, or remove them, then run this installer again."
                exit 0
            }
        } else {
            Write-Warn "Replacing the existing install at $JwkitHome - this download-and-replace (unlike install.sh's git-based update) discards any direct edits made there, not just installer-managed files."
        }
        Remove-Item -Recurse -Force $JwkitHome
    }
    New-Item -ItemType Directory -Path $JwkitHome -Force | Out-Null

    $zipPath = Join-Path $env:TEMP "jwkit-install.zip"
    $extractPath = Join-Path $env:TEMP "jwkit-install-extract"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    if (Test-Path $extractPath) { Remove-Item -Recurse -Force $extractPath }

    Invoke-WebRequest -Uri $RepoZip -OutFile $zipPath
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
    $extractedRoot = Get-ChildItem -Path $extractPath -Directory | Select-Object -First 1
    Copy-Item -Path (Join-Path $extractedRoot.FullName "*") -Destination $JwkitHome -Recurse -Force
    Remove-Item -Recurse -Force $extractPath, $zipPath
    $allDependencies = @($previousDependencies + $InstalledPackageIds | Select-Object -Unique)
    if ($allDependencies.Count -gt 0) {
        @{ dependencies = $allDependencies } | ConvertTo-Json | Set-Content -Path $statePath -Encoding UTF8
    }

    # --- Command shims (Windows won't run a shebang-only script directly) ---
    Write-Step "Creating command shims"
    foreach ($tool in $Tools) {
        $toolPath = Join-Path $JwkitHome $tool
        if (Test-Path $toolPath) {
            $shimPath = Join-Path $JwkitHome "$tool.cmd"
            # Resolve Python at run time, not install time: prefer the py
            # launcher (python.org/winget installs always add it), fall back
            # to python on PATH.
            $shim = "@echo off`r`nwhere py >nul 2>nul`r`nif not errorlevel 1 (`r`n  py -3 `"%~dp0$tool`" %*`r`n  exit /b %errorlevel%`r`n)`r`npython `"%~dp0$tool`" %*`r`nexit /b %errorlevel%`r`n"
            Set-Content -Path $shimPath -Value $shim -Encoding ASCII -NoNewline
        }
    }

    # --- PATH ---
    Write-Step "Adding jwkit to your PATH"
    $currentUserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    if ($currentUserPath -notlike "*$JwkitHome*") {
        $newPath = if ($currentUserPath) { "$currentUserPath;$JwkitHome" } else { $JwkitHome }
        [System.Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Ok "Added $JwkitHome to your PATH"
    } else {
        Write-Ok "Already on your PATH"
    }
    $env:Path = "$env:Path;$JwkitHome"

    # --- Update command ---
    $updateShim = Join-Path $JwkitHome "jwkit-update.cmd"
    Set-Content -Path $updateShim -Value "@echo off`r`npowershell -NoProfile -Command `"irm https://raw.githubusercontent.com/majal/jwkit/main/install.ps1 | iex`"" -Encoding ASCII

    # --- Smoke test: run a real shim, the way a new terminal will ---
    Write-Step "Checking that jwdl runs"
    $smoke = & (Join-Path $JwkitHome "jwdl.cmd") --help 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "jwdl.cmd --help failed (exit $LASTEXITCODE): $smoke"
    }
    Write-Ok "jwdl runs."

    Write-Step "All set!"
    Write-Ok "jwkit is installed at $JwkitHome"
    Write-Host ""
    Write-Host "Close ALL open PowerShell / Terminal windows and open a new one (an already-running Windows Terminal keeps the old PATH), then try:"
    Write-Host "  slverse --help" -ForegroundColor White
    Write-Host "  jwdl list" -ForegroundColor White
    Write-Host ""
    Write-Host "For the interactive setup (languages, cache size, etc.), run:"
    Write-Host "  slverse setup" -ForegroundColor White
    Write-Host ""
    Write-Host "To update jwkit later, run:"
    Write-Host "  jwkit-update" -ForegroundColor White
}
catch {
    Write-Err "Something went wrong partway through setup: $_"
    Write-Err "You can re-run this installer any time - it's safe to repeat."
    Write-Err "If it keeps failing, please open an issue: $RepoUrl/issues"
    exit 1
}
