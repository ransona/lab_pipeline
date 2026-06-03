from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .config import DataPaths
from .database import DataStore, ScopeKey
from .models import DataNode


def load_exclude_dirs(paths: DataPaths) -> List[str]:
    exclude_file = Path("exclude_dirs.txt")
    if not exclude_file.exists():
        return []
    entries: List[str] = []
    try:
        with exclude_file.open("r", encoding="utf-8") as handle:
            for line in handle:
                name = line.strip()
                if not name or name.startswith("#"):
                    continue
                entries.append(name.lower())
    except OSError:
        return []
    return entries


def detect_current_user() -> str:
    return getpass.getuser()


def list_available_users(home_root: Path) -> List[str]:
    users: List[str] = []
    try:
        for entry in sorted(home_root.iterdir()):
            if entry.is_dir():
                users.append(entry.name)
    except FileNotFoundError:
        return []
    return users


def _slice_initials(identifier: str, start: int, end: int) -> Optional[str]:
    """Return uppercase initials from 1-based positions; None if too short."""
    if len(identifier) < end:
        return None
    return identifier[start - 1 : end].upper()


def guess_owner(animal_id: str, exp_id: Optional[str], user_map: Dict[str, str]) -> Optional[str]:
    """
    Guess owner based on fixed character positions:
    - Animal ID: chars 3-4 (1-based)
    - Exp ID: chars 17-18 (1-based)
    """
    if exp_id:
        initials = _slice_initials(exp_id, 17, 18)
    else:
        initials = _slice_initials(animal_id, 3, 4)
    if not initials:
        return None
    return user_map.get(initials)


def _make_node(
    scope: str,
    animal_id: str,
    path: Path,
    user: Optional[str],
    exp_id: Optional[str],
    owner: Optional[str],
    has_override: bool,
    metrics_lookup: Dict[ScopeKey, object],
    kill_lookup: Dict[ScopeKey, object],
) -> DataNode:
    key: ScopeKey = (scope, animal_id, exp_id)
    metric_row = metrics_lookup.get(key)
    kill_row = kill_lookup.get(key)
    size_bytes = metric_row["size_bytes"] if metric_row else None
    last_access_ts = metric_row["last_access_ts"] if metric_row else None
    marked = kill_row is not None
    return DataNode(
        scope=scope,
        animal_id=animal_id,
        user=user,
        exp_id=exp_id,
        owner=owner,
        has_override=has_override,
        path=path,
        size_bytes=size_bytes,
        last_access_ts=last_access_ts,
        marked_for_deletion=marked,
    )


def _resolve_owner(
    scope: str,
    animal_id: str,
    exp_id: Optional[str],
    user_map: Dict[str, str],
    overrides: Dict[ScopeKey, str],
    default_user: Optional[str],
) -> Tuple[Optional[str], bool]:
    key: ScopeKey = (scope, animal_id, exp_id)
    if key in overrides:
        return overrides[key], True
    if exp_id:
        # Default to parent owner if available
        parent_key: ScopeKey = (scope, animal_id, None)
        if parent_key in overrides:
            return overrides[parent_key], True
    # Guess based on initials for raw data; processed defaults to the selected user
    if scope == "raw":
        guessed = guess_owner(animal_id, exp_id, user_map)
        return guessed or default_user, False
    return default_user, False


def _processed_repo_paths(user: str, paths: DataPaths) -> List[Path]:
    """
    Return candidate processed repo paths for a user.
    Supports both Data/Repository and data/Repository.
    """
    candidates = [
        paths.home_root / user / "Data" / "Repository",
        paths.home_root / user / "data" / "Repository",
    ]
    seen: List[Path] = []
    for c in candidates:
        if c not in seen:
            seen.append(c)
    return seen


def scan_scope(
    scope: str,
    selected_user: str,
    paths: DataPaths,
    datastore: DataStore,
    user_map: Dict[str, str],
    available_users: Optional[List[str]] = None,
) -> List[DataNode]:
    """
    Build a list of DataNode objects for a scope ('raw' or 'processed').
    Only cached metrics are included; use calculate_metrics to update.
    """
    metrics_lookup = datastore.load_metrics()
    overrides = datastore.load_overrides()
    kill_lookup = datastore.load_kill_flags()
    excluded = set(load_exclude_dirs(paths))

    nodes: List[DataNode] = []

    roots: List[Tuple[Optional[str], Path, Optional[str]]] = []
    if scope == "raw":
        roots.append((None, paths.raw_root, None))
    else:
        target_users = available_users or [selected_user]
        if selected_user != "all":
            target_users = [selected_user]
        for user in target_users:
            for repo_path in _processed_repo_paths(user, paths):
                roots.append((user, repo_path, user))

    for user_for_scope, base_path, default_owner in roots:
        try:
            if not base_path.exists():
                continue
        except OSError:
            # Skip paths we cannot stat (permission issues)
            continue

        try:
            animal_entries = sorted([p for p in base_path.iterdir() if p.is_dir()])
        except OSError:
            continue

        for animal_entry in animal_entries:
            animal_id = animal_entry.name
            if excluded and animal_id.lower() in excluded:
                continue
            owner, has_override = _resolve_owner(
                scope, animal_id, None, user_map, overrides, default_user=default_owner
            )
            animal_node = _make_node(
                scope,
                animal_id,
                animal_entry,
                user=user_for_scope,
                exp_id=None,
                owner=owner,
                has_override=has_override,
                metrics_lookup=metrics_lookup,
                kill_lookup=kill_lookup,
            )
            nodes.append(animal_node)

            # Experiments
            try:
                exp_entries = sorted([p for p in animal_entry.iterdir() if p.is_dir()])
            except OSError:
                exp_entries = []

            for exp_entry in exp_entries:
                exp_id = exp_entry.name
                exp_owner, exp_override = _resolve_owner(
                    scope,
                    animal_id,
                    exp_id,
                    user_map,
                    overrides,
                    default_user=owner or default_owner,
                )
                exp_node = _make_node(
                    scope,
                    animal_id,
                    exp_entry,
                    user=user_for_scope,
                    exp_id=exp_id,
                    owner=exp_owner,
                    has_override=exp_override,
                    metrics_lookup=metrics_lookup,
                    kill_lookup=kill_lookup,
                )
                nodes.append(exp_node)
    return nodes


def calculate_metrics_for_path(path: Path) -> Tuple[int, Optional[int]]:
    """
    Return total size in bytes and latest atime for all files in path.
    Last access may be None if no files are encountered.
    """
    total_size = 0
    latest_access: Optional[int] = None
    for root, dirs, files in os.walk(path):
        for filename in files:
            fpath = Path(root) / filename
            try:
                stat = fpath.stat()
                total_size += stat.st_size
                atime = int(stat.st_atime)
                if latest_access is None or atime > latest_access:
                    latest_access = atime
            except OSError:
                continue
    return total_size, latest_access


def update_metrics_for_nodes(datastore: DataStore, nodes: Iterable[DataNode]) -> None:
    """
    Compute metrics for each node and persist them.
    Intended for background use; heavy on large trees.
    """
    for node in nodes:
        if not node.path.exists():
            continue
        size_bytes, last_access = calculate_metrics_for_path(node.path)
        datastore.upsert_metrics(
            node.scope, node.animal_id, node.exp_id, size_bytes, last_access
        )
