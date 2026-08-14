# Launch multiple DotE instances by closing the single-instance mutex between launches.
# Requires: handle64.exe in the same directory as this script (or in PATH)
# Must run as Administrator (handle64.exe needs elevation to close handles)
#
# Usage:
#   powershell -ExecutionPolicy Bypass .\scripts\launch_multi.ps1 -NumInstances 2

param(
    [int]$NumInstances = 2,
    [string]$BaseDir = "C:\DotE_Training"
)

$handleExe = Join-Path $PSScriptRoot "handle64.exe"
if (-not (Test-Path $handleExe)) {
    $handleExe = "handle64.exe"  # Try PATH
}

Write-Host "=== Multi-Instance DotE Launcher ==="
Write-Host "Instances: $NumInstances"
Write-Host "Base dir: $BaseDir"
Write-Host ""

for ($i = 0; $i -lt $NumInstances; $i++) {
    $instanceDir = Join-Path $BaseDir "instance_$i"
    $exePath = Join-Path $instanceDir "DungeonoftheEndless.exe"
    
    if (-not (Test-Path $exePath)) {
        Write-Host "[ERROR] Instance $i exe not found: $exePath"
        continue
    }

    Write-Host "Launching instance $i from $instanceDir..."
    Start-Process -FilePath $exePath -WorkingDirectory $instanceDir
    
    # Wait for the game to start and create its mutex
    Write-Host "  Waiting 10s for instance $i to initialize..."
    Start-Sleep -Seconds 10
    
    # Close the single-instance mutex so the next instance can start
    if ($i -lt ($NumInstances - 1)) {
        Write-Host "  Closing single-instance mutex..."
        
        # Find and close the mutex handle
        $output = & $handleExe -a -p DungeonoftheEndless.exe -accepteula 2>&1 | 
            Select-String "SingleInstanceMutex"
        
        if ($output) {
            foreach ($line in $output) {
                # Parse handle ID from output like "  304: Mutant  \Sessions\1\BaseNamedObjects\..."
                if ($line -match '^\s*([0-9A-F]+):\s+Mutant') {
                    $handleId = $Matches[1]
                    Write-Host "  Found mutex handle: $handleId"
                    
                    # Get the PID of the most recent DungeonoftheEndless process
                    $gameProcs = Get-Process -Name "DungeonoftheEndless" -ErrorAction SilentlyContinue | 
                        Sort-Object StartTime -Descending
                    if ($gameProcs) {
                        $gamePid = $gameProcs[0].Id
                        Write-Host "  Closing handle $handleId in PID $gamePid..."
                        & $handleExe -c $handleId -p $gamePid -y -accepteula 2>&1 | Out-Null
                        Write-Host "  Mutex closed for PID $gamePid."
                    }
                }
            }
        } else {
            Write-Host "  [WARN] No SingleInstanceMutex found. The game might use a different mechanism."
            Write-Host "  Trying to launch next instance anyway..."
        }
        
        Start-Sleep -Seconds 2
    }
}

Write-Host ""
Write-Host "=== All $NumInstances instances launched ==="
Write-Host ""
Write-Host "Port assignments:"
for ($i = 0; $i -lt $NumInstances; $i++) {
    $sp = 5555 + ($i * 2)
    $ap = 5556 + ($i * 2)
    Write-Host "  Instance ${i}: state=${sp}, action=${ap}"
}
Write-Host ""
Write-Host "Wait for all instances to reach main menu, then run:"
Write-Host "  python src/agent/train_multi_env.py --num-envs $NumInstances --no-launch --episodes 100"
