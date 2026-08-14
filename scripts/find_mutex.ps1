# Find mutex/mutant handles held by DungeonoftheEndless.exe
# Requires: Sysinternals handle.exe (or handle64.exe) in PATH or current directory
#
# Download from: https://docs.microsoft.com/en-us/sysinternals/downloads/handle
# Extract handle64.exe somewhere and add to PATH, or place next to this script.
#
# Usage: Run as Administrator
#   powershell .\scripts\find_mutex.ps1

Write-Host "=========================================="
Write-Host "Finding mutex handles for DungeonoftheEndless"
Write-Host "=========================================="
Write-Host ""

# Check if handle64.exe is available
$handleExe = $null
if (Get-Command "handle64.exe" -ErrorAction SilentlyContinue) {
    $handleExe = "handle64.exe"
} elseif (Get-Command "handle.exe" -ErrorAction SilentlyContinue) {
    $handleExe = "handle.exe"
} elseif (Test-Path ".\handle64.exe") {
    $handleExe = ".\handle64.exe"
} elseif (Test-Path ".\handle.exe") {
    $handleExe = ".\handle.exe"
}

if ($null -eq $handleExe) {
    Write-Host "[ERROR] handle64.exe not found!"
    Write-Host ""
    Write-Host "Download Sysinternals Handle from:"
    Write-Host "  https://docs.microsoft.com/en-us/sysinternals/downloads/handle"
    Write-Host ""
    Write-Host "Extract handle64.exe to this directory or add to PATH."
    Write-Host ""
    Write-Host "Alternative: Use Process Explorer (procexp64.exe):"
    Write-Host "  1. Open Process Explorer"
    Write-Host "  2. Find DungeonoftheEndless.exe"
    Write-Host "  3. Lower pane: View > Show Lower Pane > Handles"
    Write-Host "  4. Filter by type 'Mutant'"
    Write-Host ""
    exit 1
}

Write-Host "Using: $handleExe"
Write-Host "Searching for Mutant (mutex) handles..."
Write-Host ""

# Run handle.exe filtering for our process and Mutant type
$output = & $handleExe -a -p DungeonoftheEndless.exe 2>&1 | Select-String -Pattern "Mutant|Mutex"

if ($output) {
    Write-Host "Found mutex handles:"
    Write-Host "--------------------"
    foreach ($line in $output) {
        Write-Host "  $line"
    }
    Write-Host ""
    Write-Host "Look for handles with names like:"
    Write-Host "  - UnityMutex_*"
    Write-Host "  - DVTD_*"  
    Write-Host "  - DungeonoftheEndless*"
    Write-Host "  - Any unique-looking named mutex"
    Write-Host ""
    Write-Host "The one preventing multiple instances will typically have"
    Write-Host "the game name or a Unity-related prefix in it."
} else {
    Write-Host "No Mutant/Mutex handles found matching 'DungeonoftheEndless.exe'"
    Write-Host ""
    Write-Host "The process might use a different mechanism. Let's check all handles:"
    Write-Host ""
    & $handleExe -a -p DungeonoftheEndless.exe 2>&1 | Select-String -Pattern "Mutant"
}
