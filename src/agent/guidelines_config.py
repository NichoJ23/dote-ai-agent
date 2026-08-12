"""
GuidelinesConfig: Externalized heuristic rules for the AI agent.

These guidelines (GL-1 through GL-8) constrain the heuristic agent during early
development. They can be toggled on/off via a YAML or JSON config file, allowing
easy experimentation without code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class GuidelinesConfig:
    """
    Removable learning guidelines for the heuristic agent.

    Each field corresponds to a guideline from the requirements doc.
    Set to False/None to disable a specific guideline.
    """

    # GL-1: Retreat any hero below this HP% toward crystal room
    retreat_enabled: bool = True
    retreat_hp_threshold: float = 0.30

    # GL-2: Preferred starting hero pair
    preferred_starting_heroes: list[str] = field(
        default_factory=lambda: ["Hero_H0001", "Hero_H0003"]  # Max O'Kane, Gork
    )

    # GL-3: Protect operators — avoid moving heroes operating modules
    protect_operators: bool = True

    # GL-4: Prioritize upgrading Max until Operate is unlocked
    prioritize_max_operate_unlock: bool = True

    # GL-5: Fastest hero carries crystal during escape
    fastest_hero_carries_crystal: bool = True

    # GL-6: Reorganize power for escape path
    repower_escape_path: bool = True

    # GL-7: Don't research if artifact mobs detected and artifact undefended
    gate_research_on_artifact_safety: bool = True

    # GL-8: Move valuable items to backpack before escape
    pre_escape_inventory_management: bool = True

    @classmethod
    def from_file(cls, path: str | Path) -> "GuidelinesConfig":
        """
        Load guidelines from a YAML or JSON config file.

        Supports both .yaml/.yml and .json extensions.
        Unknown keys are silently ignored.
        Missing keys use defaults.

        Args:
            path: Path to the config file.

        Returns:
            GuidelinesConfig with values from file merged over defaults.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Guidelines config not found: {path}")

        text = path.read_text(encoding="utf-8")

        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(text) or {}
        elif path.suffix == ".json":
            data = json.loads(text)
        else:
            # Try YAML first, fall back to JSON
            try:
                data = yaml.safe_load(text) or {}
            except yaml.YAMLError:
                data = json.loads(text)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "GuidelinesConfig":
        """
        Create config from a dict, ignoring unknown keys.

        Args:
            data: Dict of config values (partial is fine).

        Returns:
            GuidelinesConfig with provided values merged over defaults.
        """
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    @classmethod
    def disabled(cls) -> "GuidelinesConfig":
        """
        Create a config with all guidelines disabled.
        Useful for testing agent behavior without constraints.
        """
        return cls(
            retreat_enabled=False,
            retreat_hp_threshold=0.0,
            preferred_starting_heroes=[],
            protect_operators=False,
            prioritize_max_operate_unlock=False,
            fastest_hero_carries_crystal=False,
            repower_escape_path=False,
            gate_research_on_artifact_safety=False,
            pre_escape_inventory_management=False,
        )

    def to_dict(self) -> dict:
        """Serialize to a dict (for saving or inspection)."""
        from dataclasses import asdict
        return asdict(self)
