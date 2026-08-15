"""
Training entry point for the RL agent.

Handles:
  - Game launch via GameLauncher
  - Episode loop with PPO updates
  - Curriculum stage management
  - Checkpointing and logging
  - Graceful interrupt (save on Ctrl+C)
  - Game crash recovery
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

import torch
import numpy as np

from curriculum import CurriculumManager
from game_launcher import GameLauncher
from networks import PolicyNetwork
from ppo_trainer import PPOTrainer, RolloutBuffer
from rl_agent import RLAgent
from rl_config import RLConfig
from rl_env import RLEnv

logger = logging.getLogger(__name__)


class TrainingRunner:
    """
    Orchestrates the full RL training loop.

    Architecture:
      - Outer loop: episodes (full games)
      - Inner loop: steps (individual actions per state)
      - PPO update every rollout_steps
      - Curriculum advancement based on success rate
    """

    def __init__(self, config: RLConfig, resume_checkpoint: str | None = None, no_launch: bool = False):
        self.config = config
        self.device = "cpu"  # GPU optional, CPU sufficient for this game
        self.no_launch = no_launch

        # Networks
        self.policy_net = PolicyNetwork(config.network).to(self.device)
        self.trainer = PPOTrainer(self.policy_net, config.ppo, self.device)
        self.buffer = RolloutBuffer(config.ppo.rollout_steps, self.device)

        # RL Agent (for inference during rollout collection)
        self.agent = RLAgent(config, device=self.device)

        # Curriculum
        self.curriculum = CurriculumManager(config.curriculum)

        # Metrics
        self.episode_count = 0
        self.total_steps = 0
        self.best_success_rate = 0.0

        # Interrupt handling
        self._interrupted = False
        signal.signal(signal.SIGINT, self._handle_interrupt)

        # Resume from checkpoint
        if resume_checkpoint:
            self._load_training_state(resume_checkpoint)

    def run(self) -> None:
        """Main training loop with automatic game launch and restart."""
        logger.info("Starting RL training")
        logger.info(f"Config: {self.config.training.max_episodes} max episodes")
        logger.info(f"Curriculum stage: {self.curriculum.stage_name}")

        try:
            if self.no_launch:
                logger.info("Skipping game launch (--no-launch). Game must already be in dungeon.")
                # Don't use GameLauncher at all — RLEnv will connect directly
                launcher = None
            else:
                logger.info("Launching game and connecting...")
                launcher = GameLauncher(
                    host="127.0.0.1",
                    state_port=5555,
                    action_port=5556,
                    use_steam=True,
                )
                launcher.launch_and_connect()

                # Start first game
                logger.info("Starting new game...")
                launcher.start_new_game(
                    heroes=self.config.training.default_heroes,
                    ship=self.config.training.ship,
                    difficulty=self.config.training.difficulty,
                )
                launcher.wait_for_dungeon()
                # Disconnect launcher — RLEnv will take over the ports
                launcher.disconnect()

            env = RLEnv(config=self.config)

            while self.episode_count < self.config.training.max_episodes:
                if self._interrupted:
                    logger.info("Training interrupted by user")
                    break

                # Run one episode (with crash recovery)
                try:
                    episode_reward, episode_steps, success = self._run_episode(env)
                except (ConnectionError, OSError, TimeoutError) as e:
                    logger.warning(f"Episode failed (connection lost): {e}")
                    logger.info("Attempting recovery: disconnect, wait, reconnect...")
                    # Save progress before recovery attempt
                    self._save_checkpoint(f"recovery_{self.episode_count}")
                    # Disconnect and wait for game to stabilize
                    try:
                        env.close()
                    except Exception:
                        pass
                    env._connected = False
                    time.sleep(10.0)
                    # Reconnect
                    try:
                        env._ipc.connect()
                        env._connected = True
                        logger.info("Reconnected successfully. Restarting game...")
                        self._restart_game(env)
                        continue  # Retry the episode
                    except Exception as e2:
                        logger.error(f"Recovery failed: {e2}. Stopping training.")
                        break

                self.episode_count += 1

                # Record for curriculum
                advanced = self.curriculum.record_episode(success)
                if advanced:
                    logger.info(f"Curriculum advanced to: {self.curriculum.stage_name}")

                # PPO update when buffer is full
                if self.buffer.size >= self.config.ppo.rollout_steps:
                    self._ppo_update(env)

                # Log every episode
                self._log_metrics(episode_reward, episode_steps, success)

                # Checkpointing
                if self.episode_count % self.config.training.checkpoint_interval == 0:
                    self._save_checkpoint()

                # Track best
                if self.curriculum.success_rate > self.best_success_rate:
                    self.best_success_rate = self.curriculum.success_rate
                    self._save_checkpoint("best")

                # Restart game for next episode
                if self.episode_count < self.config.training.max_episodes and not self._interrupted:
                    self._restart_game(env)

        except Exception as e:
            logger.error(f"Training error: {e}", exc_info=True)
        finally:
            self._save_checkpoint("final")
            if launcher:
                launcher.disconnect()
            logger.info(f"Training complete. Episodes: {self.episode_count}, Steps: {self.total_steps}")

    def _run_episode(self, env: RLEnv) -> tuple[float, int, bool]:
        """
        Run a single episode (one full game or until max_floors).

        Returns:
            (total_reward, steps, success)
        """
        obs, info = env.reset()
        episode_reward = 0.0
        steps = 0
        done = False
        step_times = []  # For latency measurement
        steps_since_progress = 0  # Reset on turn change (door open)

        while not done:
            t_start = time.time()

            # Convert obs to tensors
            obs_tensor = {k: torch.tensor(v, device=self.device).unsqueeze(0) for k, v in obs.items()}
            mask_tensor = obs_tensor["action_mask"]

            # Get action from policy
            t_think_start = time.time()
            with torch.no_grad():
                action_dict, log_prob, value = self.policy_net.act(
                    obs_tensor, mask_tensor, deterministic=False
                )
            t_think = time.time() - t_think_start

            # Convert action to env format
            action = {k: v.item() for k, v in action_dict.items()}

            # Log what the agent chose
            from action_masking import StrategicOption, NUM_OPTIONS
            mask_np = obs["action_mask"] if isinstance(obs["action_mask"], np.ndarray) else obs["action_mask"].numpy()
            valid_options = [StrategicOption(i).name for i in range(NUM_OPTIONS) if mask_np[i]]
            chosen = StrategicOption(action["option"])

            # Step environment (includes send action + receive state)
            t_env_start = time.time()
            next_obs, reward, terminated, truncated, info = env.step(action)
            t_env = time.time() - t_env_start
            done = terminated or truncated

            t_total = time.time() - t_start
            step_times.append({"think": t_think, "env": t_env, "total": t_total})

            logger.info(
                f"Step {steps}: {chosen.name} | "
                f"sent={info.get('action_sent', {})} | "
                f"think={t_think*1000:.1f}ms env={t_env*1000:.1f}ms total={t_total*1000:.1f}ms | "
                f"reward={reward:.2f} | valid: [{', '.join(valid_options)}]"
            )

            # Store transition
            self.buffer.add(obs_tensor, action_dict, log_prob, value, reward, done)
            self.total_steps += 1

            episode_reward += reward
            steps += 1
            obs = next_obs

            # Check floor limit from curriculum
            if info.get("floor", 1) > self.curriculum.max_floors:
                done = True

            # Track progress — reset on turn change (door open advances turn)
            curr_turn = info.get("turn", 0)
            if not hasattr(self, '_last_turn'):
                self._last_turn = curr_turn
            if curr_turn > self._last_turn:
                steps_since_progress = 0
                self._last_turn = curr_turn
            else:
                steps_since_progress += 1

            # Force-terminate if agent is stalling (no door opened in 250 steps)
            if steps_since_progress > 250:
                logger.warning(f"Episode force-terminated: no progress in 250 steps (total steps: {steps})")
                # Lump penalty for stalling
                reward -= 50.0
                episode_reward -= 50.0
                done = True

        # Log latency summary
        if step_times:
            avg_think = np.mean([s["think"] for s in step_times]) * 1000
            avg_env = np.mean([s["env"] for s in step_times]) * 1000
            avg_total = np.mean([s["total"] for s in step_times]) * 1000
            logger.info(
                f"Episode latency: avg_think={avg_think:.1f}ms avg_env={avg_env:.1f}ms "
                f"avg_total={avg_total:.1f}ms over {len(step_times)} steps"
            )

        # Success = escaped (not game over)
        success = not (info.get("crystal_state") == "Unplugged" or terminated)
        return episode_reward, steps, success

    def _restart_game(self, env: RLEnv) -> None:
        """
        Restart the game for the next episode.

        Sequence:
          1. Wait for game-over screen
          2. Send RETURN_TO_MENU
          3. Wait for main menu
          4. Start new game
          5. Wait for dungeon to load
        """
        logger.info("Restarting game for next episode...")
        try:
            # Wait for game-over screen to appear
            time.sleep(5.0)

            # Disconnect and reconnect IPC (game tears down sockets during scene transition)
            try:
                env._ipc.disconnect()
            except Exception:
                pass
            time.sleep(2.0)
            env._ipc.connect()
            env._connected = True

            # Return to menu
            result = env._ipc.send_action("RETURN_TO_MENU", {})
            if not result.get("success"):
                logger.warning(f"RETURN_TO_MENU failed: {result.get('error')}, retrying...")
                time.sleep(5.0)
                result = env._ipc.send_action("RETURN_TO_MENU", {})

            # Drain any pending state messages
            time.sleep(3.0)
            try:
                while True:
                    env._ipc.receive_state(timeout=1.0)
            except Exception:
                pass

            # Wait for menu to be ready
            time.sleep(5.0)

            # Start new game
            heroes = self.config.training.default_heroes
            if self.curriculum.randomize_heroes:
                # TODO: randomize from available heroes
                pass

            env._ipc.send_action("START_NEW_GAME", {
                "hero_names": heroes,
                "ship_name": self.config.training.ship,
                "difficulty": self.config.training.difficulty,
            })

            # Wait for dungeon to load
            time.sleep(5.0)
            logger.info("New game started, waiting for dungeon...")

        except Exception as e:
            logger.error(f"Error restarting game: {e}")
            # Try to recover by reconnecting
            time.sleep(5.0)

    def _ppo_update(self, env: RLEnv) -> None:
        """Perform a PPO update using the filled buffer."""
        # Bootstrap value for last state
        last_value = 0.0
        if env._current_state and not env._current_state.is_game_over:
            obs_tensor = {
                k: torch.tensor(v, device=self.device).unsqueeze(0)
                for k, v in env._build_observation(env._current_state).items()
            }
            with torch.no_grad():
                embedding = self.policy_net.encode(obs_tensor)
                last_value = self.policy_net.get_value(embedding).item()

        # Compute advantages
        self.buffer.compute_advantages(
            last_value,
            gamma=self.config.ppo.gamma,
            gae_lambda=self.config.ppo.gae_lambda,
        )

        # PPO update
        metrics = self.trainer.update(self.buffer)
        self.buffer.reset()

        logger.info(
            f"=== PPO UPDATE === {self.buffer.capacity} steps | "
            f"policy_loss={metrics['policy_loss']:.4f} | "
            f"value_loss={metrics['value_loss']:.4f} | "
            f"entropy={metrics['entropy']:.4f} | "
            f"clip_frac={metrics['clip_fraction']:.3f} | "
            f"updates={metrics['num_updates']}"
        )

    def _log_metrics(self, episode_reward: float, steps: int, success: bool) -> None:
        """Log training metrics."""
        logger.info(
            f"Episode {self.episode_count} | "
            f"Reward: {episode_reward:.1f} | Steps: {steps} | "
            f"Success: {success} | "
            f"Success Rate: {self.curriculum.success_rate:.2%} | "
            f"Stage: {self.curriculum.stage_name} | "
            f"Total Steps: {self.total_steps}"
        )

    def _save_checkpoint(self, suffix: str = "") -> None:
        """Save training state."""
        dir_path = Path(self.config.training.checkpoint_dir)
        dir_path.mkdir(parents=True, exist_ok=True)

        name = f"checkpoint_{self.episode_count}" if not suffix else f"checkpoint_{suffix}"
        path = dir_path / f"{name}.pt"

        torch.save({
            "policy_net": self.policy_net.state_dict(),
            "optimizer": self.trainer.optimizer.state_dict(),
            "episode_count": self.episode_count,
            "total_steps": self.total_steps,
            "curriculum_stage": self.curriculum.stage_index,
            "best_success_rate": self.best_success_rate,
        }, path)
        logger.info(f"Checkpoint saved: {path}")

    def _load_training_state(self, path: str) -> None:
        """Resume training from a checkpoint."""
        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        self.policy_net.load_state_dict(checkpoint["policy_net"])
        self.trainer.optimizer.load_state_dict(checkpoint["optimizer"])
        self.episode_count = checkpoint.get("episode_count", 0)
        self.total_steps = checkpoint.get("total_steps", 0)
        self.best_success_rate = checkpoint.get("best_success_rate", 0.0)
        stage = checkpoint.get("curriculum_stage", 0)
        self.curriculum.force_stage(stage)
        logger.info(f"Resumed from checkpoint: {path} (episode {self.episode_count})")

    def _handle_interrupt(self, signum, frame) -> None:
        """Handle Ctrl+C gracefully."""
        if self._interrupted:
            # Second interrupt = force exit
            sys.exit(1)
        self._interrupted = True
        logger.info("Interrupt received. Finishing current episode and saving...")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Train RL agent for Dungeon of the ENDLESS")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config file")
    parser.add_argument("--resume", type=str, default=None, help="Path to checkpoint to resume from")
    parser.add_argument("--episodes", type=int, default=None, help="Override max episodes")
    parser.add_argument("--stage", type=int, default=None, help="Force curriculum stage")
    parser.add_argument("--no-launch", action="store_true", help="Skip game launch (game already running)")
    args = parser.parse_args()

    # Setup logging
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "rl_training.log", mode="w"),
        ],
    )

    # Load config
    if args.config:
        config = RLConfig.from_file(args.config)
    else:
        config = RLConfig()

    if args.episodes:
        config.training.max_episodes = args.episodes

    # Run training
    runner = TrainingRunner(config, resume_checkpoint=args.resume, no_launch=args.no_launch)
    if args.stage is not None:
        runner.curriculum.force_stage(args.stage)

    runner.run()


if __name__ == "__main__":
    main()
