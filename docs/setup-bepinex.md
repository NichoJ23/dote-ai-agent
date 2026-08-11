# Task 1.1: BepInEx Installation Guide

## Prerequisites

- Dungeon of the ENDLESS installed via Steam
- PowerShell 5.1+ (included with Windows)

## Important: Unity Version Compatibility

Dungeon of the ENDLESS runs **Unity 5.0.3p3**, which is below BepInEx's officially supported minimum (Unity 5.4+). Standard BepInEx releases (5.4.22, 5.4.23.2) will crash `mono.dll` with an access violation on this game.

**Solution:** Use the patched BepInEx build from [sc2ad/DungeonOfTheEndless-Mod](https://github.com/sc2ad/DungeonOfTheEndless-Mod/releases/tag/4.1.0), which is specifically configured for DotE.

## Automated Installation

Run the install script from the project root:

```powershell
.\scripts\install-bepinex.ps1 -GameDir "C:\Program Files (x86)\Steam\steamapps\common\Dungeon of the ENDLESS"
```

Replace the path with your actual game directory. Find it via Steam: right-click game → Manage → Browse Local Files.

## What the Script Does

1. Downloads the DotE-patched BepInEx build from sc2ad's GitHub release
2. Extracts it into the game directory, placing:
   - `winhttp.dll` — Unity doorstop proxy that bootstraps BepInEx
   - `doorstop_config.ini` — doorstop configuration
   - `BepInEx/core/` — framework assemblies
   - `BepInEx/plugins/` — where our mod DLL will go

## Verification

After installing, launch the game once through Steam:

1. The game should start normally (BepInEx is invisible to gameplay)
2. Close the game after reaching the main menu
3. Check that these files were created:
   - `BepInEx/LogOutput.log` — should contain BepInEx loading messages
   - `BepInEx/config/` — default config directory

If `LogOutput.log` exists and mentions BepInEx loading, the installation is confirmed working.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `mono.dll` access violation crash | You're using a standard BepInEx release; switch to sc2ad's patched build |
| Game doesn't launch at all | Delete `winhttp.dll` and `doorstop_config.ini` to revert |
| No LogOutput.log | Verify `doorstop_config.ini` has `enabled=true` |

## Reverting

To remove BepInEx and restore vanilla game:

```powershell
Remove-Item "$GameDir\winhttp.dll"
Remove-Item "$GameDir\doorstop_config.ini"
Remove-Item -Recurse -Force "$GameDir\BepInEx"
```

## Next Step

Once BepInEx is confirmed loading, proceed to Task 1.2 (decompilation with dnSpy) and Task 1.3 (creating the mod project).
