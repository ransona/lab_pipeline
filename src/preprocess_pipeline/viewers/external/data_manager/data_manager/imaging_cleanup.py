from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple


PROCESSED_DIRECTORY_NAMES = {"suite2p", "suite2p_combined", "ch2", "P0", "P1", "P2"}


def discover_imaging_targets(scope: str, experiment_path: Path) -> List[Tuple[Path, str]]:
    if scope == "raw":
        return _discover_raw_tiffs(experiment_path)
    if scope == "processed":
        return _discover_processed_targets(experiment_path)
    raise ValueError(f"Unsupported scope: {scope}")


def _discover_raw_tiffs(experiment_path: Path) -> List[Tuple[Path, str]]:
    targets: List[Tuple[Path, str]] = []
    for root, _dirs, files in os.walk(experiment_path, followlinks=False):
        for filename in files:
            if Path(filename).suffix.lower() in {".tif", ".tiff"}:
                targets.append((Path(root) / filename, "file"))
    return sorted(targets, key=lambda item: str(item[0]))


def _discover_processed_targets(experiment_path: Path) -> List[Tuple[Path, str]]:
    targets: List[Tuple[Path, str]] = []
    for root, dirs, _files in os.walk(experiment_path, followlinks=False):
        root_path = Path(root)
        selected_dirs = [name for name in dirs if name in PROCESSED_DIRECTORY_NAMES]
        for name in selected_dirs:
            targets.append((root_path / name, "directory"))
        dirs[:] = [name for name in dirs if name not in PROCESSED_DIRECTORY_NAMES]

    for subdir in ("recordings", "cut"):
        target_dir = experiment_path / subdir
        try:
            matches = target_dir.glob("s2p_*.pickle")
            targets.extend((path, "file") for path in matches if path.is_file() or path.is_symlink())
        except OSError:
            continue
    return sorted(targets, key=lambda item: str(item[0]))
