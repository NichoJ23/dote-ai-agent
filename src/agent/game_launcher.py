"""
GameLauncher: Manages game lifecycle — launching the executable, connecting via IPC,
starting/continuing runs, and waiting for the dungeon to load.

Usage:
    launcher = GameLauncher()
    launcher.launch_and_connect()
    menu_state = launcher.query_menu_state()
    launcher.start_new_game(heroes=["Hero_H0001", "Hero_H0002"], ship="Ship_01")
    state = launcher.wait_for_dungeon()
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ipc_client import IpcClient


# Common game install paths to search (Steam default + common locations)
DEFAULT_GAME_PATHS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Dungeon of the Endless\DungeonoftheEndless.exe",
    r"C:\Program Files\Steam\steamapps\common\Dungeon of the Endless\DungeonoftheEndless.exe",
    r"D:\SteamLibrary\steamapps\common\Dungeon of the Endless\DungeonoftheEndless.exe",
]

# Steam app ID for launching via Steam
STEAM_APP_ID = "249050"


@dataclass
class MenuState:
    """Parsed response from QUERY_MENU_STATE command."""
    in_dungeon: bool = False
    has_save: bool = False
    available_heroes: list[str] = field(default_factory=list)
    selectable_heroes: list[str] = field(default_factory=list)
    available_ships: list[str] = field(default_factory=list)


class GameLauncher:
    """
    Manages the full lifecycle of launching and connecting to Dungeon of the ENDLESS.

    Handles:
    - Launching the game executable (direct path or via Steam)
    - Connecting to the mod's IPC once the game is running
    - Querying menu state (available heroes, ships, saves)
    - Starting new games or continuing saved ones
    - Waiting for the dungeon to fully load

    Training Mode:
    - headless=True passes -batchmode -nographics to disable rendering entirely
    - small_window=True launches with a tiny window (64x64) instead of headless
    - These are mutually exclusive — headless takes priority
    """

    def __init__(
        self,
        game_path: Optional[str] = None,
        use_steam: bool = True,
        host: str = "127.0.0.1",
        state_port: int = 5555,
        action_port: int = 5556,
        connect_timeout: float = 120.0,
        recv_timeout: float = 30.0,
        headless: bool = False,
    ):
        """
        Args:
            game_path: Path to DungeonoftheEndless.exe. Auto-detected if None.
            use_steam: If True and game_path is None, launch via Steam protocol.
                       Ignored if headless=True (headless requires direct exe launch).
            host: IPC host address.
            state_port: Port for state channel.
            action_port: Port for action channel.
            connect_timeout: Max seconds to wait for IPC connection after launch.
            recv_timeout: Timeout for individual IPC messages.
            headless: If True, launch with -batchmode -nographics (no GPU rendering).
                      Known to crash on Unity 5.0.3 — use training mode in
                      dote_training.cfg instead for rendering optimizations.
        """
        self.game_path = game_path
        self.use_steam = use_steam
        self.host = host
        self.state_port = state_port
        self.action_port = action_port
        self.connect_timeout = connect_timeout
        self.recv_timeout = recv_timeout
        self.headless = headless

        self._ipc: Optional[IpcClient] = None
        self._process: Optional[subprocess.Popen] = None

    @property
    def is_connected(self) -> bool:
        return self._ipc is not None and self._ipc.is_connected

    def launch_and_connect(self) -> None:
        """
        Launch the game (if not already running) and connect via IPC.

        The mod starts its TCP listeners in Awake(), so once the game process
        is running and BepInEx has loaded, the IPC ports become available.

        Raises:
            RuntimeError: If the game cannot be launched or connection fails.
        """
        # Try connecting first — game might already be running
        if self._try_connect(timeout=5.0):
            print("GameLauncher: Connected to already-running game")
            return

        # Launch the game
        self._launch_game()

        # Wait for IPC to become available
        if not self._try_connect(timeout=self.connect_timeout):
            raise RuntimeError(
                f"Failed to connect to game IPC within {self.connect_timeout}s. "
                "Is BepInEx loaded? Check game logs."
            )

        print("GameLauncher: Connected to game IPC")

    def query_menu_state(self, retries: int = 5, retry_delay: float = 3.0) -> MenuState:
        """
        Query the current menu state from the mod.

        Retries on failure since the game databases may not be loaded yet
        during early startup.

        Returns:
            MenuState with available options.

        Raises:
            ConnectionError: If not connected.
            RuntimeError: If the command fails after all retries.
        """
        self._ensure_connected()

        last_error = ""
        for attempt in range(retries):
            result = self._ipc.send_action("QUERY_MENU_STATE", {})

            if result.get("success", False):
                meta = result.get("metadata", {}) or {}
                return MenuState(
                    in_dungeon=meta.get("in_dungeon", False),
                    has_save=meta.get("has_save", False),
                    available_heroes=meta.get("available_heroes", []),
                    selectable_heroes=meta.get("selectable_heroes", []),
                    available_ships=meta.get("available_ships", []),
                )

            last_error = result.get("error", "unknown")
            if attempt < retries - 1:
                print(f"GameLauncher: QUERY_MENU_STATE not ready ({last_error}), "
                      f"retrying in {retry_delay}s... ({attempt + 1}/{retries})")
                time.sleep(retry_delay)

        raise RuntimeError(f"QUERY_MENU_STATE failed after {retries} attempts: {last_error}")

    def start_new_game(
        self,
        heroes: Optional[list[str]] = None,
        ship: Optional[str] = None,
        difficulty: str = "easy",
        retries: int = 10,
        retry_delay: float = 3.0,
    ) -> dict:
        """
        Start a new game with the specified configuration.

        Retries on failure since GameControlService may not be ready yet
        during early startup.

        Args:
            heroes: List of hero config names (e.g., ["Hero_H0001", "Hero_H0005"]).
                    If None, the game picks random heroes.
            ship: Ship config name. If None, uses the first available ship.
            difficulty: One of "easy", "normal", "hard", "very_hard".
            retries: Number of retry attempts.
            retry_delay: Seconds to wait between retries.

        Returns:
            Action result dict from the mod.

        Raises:
            ConnectionError: If not connected.
            RuntimeError: If the command fails.
        """
        self._ensure_connected()

        params = {"difficulty": difficulty}
        if heroes:
            params["hero_names"] = heroes
        if ship:
            params["ship_name"] = ship

        last_error = ""
        for attempt in range(retries):
            result = self._ipc.send_action("START_NEW_GAME", params)

            if result.get("success", False):
                return result

            last_error = result.get("error", "unknown")
            if attempt < retries - 1:
                print(f"GameLauncher: START_NEW_GAME not ready ({last_error}), "
                      f"retrying in {retry_delay}s... ({attempt + 1}/{retries})")
                time.sleep(retry_delay)

        raise RuntimeError(f"START_NEW_GAME failed after {retries} attempts: {last_error}")

    def continue_game(self, retries: int = 10, retry_delay: float = 3.0) -> dict:
        """
        Continue from the best available save.

        Retries on failure since game services may not be ready during startup.

        Returns:
            Action result dict from the mod.

        Raises:
            ConnectionError: If not connected.
            RuntimeError: If no save exists or the command fails after retries.
        """
        self._ensure_connected()

        last_error = ""
        for attempt in range(retries):
            result = self._ipc.send_action("CONTINUE_GAME", {})

            if result.get("success", False):
                return result

            last_error = result.get("error", "unknown")
            if attempt < retries - 1:
                print(f"GameLauncher: CONTINUE_GAME not ready ({last_error}), "
                      f"retrying in {retry_delay}s... ({attempt + 1}/{retries})")
                time.sleep(retry_delay)

        raise RuntimeError(f"CONTINUE_GAME failed after {retries} attempts: {last_error}")

    def wait_for_dungeon(self, timeout: float = 60.0) -> dict:
        """
        Wait for the dungeon to load and return the first game state.

        After starting a new game or continuing, the game goes through
        loading screens. This method waits until the mod sends a valid
        dungeon state on the state port.

        Args:
            timeout: Max seconds to wait for dungeon state.

        Returns:
            First game state dict from the mod.

        Raises:
            TimeoutError: If dungeon doesn't load within timeout.
            ConnectionError: If not connected.
        """
        self._ensure_connected()

        print(f"GameLauncher: Waiting for dungeon to load (timeout={timeout}s)...")
        start = time.time()

        while time.time() - start < timeout:
            try:
                state = self._ipc.receive_state(timeout=5.0)
                # Verify it's a real dungeon state (has rooms)
                if state and "rooms" in state and len(state.get("rooms", [])) > 0:
                    print(f"GameLauncher: Dungeon loaded! Turn {state.get('turn', '?')}, "
                          f"{len(state['rooms'])} rooms")
                    return state
            except TimeoutError:
                continue
            except ConnectionError:
                # State port might not be sending yet; wait
                time.sleep(1.0)

        raise TimeoutError(f"Dungeon did not load within {timeout}s")

    def start_or_continue(
        self,
        heroes: Optional[list[str]] = None,
        ship: Optional[str] = None,
        difficulty: str = "easy",
    ) -> dict:
        """
        High-level convenience: launch game, continue if save exists, else start new.

        Defaults to Max O'Kane + Gork on the Pod if no heroes/ship specified.

        Returns the first dungeon state.
        """
        if heroes is None:
            heroes = ["Hero_H0001", "Hero_H0003"]  # Max O'Kane, Gork
        if ship is None:
            ship = "Pod"

        self.launch_and_connect()
        menu = self.query_menu_state()

        if menu.in_dungeon:
            print("GameLauncher: Already in dungeon, receiving state...")
            return self.wait_for_dungeon(timeout=10.0)

        if menu.has_save:
            print("GameLauncher: Save found, continuing...")
            self.continue_game()
        else:
            print("GameLauncher: No save, starting new game...")
            self.start_new_game(heroes=heroes, ship=ship, difficulty=difficulty)

        return self.wait_for_dungeon()

    def disconnect(self) -> None:
        """Disconnect from IPC (does not close the game)."""
        if self._ipc:
            self._ipc.disconnect()
            self._ipc = None

    def close(self) -> None:
        """Disconnect and optionally terminate the game process."""
        self.disconnect()
        # We don't kill the game process — user may want it running

    # --- Private helpers ---

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise ConnectionError("Not connected to game. Call launch_and_connect() first.")

    def _try_connect(self, timeout: float) -> bool:
        """Attempt to connect to IPC. Returns True if successful."""
        try:
            ipc = IpcClient(
                host=self.host,
                state_port=self.state_port,
                action_port=self.action_port,
                connect_timeout=timeout,
                recv_timeout=self.recv_timeout,
            )
            ipc.connect()
            self._ipc = ipc
            return True
        except (ConnectionError, OSError):
            return False

    def _launch_game(self) -> None:
        """Launch the game executable with optional headless/training flags."""
        # Headless mode requires direct exe launch (can't pass args via Steam)
        if self.headless:
            exe_path = self._resolve_game_path()
            if exe_path is None:
                raise RuntimeError(
                    "Could not find DungeonoftheEndless.exe. "
                    "headless mode requires a direct exe path. "
                    "Provide game_path or ensure game is installed in a standard location."
                )

            args = [str(exe_path), "-batchmode", "-nographics"]
            print(f"GameLauncher: Launching HEADLESS (no GPU): {exe_path}")

            self._process = subprocess.Popen(
                args,
                cwd=str(exe_path.parent),
            )
            return

        if self.use_steam and not self.game_path:
            # Launch via Steam protocol
            steam_url = f"steam://rungameid/{STEAM_APP_ID}"
            print(f"GameLauncher: Launching via Steam ({steam_url})...")
            subprocess.Popen(
                ["cmd", "/c", "start", "", steam_url],
                shell=False,
            )
            return

        # Direct executable launch (no extra args — mod handles training optimizations)
        exe_path = self._resolve_game_path()
        if exe_path is None:
            raise RuntimeError(
                "Could not find DungeonoftheEndless.exe. "
                "Provide game_path or ensure game is installed in a standard location."
            )

        print(f"GameLauncher: Launching {exe_path}...")
        self._process = subprocess.Popen(
            [str(exe_path)],
            cwd=str(exe_path.parent),
        )

    def _resolve_game_path(self) -> Optional[Path]:
        """Find the game executable."""
        if self.game_path:
            p = Path(self.game_path)
            if p.exists():
                return p
            raise RuntimeError(f"Specified game path does not exist: {self.game_path}")

        # Search default paths
        for path_str in DEFAULT_GAME_PATHS:
            p = Path(path_str)
            if p.exists():
                return p

        return None

    def __enter__(self):
        self.launch_and_connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
