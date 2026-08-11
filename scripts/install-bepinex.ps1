# install-bepinex.ps1
# Downloads and installs BepInEx 5.4.x (Mono x86) into the Dungeon of the ENDLESS game directory.
# Usage: .\install-bepinex.ps1 -GameDir "C:\path\to\Dungeon of the ENDLESS"

param(
    [Parameter(Mandatory = $true)]
    [string]$GameDir
)

$ErrorActionPreference = "Stop"

# BepInEx for Dungeon of the ENDLESS (Unity 5.0.3)
# Standard BepInEx 5.4.x does NOT support Unity < 5.4.
# We use the custom build from sc2ad/DungeonOfTheEndless-Mod which is patched for DotE.
$BepInExZip = "BepInEx.zip"
$DownloadUrl = "https://github.com/sc2ad/DungeonOfTheEndless-Mod/releases/download/4.1.0/$BepInExZip"
$TempDir = Join-Path $env:TEMP "bepinex_install"
$TempZip = Join-Path $TempDir $BepInExZip

# Validate game directory
if (-not (Test-Path $GameDir)) {
    Write-Error "Game directory not found: $GameDir"
    exit 1
}

$GameExe = Get-ChildItem -Path $GameDir -Filter "*.exe" | Where-Object { $_.Name -notmatch "UnityCrashHandler" } | Select-Object -First 1
if (-not $GameExe) {
    Write-Error "No game executable found in: $GameDir"
    exit 1
}

Write-Host "=== BepInEx Installer for Dungeon of the ENDLESS (sc2ad patched build) ===" -ForegroundColor Cyan
Write-Host "Game directory: $GameDir"
Write-Host "Game executable: $($GameExe.Name)"
Write-Host ""

# Check if BepInEx is already installed
$BepInExDir = Join-Path $GameDir "BepInEx"
if (Test-Path $BepInExDir) {
    Write-Host "BepInEx directory already exists at: $BepInExDir" -ForegroundColor Yellow
    $confirm = Read-Host "Overwrite existing installation? (y/N)"
    if ($confirm -ne "y") {
        Write-Host "Aborted."
        exit 0
    }
}

# Create temp directory
if (-not (Test-Path $TempDir)) {
    New-Item -ItemType Directory -Path $TempDir | Out-Null
}

# Download BepInEx
Write-Host "Downloading BepInEx (DotE-patched build from sc2ad)..." -ForegroundColor Green
try {
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $TempZip -UseBasicParsing
} catch {
    Write-Error "Failed to download BepInEx from: $DownloadUrl"
    Write-Error $_.Exception.Message
    exit 1
}

# Extract to game directory
Write-Host "Extracting to game directory..." -ForegroundColor Green
Expand-Archive -Path $TempZip -DestinationPath $GameDir -Force

# Verify installation
$Doorstop = Join-Path $GameDir "winhttp.dll"
$BepInExCore = Join-Path $GameDir "BepInEx\core\BepInEx.dll"

if ((Test-Path $Doorstop) -and (Test-Path $BepInExCore)) {
    Write-Host ""
    Write-Host "=== BepInEx installed successfully! ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Installed files:" -ForegroundColor Cyan
    Write-Host "  - winhttp.dll (doorstop proxy)"
    Write-Host "  - doorstop_config.ini"
    Write-Host "  - BepInEx/core/ (framework DLLs)"
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Launch Dungeon of the ENDLESS once through Steam"
    Write-Host "  2. Close the game after it reaches the main menu"
    Write-Host "  3. Check that BepInEx\LogOutput.log was created"
    Write-Host "  4. The BepInEx\plugins\ folder is now ready for our mod DLL"
} else {
    Write-Error "Installation verification failed. Expected files not found."
    exit 1
}

# Create plugins directory if it doesn't exist (BepInEx creates it on first run, but let's be safe)
$PluginsDir = Join-Path $GameDir "BepInEx\plugins"
if (-not (Test-Path $PluginsDir)) {
    New-Item -ItemType Directory -Path $PluginsDir | Out-Null
}

# Cleanup
Remove-Item -Path $TempDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done." -ForegroundColor Green
