"""
run_agent.py: Main game loop runner for the heuristic agent.

Instantiates the DotE environment, loads guidelines, creates the HeuristicAgent,
and loops step() until the game terminates.

Supports:
  - Starting a new game or continuing a saved one
  - Multiple floor runs (if the agent escapes a floor)
  - Metrics collection and saving
  - Graceful shutdown on interrupt

Usage:
    python run_agent.py                          # Default: new game, Max+Gork, Pod, Easy
    python run_agent.py --continue               # Continue saved game
    python run_agent.py --config guidelines.yaml # Custom guidelines
    python run_agent.py --max-floors 3           # Stop after 3 floors
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

from game_launcher import GameLauncher
from guidelines_config import GuidelinesConfig
from heuristic_agent import HeuristicAgent
from ipc_client import IpcClient
from metrics import FloorMetrics, RunMetrics
from state_parser import GameStatePayload, StateParser

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_HEROES = ["Hero_H0001", "Hero_H0003"]  # Max O'Kane + Gork
DEFAULT_SHIP = "Pod"
DEFAULT_DIFFICULTY = "easy"
MAX_ACTIONS_PER_TURN = 50  # Safety: prevent infinite action loops within one turn
MAX_NULL_ACTIONS = 5  # If agent returns None this many times, wait for next state


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------


class AgentRunner:
    """
    Orchestrates the main game loop: launch → connect → play → collect metrics.
    """

    def __init__(
        self,
        guidelines: Optional[GuidelinesConfig] = None,
        heroes: Optional[list[str]] = None,
        ship: str = DEFAULT_SHIP,
        difficulty: str = DEFAULT_DIFFICULTY,
        continue_game: bool = False,
        max_floors: int = 1,
        metrics_dir: str = "metrics",
        use_steam: bool = True,
    ):
        self.guidelines = guidelines or GuidelinesConfig()
        self.heroes = heroes or (
            self.guidelines.preferred_starting_heroes
            if self.guidelines.preferred_starting_heroes
            else DEFAULT_HEROES
        )
        self.ship = ship
        self.difficulty = difficulty
        self.continue_game = continue_game
        self.max_floors = max_floors
        self.metrics_dir = Path(metrics_dir)
        self.use_steam = use_steam

        self._agent = HeuristicAgent(guidelines=self.guidelines)
        self._parser = StateParser()
        self._launcher: Optional[GameLauncher] = None
        self._ipc: Optional[IpcClient] = None
        self._running = False
        self._run_metrics = RunMetrics()

    def run(self) -> RunMetrics:
        """
        Execute the full game run.

        Returns:
            RunMetrics with collected statistics.
        """
        self._running = True
        self._setup_signal_handlers()

        try:
            # Launch game and connect
            self._launcher = GameLauncher(use_steam=self.use_steam)
            self._launcher.launch_and_connect()
            self._ipc = self._launcher._ipc

            # Start or continue game
            if self.continue_game:
                logger.info("Continuing saved game...")
                self._launcher.continue_game()
            else:
                logger.info(
                    f"Starting new game: heroes={self.heroes}, ship={self.ship}, "
                    f"difficulty={self.difficulty}"
                )
                self._launcher.start_new_game(
                    heroes=self.heroes,
                    ship=self.ship,
                    difficulty=self.difficulty,
                )

            # Wait for dungeon to load
            logger.info("Waiting for dungeon to load...")
            first_state_dict = self._launcher.wait_for_dungeon(timeout=120)
            first_state = self._parser.parse(first_state_dict)

            # Play floors
            floors_played = 0
            current_state = first_state

            while self._running and floors_played < self.max_floors:
                logger.info(f"=== Starting Floor {current_state.floor} ===")
                floor_metrics = self._play_floor(current_state)
                self._run_metrics.add_floor(floor_metrics)
                floors_played += 1

                if floor_metrics.outcome == "game_over":
                    logger.info("Game over! Crystal destroyed.")
                    break
                elif floor_metrics.outcome == "escaped":
                    logger.info(f"Floor {floor_metrics.floor_number} escaped!")
                    if floors_played < self.max_floors:
                        # Send NEXT_FLOOR to skip dialogue and start next level
                        logger.info("Sending NEXT_FLOOR command...")
                        try:
                            import time as _time
                            _time.sleep(3.0)  # Give game time to show lift panel
                            result = self._ipc.send_action("NEXT_FLOOR", {})
                            if not result.get("success", False):
                                logger.warning(f"NEXT_FLOOR failed: {result.get('error')}, retrying...")
                                _time.sleep(5.0)
                                result = self._ipc.send_action("NEXT_FLOOR", {})
                        except Exception as e:
                            logger.error(f"Failed to start next floor: {e}")
                            break

                        # Wait for next floor dungeon to load
                        # Must detect floor number change to avoid stale states from previous floor
                        current_floor = current_state.floor
                        try:
                            next_state_dict = self._ipc.wait_for_state(
                                condition=lambda s: s.get("floor", 0) > current_floor,
                                timeout=60,
                            )
                            current_state = self._parser.parse(next_state_dict)
                        except TimeoutError:
                            logger.warning("Timeout waiting for next floor. Ending run.")
                            break
                else:
                    break

            # Finish run
            if any(f.outcome == "game_over" for f in self._run_metrics.floors_completed):
                self._run_metrics.finish("game_over")
            elif all(f.outcome == "escaped" for f in self._run_metrics.floors_completed):
                self._run_metrics.finish("escaped_all")
            else:
                self._run_metrics.finish("aborted")

        except KeyboardInterrupt:
            logger.info("Run interrupted by user.")
            self._run_metrics.finish("aborted")
        except Exception as e:
            logger.exception(f"Run failed with error: {e}")
            self._run_metrics.finish("aborted")
        finally:
            self._save_metrics()
            self._run_metrics.print_summary()

        return self._run_metrics

    def _play_floor(self, initial_state: GameStatePayload) -> FloorMetrics:
        """
        Play through a single floor.

        Args:
            initial_state: The first state after the floor loads.

        Returns:
            FloorMetrics for this floor.
        """
        floor_metrics = FloorMetrics(floor_number=initial_state.floor)
        floor_metrics.start()
        floor_metrics.update_from_state(initial_state)

        self._agent.reset()
        current_state = initial_state
        null_action_count = 0
        last_turn = current_state.turn
        actions_this_turn = 0

        # Drain any pending state updates (e.g., turn 0 -> turn 1 transition
        # that arrived while we were initializing). Cap at 2s wall-clock to avoid
        # getting stuck when state pushes are very frequent (high timeScale).
        import time as _drain_time
        drain_start = _drain_time.time()
        try:
            while _drain_time.time() - drain_start < 2.0:
                next_state_dict = self._ipc.receive_state(timeout=0.5)
                current_state = self._parser.parse(next_state_dict)
                floor_metrics.update_from_state(current_state)
                last_turn = current_state.turn
                logger.debug(f"Drained buffered state: turn {current_state.turn}")
        except TimeoutError:
            pass  # No more buffered states

        while self._running:
            # Check termination
            if current_state.is_game_over:
                floor_metrics.finish("game_over")
                return floor_metrics

            if current_state.is_escaping:
                # Crystal is on exit slot — floor is complete
                floor_metrics.finish("escaped")
                return floor_metrics

            # Get action from agent
            action = self._agent.select_action(current_state)

            if action is None:
                null_action_count += 1
                if null_action_count >= MAX_NULL_ACTIONS:
                    # Agent has nothing to do — wait for next state update
                    try:
                        next_state_dict = self._ipc.receive_state(timeout=5.0)
                        current_state = self._parser.parse(next_state_dict)
                        floor_metrics.update_from_state(current_state)
                        null_action_count = 0

                        # Check if turn advanced
                        if current_state.turn != last_turn:
                            last_turn = current_state.turn
                            actions_this_turn = 0
                            self._agent.new_turn()
                    except TimeoutError:
                        logger.warning("Timeout waiting for state. Continuing...")
                        continue
                continue

            # Handle WAIT sentinel: agent is waiting for heroes to finish
            # their current commands before proceeding (e.g., before opening a door)
            if action.get("command") == "WAIT":
                logger.debug("Agent returned WAIT — polling for state until heroes ready")
                try:
                    next_state_dict = self._ipc.receive_state(timeout=3.0)
                    current_state = self._parser.parse(next_state_dict)
                    floor_metrics.update_from_state(current_state)

                    if current_state.turn != last_turn:
                        last_turn = current_state.turn
                        actions_this_turn = 0
                        self._agent.new_turn()
                except TimeoutError:
                    pass  # Will retry on next loop iteration
                continue

            # Safety: prevent infinite loops within a single turn
            actions_this_turn += 1
            if actions_this_turn > MAX_ACTIONS_PER_TURN:
                logger.warning(
                    f"Hit max actions per turn ({MAX_ACTIONS_PER_TURN}). "
                    "Waiting for next state."
                )
                try:
                    next_state_dict = self._ipc.receive_state(timeout=30.0)
                    current_state = self._parser.parse(next_state_dict)
                    floor_metrics.update_from_state(current_state)
                    actions_this_turn = 0
                    if current_state.turn != last_turn:
                        last_turn = current_state.turn
                        self._agent.new_turn()
                except TimeoutError:
                    pass
                continue

            null_action_count = 0

            # Execute action
            command = action["command"]
            parameters = action["parameters"]

            try:
                result = self._ipc.send_action(command, parameters)
                success = result.get("success", False)
                self._agent.on_action_result(action, result)
                floor_metrics.record_action(command, success)

                if success:
                    # Track specific metrics
                    if command == "RECRUIT_HERO":
                        floor_metrics.heroes_recruited += 1
                    elif command == "EQUIP_ITEM":
                        floor_metrics.items_equipped += 1
                    elif command == "BUY_FROM_MERCHANT":
                        floor_metrics.items_bought += 1

                logger.debug(
                    f"Action: {command}({parameters}) -> {'OK' if success else 'FAIL'}: "
                    f"{result.get('error', '')}"
                )

            except (ConnectionError, TimeoutError) as e:
                logger.error(f"IPC error during action: {e}")
                floor_metrics.finish("game_over")
                return floor_metrics

            # Receive next state after action
            # The mod pushes fresh state after every successful action.
            try:
                next_state_dict = self._ipc.receive_state(timeout=5.0)
                current_state = self._parser.parse(next_state_dict)
                floor_metrics.update_from_state(current_state)

                if current_state.turn != last_turn:
                    last_turn = current_state.turn
                    actions_this_turn = 0
                    self._agent.new_turn()

            except TimeoutError:
                # No state received — action may have failed or mod didn't push
                pass

        # If we get here via stop signal
        floor_metrics.finish("aborted")
        return floor_metrics

    def _save_metrics(self) -> None:
        """Save run metrics to the metrics directory."""
        try:
            self._run_metrics.save(self.metrics_dir / f"{self._run_metrics.run_id}.json")
            logger.info(f"Metrics saved to {self.metrics_dir / self._run_metrics.run_id}.json")
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

    def _setup_signal_handlers(self) -> None:
        """Set up graceful shutdown on SIGINT/SIGTERM."""

        def _signal_handler(sig, frame):
            logger.info("Shutdown signal received. Finishing current action...")
            self._running = False

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Run the heuristic AI agent for Dungeon of the ENDLESS"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to guidelines config file (YAML or JSON)",
    )
    parser.add_argument(
        "--continue",
        dest="continue_game",
        action="store_true",
        help="Continue a saved game instead of starting new",
    )
    parser.add_argument(
        "--heroes",
        nargs="+",
        default=None,
        help="Hero config names (e.g., Hero_H0001 Hero_H0003)",
    )
    parser.add_argument(
        "--ship",
        type=str,
        default=DEFAULT_SHIP,
        help="Ship name (default: Pod)",
    )
    parser.add_argument(
        "--difficulty",
        type=str,
        choices=["easy", "normal"],
        default=DEFAULT_DIFFICULTY,
        help="Game difficulty (default: easy)",
    )
    parser.add_argument(
        "--max-floors",
        type=int,
        default=1,
        help="Maximum floors to play (default: 1)",
    )
    parser.add_argument(
        "--metrics-dir",
        type=str,
        default="metrics",
        help="Directory to save metrics (default: metrics/)",
    )
    parser.add_argument(
        "--no-steam",
        action="store_true",
        help="Launch game directly without Steam",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging — both console and file
    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_datefmt = "%H:%M:%S"

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=log_datefmt))
    root_logger.addHandler(console_handler)

    # File handler — writes full debug log next to the script
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "agent_run.log"
    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)  # Always capture full debug in file
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=log_datefmt))
    root_logger.addHandler(file_handler)

    logger.info(f"Logging to file: {log_file}")

    # Load guidelines
    guidelines = None
    if args.config:
        guidelines = GuidelinesConfig.from_file(args.config)
        logger.info(f"Loaded guidelines from {args.config}")

    # Run the agent
    runner = AgentRunner(
        guidelines=guidelines,
        heroes=args.heroes,
        ship=args.ship,
        difficulty=args.difficulty,
        continue_game=args.continue_game,
        max_floors=args.max_floors,
        metrics_dir=args.metrics_dir,
        use_steam=not args.no_steam,
    )

    run_metrics = runner.run()

    # Exit with appropriate code
    if run_metrics.final_outcome == "escaped_all":
        sys.exit(0)
    elif run_metrics.final_outcome == "game_over":
        sys.exit(1)
    else:
        sys.exit(2)


if __name__ == "__main__":
    main()
