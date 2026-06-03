from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass(frozen=True)
class DataPaths:
    raw_root: Path = Path("/data/Remote_Repository")
    home_root: Path = Path("/home")
    user_map_file: Path = Path("/data/common/configs/data_manager/users.txt")
    db_file: Path = Path("/data/common/configs/data_manager/data_manager.db")


def load_user_map(paths: DataPaths) -> Dict[str, str]:
    """
    Parse a tab-delimited initials -> username map.
    Unknown or unreadable files return an empty map.
    """
    mapping: Dict[str, str] = {}
    try:
        with paths.user_map_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                parts = stripped.split()
                if len(parts) >= 2:
                    initials, username = parts[0], parts[1]
                    mapping[initials.upper()] = username.strip()
    except FileNotFoundError:
        # Safe fallback; GUI will show warning
        return {}
    except OSError:
        return {}
    return mapping


def ensure_parent(path: Path) -> None:
    """Create the parent directory for a file if needed."""
    os.makedirs(path.parent, exist_ok=True)

