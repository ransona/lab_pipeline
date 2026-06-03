from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DataNode:
    scope: str  # raw | processed
    animal_id: str
    path: Path
    user: Optional[str] = None  # home directory owner for processed scope
    exp_id: Optional[str] = None
    owner: Optional[str] = None
    has_override: bool = False
    size_bytes: Optional[int] = None
    last_access_ts: Optional[int] = None
    marked_for_deletion: bool = False

    @property
    def key(self) -> str:
        user_part = self.user or ""
        return f"{self.scope}|{user_part}|{self.animal_id}|{self.exp_id or ''}"

    @property
    def display_name(self) -> str:
        return self.exp_id or self.animal_id
