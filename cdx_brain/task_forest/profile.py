"""User profile for collaboration preferences."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class UserProfile:
    tech_stack_preferences: list[str] = field(default_factory=list)
    architecture_style: str = ""
    decision_patterns: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    communication_style: str = ""
    risk_boundary: str = "balance"
    timezone: str = "Asia/Shanghai"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "tech_stack_preferences": self.tech_stack_preferences,
            "architecture_style": self.architecture_style,
            "decision_patterns": self.decision_patterns,
            "anti_patterns": self.anti_patterns,
            "communication_style": self.communication_style,
            "risk_boundary": self.risk_boundary,
            "timezone": self.timezone,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> UserProfile:
        return cls(
            tech_stack_preferences=d.get("tech_stack_preferences", []),
            architecture_style=d.get("architecture_style", ""),
            decision_patterns=d.get("decision_patterns", []),
            anti_patterns=d.get("anti_patterns", []),
            communication_style=d.get("communication_style", ""),
            risk_boundary=d.get("risk_boundary", "balance"),
            timezone=d.get("timezone", "Asia/Shanghai"),
            notes=d.get("notes", ""),
        )


_PROFILE_PATH = Path.home() / ".cdx-brain" / "data" / "user_profile.json"


def load_profile() -> UserProfile:
    if _PROFILE_PATH.is_file():
        try:
            return UserProfile.from_dict(json.loads(_PROFILE_PATH.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return UserProfile()


def save_profile(profile: UserProfile) -> None:
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), "utf-8")
