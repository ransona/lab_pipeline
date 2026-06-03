from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

from .config import DataPaths


def has_suite2p_bin(processed_exp: Path) -> bool:
    for root, dirs, files in os.walk(processed_exp):
        # only dive into suite2p folders
        if "suite2p" not in Path(root).parts:
            continue
        for f in files:
            if f.endswith(".bin"):
                return True
    return False


def count_tifs(raw_exp: Path) -> int:
    count = 0
    for root, _dirs, files in os.walk(raw_exp):
        for f in files:
            if f.lower().endswith(".tif"):
                count += 1
    return count


def find_tif_candidates(
    processed_nodes: List["DataNode"], paths: DataPaths
) -> List[Tuple[str, str, Path, int]]:
    """
    Return list of (animal_id, exp_id, raw_path, tif_count).
    Only includes entries that have suite2p bin in processed and tifs in raw.
    """
    candidates = []
    for node in processed_nodes:
        if node.exp_id is None:
            continue
        if not has_suite2p_bin(node.path):
            continue
        raw_path = paths.raw_root / node.animal_id / node.exp_id
        if not raw_path.exists():
            continue
        tif_count = count_tifs(raw_path)
        if tif_count > 0:
            candidates.append((node.animal_id, node.exp_id, raw_path, tif_count))
    return candidates


def list_tif_files(raw_exp: Path) -> List[Path]:
    files: List[Path] = []
    for root, _dirs, filenames in os.walk(raw_exp):
        for f in filenames:
            if f.lower().endswith(".tif"):
                files.append(Path(root) / f)
    return files
