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

    def __init__(self, config: RLConfig, resume_checkpoint: str | None = None):
        self.config = config
        self.device = "cpu"  # GPU optional, CPU sufficient for this game

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
        """Main training loop."""
        logger.info("Starting RL training")
        logger.info(f"Config: {self.config.training.max_episodes} max episodes")
        logger.info(f"Curriculum stage: {self.curriculum.stage_name}")

        try:
            env = RLEnv(config=self.config)

            while self.episode_count < self.config.training.max_episodes:
                if self._interrupted:
                    logger.info("Training interrupted by user")
                    break

                # Run one episode
                episode_reward, episode_steps, success = self._run_episode(env)
                self.episode_count += 1

                # Record for curriculum
                advanced = self.curriculum.record_episode(success)
                if advanced:
                    logger.info(f"Curriculum advanced to: {self.curriculum.stage_name}")

                # PPO update when buffer is full
                if self.buffer.size >= self.config.ppo.rollout_steps:
                    self._ppo_update(env)

                # Logging
                if self.episode_count % self.config.training.log_interval == 0:
                    self._log_metrics(episode_reward, episode_steps, success)

                # Checkpointing
                if self.episode_count % self.config.training.checkpoint_interval == 0:
                    self._save_checkpoint()

                # Track best
                if self.curriculum.success_rate > self.best_success_rate:
                    self.best_success_rate = self.curriculum.success_rate
                    self._save_checkpoint("best")

        except Exception as e:
            logger.error(f"Training error: {e}", exc_info=True)
        finally:
            self._save_checkpoint("final")
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

        while not done:
            # Convert obs to tensors
            obs_tensor = {k: torch.tensor(v, device=self.device).unsqueeze(0) for k, v in obs.items()}
            mask_tensor = obs_tensor["action_mask"]

            # Get action from policy
            with torch.no_grad():
                action_dict, log_prob, value = self.policy_net.act(
                    obs_tensor, mask_tensor, deterministic=False
                )

            # Convert action to env format
            action = {k: v.item() for k, v in action_dict.items()}

            # Log what the agent chose
            from action_masking import StrategicOption, NUM_OPTIONS
            mask_np = obs["action_mask"] if isinstance(obs["action_mask"], np.ndarray) else obs["action_mask"].numpy()
            valid_options = [StrategicOption(i).name for i in range(NUM_OPTIONS) if mask_np[i]]
            chosen = StrategicOption(action["option"])
            logger.info(
                f"Step {steps}: chose {chosen.name} | room={action['room_target']} "
                f"hero={action['hero_target']} entity={action['entity_target']} | "
                f"valid: [{', '.join(valid_options)}]"
            )

            # Step environment
            next_obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated

            # Store transition
            self.buffer.add(obs_tensor, action_dict, log_prob, value, reward, done)
            self.total_steps += 1

            episode_reward += reward
            steps += 1
            obs = next_obs

            # Check floor limit from curriculum
            if info.get("floor", 1) > self.curriculum.max_floors:
                done = True

        # Success = escaped (not game over)
        success = not (info.get("crystal_state") == "Unplugged" or terminated)
        return episode_reward, steps, success

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

        logger.debug(
            f"PPO update: policy_loss={metrics['policy_loss']:.4f}, "
            f"value_loss={metrics['value_loss']:.4f}, "
            f"entropy={metrics['entropy']:.4f}"
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
    args = parser.parse_args()

    # Setup logging
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "rl_training.log", mode="a"),
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
    runner = TrainingRunner(config, resume_checkpoint=args.resume)
    if args.stage is not None:
        runner.curriculum.force_stage(args.stage)

    runner.run()


if __name__ == "__main__":
    main()
