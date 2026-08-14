"""
Multi-environment training: runs N game instances in parallel for faster data collection.

Each game instance uses a unique port pair (state_port, action_port) configured via
its own dote_training.cfg file. The trainer collects rollouts from all environments
round-robin and does PPO updates on the combined buffer.

Usage:
    python train_multi_env.py --num-envs 4 --episodes 100
    python train_multi_env.py --num-envs 2 --no-launch  # games already running on ports

Port assignment:
    Env 0: state=5555, action=5556  (default)
    Env 1: state=5557, action=5558
    Env 2: state=5559, action=5560
    ...
"""

from __future__ import annotations

import argparse
import logging
import shutil
import signal
import sys
import time
from pathlib import Path

import numpy as np
import torch

from action_masking import StrategicOption, NUM_OPTIONS
from curriculum import CurriculumManager
from game_launcher import GameLauncher
from networks import PolicyNetwork
from ppo_trainer import PPOTrainer, RolloutBuffer
from rl_config import RLConfig
from rl_env import RLEnv
from state_parser import StateParser

logger = logging.getLogger(__name__)

BASE_STATE_PORT = 5555
BASE_ACTION_PORT = 5556


class MultiEnvTrainer:
    """
    Manages N parallel game instances for PPO training.

    Architecture:
    - N game processes, each with unique port pair
    - N RLEnv instances connected to their respective game
    - Single PolicyNetwork shared across all envs
    - Round-robin rollout collection (step each env in turn)
    - Combined rollout buffer → PPO update
    """

    def __init__(
        self,
        config: RLConfig,
        num_envs: int = 4,
        no_launch: bool = False,
        resume_checkpoint: str | None = None,
    ):
        self.config = config
        self.num_envs = num_envs
        self.no_launch = no_launch
        self.device = "cpu"

        # Networks
        self.policy_net = PolicyNetwork(config.network).to(self.device)
        self.trainer = PPOTrainer(self.policy_net, config.ppo, self.device)
        self.buffer = RolloutBuffer(config.ppo.rollout_steps, self.device)

        # Curriculum
        self.curriculum = CurriculumManager(config.curriculum)

        # Environments (created in run())
        self.envs: list[RLEnv] = []

        # Metrics
        self.episode_count = 0
        self.total_steps = 0
        self.best_success_rate = 0.0

        # Interrupt handling
        self._interrupted = False
        signal.signal(signal.SIGINT, self._handle_interrupt)

        # Resume
        if resume_checkpoint:
            self._load_training_state(resume_checkpoint)

    def get_port_pair(self, env_index: int) -> tuple[int, int]:
        """Get (state_port, action_port) for a given environment index."""
        state_port = BASE_STATE_PORT + (env_index * 2)
        action_port = BASE_ACTION_PORT + (env_index * 2)
        return state_port, action_port

    def run(self) -> None:
        """Main multi-env training loop."""
        logger.info(f"Starting multi-env training with {self.num_envs} environments")
        logger.info(f"Port assignments:")
        for i in range(self.num_envs):
            sp, ap = self.get_port_pair(i)
            logger.info(f"  Env {i}: state={sp}, action={ap}")

        try:
            # Launch games (if needed) and create environments
            self._setup_environments()

            logger.info(f"All {len(self.envs)} environments ready. Starting training...")

            # Track per-env episode state
            env_obs = [None] * self.num_envs
            env_done = [True] * self.num_envs  # Start as done to trigger reset
            env_episode_rewards = [0.0] * self.num_envs
            env_episode_steps = [0] * self.num_envs

            while self.episode_count < self.config.training.max_episodes:
                if self._interrupted:
                    logger.info("Training interrupted")
                    break

                # Step each environment
                for i in range(self.num_envs):
                    if env_done[i]:
                        # Reset this env for new episode
                        try:
                            obs, info = self.envs[i].reset()
                            env_obs[i] = obs
                            env_done[i] = False
                            env_episode_rewards[i] = 0.0
                            env_episode_steps[i] = 0
                        except Exception as e:
                            logger.warning(f"Env {i} reset failed: {e}")
                            continue

                    if env_obs[i] is None:
                        continue

                    # Get action from policy
                    obs_tensor = {
                        k: torch.tensor(v, device=self.device).unsqueeze(0)
                        for k, v in env_obs[i].items()
                    }
                    mask_tensor = obs_tensor["action_mask"]

                    with torch.no_grad():
                        action_dict, log_prob, value = self.policy_net.act(
                            obs_tensor, mask_tensor, deterministic=False
                        )

                    action = {k: v.item() for k, v in action_dict.items()}

                    # Step environment
                    try:
                        next_obs, reward, terminated, truncated, info = self.envs[i].step(action)
                        done = terminated or truncated
                    except Exception as e:
                        logger.warning(f"Env {i} step failed: {e}")
                        env_done[i] = True
                        self.episode_count += 1
                        self.curriculum.record_episode(False)
                        continue

                    # Store transition
                    self.buffer.add(obs_tensor, action_dict, log_prob, value, reward, done)
                    self.total_steps += 1

                    env_episode_rewards[i] += reward
                    env_episode_steps[i] += 1
                    env_obs[i] = next_obs

                    # Check floor limit
                    if info.get("floor", 1) > self.curriculum.max_floors:
                        done = True

                    if done:
                        env_done[i] = True
                        self.episode_count += 1
                        success = not terminated  # terminated = game over
                        self.curriculum.record_episode(success)

                        if self.episode_count % self.config.training.log_interval == 0:
                            logger.info(
                                f"Episode {self.episode_count} (env {i}) | "
                                f"Reward: {env_episode_rewards[i]:.1f} | "
                                f"Steps: {env_episode_steps[i]} | "
                                f"Success: {success} | "
                                f"Rate: {self.curriculum.success_rate:.2%} | "
                                f"Stage: {self.curriculum.stage_name}"
                            )

                        # Restart game for this env
                        self._restart_env(i)

                # PPO update when buffer is full
                if self.buffer.size >= self.config.ppo.rollout_steps:
                    self._ppo_update()

                # Checkpointing
                if self.episode_count > 0 and self.episode_count % self.config.training.checkpoint_interval == 0:
                    self._save_checkpoint()

                if self.curriculum.success_rate > self.best_success_rate:
                    self.best_success_rate = self.curriculum.success_rate
                    self._save_checkpoint("best")

        except Exception as e:
            logger.error(f"Training error: {e}", exc_info=True)
        finally:
            self._save_checkpoint("final")
            for env in self.envs:
                try:
                    env.close()
                except Exception:
                    pass
            logger.info(
                f"Training complete. Episodes: {self.episode_count}, "
                f"Steps: {self.total_steps}, Envs: {self.num_envs}"
            )

    def _setup_environments(self) -> None:
        """Launch game instances and create RLEnv connections."""
        for i in range(self.num_envs):
            state_port, action_port = self.get_port_pair(i)

            if not self.no_launch and i > 0:
                # For env 0, game may already be running with default ports
                # For envs 1+, we need to set up config files with custom ports
                self._create_game_config(i, state_port, action_port)
                # Launch the game instance
                logger.info(f"Launching game instance {i} (ports {state_port}/{action_port})...")
                launcher = GameLauncher(
                    state_port=state_port,
                    action_port=action_port,
                    use_steam=False,  # Can't launch multiple via Steam
                )
                launcher.launch_and_connect()
                launcher.start_new_game(
                    heroes=self.config.training.default_heroes,
                    ship=self.config.training.ship,
                    difficulty=self.config.training.difficulty,
                )
                launcher.wait_for_dungeon()
                launcher.disconnect()
                time.sleep(2.0)

            # Create the RLEnv for this instance
            env = RLEnv(
                state_port=state_port,
                action_port=action_port,
                config=self.config,
            )
            self.envs.append(env)
            logger.info(f"Env {i} created (ports {state_port}/{action_port})")

    def _create_game_config(self, env_index: int, state_port: int, action_port: int) -> None:
        """
        Create a dote_training.cfg for a specific game instance with custom ports.

        Note: This requires each game instance to have its own BepInEx/plugins/ directory
        pointing to a unique config. For now, this creates the config file — the user
        needs to set up multiple game install directories or a symlink structure.
        """
        # Write config to a temp location — user copies to appropriate game dir
        config_dir = Path(__file__).parent / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"dote_training_env{env_index}.cfg"

        config_content = (
            f"# DotE Agent Training Config - Env {env_index}\n"
            f"training_mode=true\n"
            f"time_scale={int(self.curriculum.time_scale)}\n"
            f"resolution_width=640\n"
            f"resolution_height=480\n"
            f"state_port={state_port}\n"
            f"action_port={action_port}\n"
        )
        config_path.write_text(config_content)
        logger.info(f"Config written: {config_path}")

    def _restart_env(self, env_index: int) -> None:
        """Restart the game for a specific environment."""
        try:
            env = self.envs[env_index]
            time.sleep(2.0)
            env._ipc.send_action("RETURN_TO_MENU", {})
            time.sleep(3.0)
            # Drain state
            try:
                while True:
                    env._ipc.receive_state(timeout=1.0)
            except Exception:
                pass
            time.sleep(3.0)
            env._ipc.send_action("START_NEW_GAME", {
                "hero_names": self.config.training.default_heroes,
                "ship_name": self.config.training.ship,
                "difficulty": self.config.training.difficulty,
            })
            time.sleep(3.0)
        except Exception as e:
            logger.warning(f"Env {env_index} restart failed: {e}")

    def _ppo_update(self) -> None:
        """PPO update from the shared buffer."""
        # Use last value = 0 (simplification for multi-env)
        self.buffer.compute_advantages(
            last_value=0.0,
            gamma=self.config.ppo.gamma,
            gae_lambda=self.config.ppo.gae_lambda,
        )
        metrics = self.trainer.update(self.buffer)
        self.buffer.reset()
        logger.debug(
            f"PPO update: policy_loss={metrics['policy_loss']:.4f}, "
            f"value_loss={metrics['value_loss']:.4f}, "
            f"entropy={metrics['entropy']:.4f}"
        )

    def _save_checkpoint(self, suffix: str = "") -> None:
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
        checkpoint = torch.load(path, map_location=self.device, weights_only=False)
        self.policy_net.load_state_dict(checkpoint["policy_net"])
        self.trainer.optimizer.load_state_dict(checkpoint["optimizer"])
        self.episode_count = checkpoint.get("episode_count", 0)
        self.total_steps = checkpoint.get("total_steps", 0)
        self.best_success_rate = checkpoint.get("best_success_rate", 0.0)
        self.curriculum.force_stage(checkpoint.get("curriculum_stage", 0))
        logger.info(f"Resumed from: {path}")

    def _handle_interrupt(self, signum, frame) -> None:
        if self._interrupted:
            sys.exit(1)
        self._interrupted = True
        logger.info("Interrupt received. Saving and stopping...")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Multi-env RL training for Dungeon of the ENDLESS")
    parser.add_argument("--num-envs", type=int, default=2, help="Number of parallel game instances")
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config file")
    parser.add_argument("--resume", type=str, default=None, help="Checkpoint to resume from")
    parser.add_argument("--episodes", type=int, default=None, help="Override max episodes")
    parser.add_argument("--stage", type=int, default=None, help="Force curriculum stage")
    parser.add_argument("--no-launch", action="store_true", help="Games already running on expected ports")
    parser.add_argument("--game-dir", type=str, default=None,
                        help="Base dir with instance_0/, instance_1/, etc. (from setup_multi_env.py)")
    args = parser.parse_args()

    # Setup logging
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "rl_multi_env.log", mode="w"),
        ],
    )

    # Load config
    config = RLConfig.from_file(args.config) if args.config else RLConfig()
    if args.episodes:
        config.training.max_episodes = args.episodes

    # Run
    trainer = MultiEnvTrainer(
        config,
        num_envs=args.num_envs,
        no_launch=args.no_launch,
        resume_checkpoint=args.resume,
    )
    if args.stage is not None:
        trainer.curriculum.force_stage(args.stage)

    trainer.run()


if __name__ == "__main__":
    main()
