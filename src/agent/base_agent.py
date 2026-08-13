"""
BaseAgent: Abstract base class for all AI agent controllers.

Defines the interface that any agent (heuristic, RL, hybrid) must implement.
Integrates GuidelinesConfig for configurable heuristic rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from guidelines_config import GuidelinesConfig
from state_parser import GameStatePayload


class BaseAgent(ABC):
    """
    Abstract base for all agent controllers.

    Subclasses implement select_action() to produce ActionCommand dicts
    that can be sent directly via IpcClient.send_action().

    Attributes:
        guidelines: GuidelinesConfig with toggleable heuristic rules.
    """

    def __init__(self, guidelines: Optional[GuidelinesConfig] = None):
        """
        Args:
            guidelines: GuidelinesConfig instance. Uses defaults if None.
        """
        self.guidelines = guidelines or GuidelinesConfig()

    @abstractmethod
    def select_action(self, state: GameStatePayload) -> Optional[dict]:
        """
        Given the current game state, return an action command dict.

        The returned dict should have:
            {"command": "MOVE_HERO", "parameters": {"hero_name": ..., "target_room_index": ...}}

        Or None if no action should be taken this tick.

        Args:
            state: Parsed GameStatePayload from StateParser.

        Returns:
            Action command dict ready for IpcClient.send_action(), or None.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """
        Reset internal state for a new episode/floor.

        Called when a new game starts or a new floor begins.
        """
        ...

    def on_action_result(self, command: dict, result: dict) -> None:
        """
        Callback after an action result is received from the game.

        Override in subclasses to update internal tracking based on
        whether actions succeeded or failed.

        Args:
            command: The action command that was sent.
            result: The ActionResult dict from the mod (has 'success', 'error', 'metadata').
        """
        pass

    def on_floor_complete(self, escaped: bool) -> None:
        """
        Callback when a floor ends (escaped successfully or game over).

        Args:
            escaped: True if the floor was escaped, False if crystal was destroyed.
        """
        pass
