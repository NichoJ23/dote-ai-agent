"""
Evaluation script for the RL agent.

Loads a trained checkpoint and runs the agent with greedy (deterministic)
action selection. Records full game metrics.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from rl_agent import RLAgent
from rl_config import RLConfig

logger = logging.getLogger(__name__)


def evaluate(
    config: RLConfig,
    checkpoint_path: str,
    num_games: int = 5,
    output_dir: str = "metrics/rl_eval",
) -> dict:
    """
    Run evaluation games with a trained agent.

    Args:
        config: RL configuration.
        checkpoint_path: Path to trained checkpoint.
        num_games: Number of games to play.
        output_dir: Directory to save results.

    Returns:
        Summary metrics dict.
    """
    from game_launcher import GameLauncher
    from ipc_client import IpcClient
    from state_parser import StateParser

    agent = RLAgent(config, checkpoint_path=checkpoint_path, deterministic=True)
    parser = StateParser()

    results = []

    for game_num in range(num_games):
        logger.info(f"Evaluation game {game_num + 1}/{num_games}")

        # Connect to game
        ipc = IpcClient()
        ipc.connect()

        game_metrics = {
            "game_number": game_num + 1,
            "floors_reached": 0,
            "total_turns": 0,
            "heroes_alive_at_end": 0,
            "total_rewards": 0.0,
            "actions_taken": 0,
            "invalid_actions": 0,
            "outcome": "unknown",
            "floor_details": [],
        }

        try:
            # Start game
            ipc.send_action("START_NEW_GAME", {
                "hero_names": config.training.default_heroes,
                "ship_name": config.training.ship,
                "difficulty": config.training.difficulty,
            })

            # Wait for dungeon
            time.sleep(5)
            agent.reset()

            floor_start_turn = 0
            current_floor = 1

            while True:
                # Receive state
                try:
                    raw_state = ipc.receive_state(timeout=30.0)
                except Exception:
                    logger.warning("Timeout waiting for state")
                    break

                state = parser.parse(raw_state)

                # Track floor transitions
                if state.floor > current_floor:
                    game_metrics["floor_details"].append({
                        "floor": current_floor,
                        "turns": state.turn - floor_start_turn,
                    })
                    current_floor = state.floor
                    floor_start_turn = state.turn
                    agent.reset()

                # Check game over
                if state.is_game_over:
                    game_metrics["outcome"] = "game_over"
                    break

                if state.is_escaping:
                    game_metrics["outcome"] = "escaped"

                # Check if we've won (floor 12 escaped)
                if state.floor > 12:
                    game_metrics["outcome"] = "victory"
                    break

                # Get action from agent
                action = agent.select_action(state)
                if action is None:
                    continue

                # Send action
                result = ipc.send_action(action["command"], action["parameters"])
                agent.on_action_result(action, result)

                game_metrics["actions_taken"] += 1
                if not result.get("success", False):
                    game_metrics["invalid_actions"] += 1

                game_metrics["total_turns"] = state.turn

        except Exception as e:
            logger.error(f"Error in eval game {game_num + 1}: {e}")
            game_metrics["outcome"] = "error"
        finally:
            game_metrics["floors_reached"] = current_floor
            game_metrics["heroes_alive_at_end"] = len(state.heroes) if state else 0
            results.append(game_metrics)
            try:
                ipc.disconnect()
            except Exception:
                pass

    # Compute summary
    summary = {
        "num_games": num_games,
        "wins": sum(1 for r in results if r["outcome"] == "victory"),
        "escapes": sum(1 for r in results if r["outcome"] in ("escaped", "victory")),
        "game_overs": sum(1 for r in results if r["outcome"] == "game_over"),
        "avg_floors_reached": sum(r["floors_reached"] for r in results) / max(len(results), 1),
        "avg_turns": sum(r["total_turns"] for r in results) / max(len(results), 1),
        "avg_actions": sum(r["actions_taken"] for r in results) / max(len(results), 1),
        "avg_invalid_rate": (
            sum(r["invalid_actions"] / max(r["actions_taken"], 1) for r in results)
            / max(len(results), 1)
        ),
        "games": results,
    }

    # Save results
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    result_file = out_path / f"eval_{int(time.time())}.json"
    result_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info(f"Evaluation results saved: {result_file}")
    logger.info(
        f"Summary: {summary['wins']}/{num_games} wins, "
        f"avg floors: {summary['avg_floors_reached']:.1f}, "
        f"invalid rate: {summary['avg_invalid_rate']:.1%}"
    )

    return summary


def main():
    parser = argparse.ArgumentParser(description="Evaluate trained RL agent")
    parser.add_argument("checkpoint", type=str, help="Path to checkpoint file")
    parser.add_argument("--config", type=str, default=None, help="Path to config YAML")
    parser.add_argument("--games", type=int, default=5, help="Number of games to play")
    parser.add_argument("--output", type=str, default="metrics/rl_eval", help="Output directory")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = RLConfig.from_file(args.config) if args.config else RLConfig()
    evaluate(config, args.checkpoint, num_games=args.games, output_dir=args.output)


if __name__ == "__main__":
    main()
