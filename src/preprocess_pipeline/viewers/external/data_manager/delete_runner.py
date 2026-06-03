#!/usr/bin/env python
"""
Deletion runner for data_manager.

Reads pending deletions from the shared DB and removes them from disk.
Supports optional minimum age and non-interactive mode.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

# Defaults
DEFAULT_MIN_AGE_DAYS = 0
DEFAULT_AUTO = False
DEFAULT_INCLUDE_DELETED = True
NAS_RAW_ROOT = Path("/mnt/nas2/Remote_Repository")
LOG_PATH = Path("/data/common/configs/data_manager/delete_runner_log.txt")

from data_manager.config import DataPaths
from data_manager.database import DataStore


def human_size(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if n < 1024:
            return f"{n:.2f}{unit}"
        n /= 1024
    return f"{n:.2f}EB"


def gather_folders(datastore: DataStore, min_age_days: float) -> List[Tuple[str, str, str, str]]:
    """Return list of (scope, animal, exp, marked_by) folder deletions eligible by age/status."""
    rows = datastore.load_kill_flags().values()
    cutoff = time.time() - (min_age_days * 86400)
    eligible = []
    for row in rows:
        if row["status"] != "pending":
            continue
        if row["marked_at"] and row["marked_at"] > cutoff:
            continue
        eligible.append((row["scope"], row["animal_id"], row["exp_id"], row["marked_by"]))
    return eligible


def gather_files(datastore: DataStore, min_age_days: float) -> List[Tuple[str, str, str, str]]:
    """Return list of (path, scope, animal, exp) file deletions eligible by age/status."""
    rows = datastore.load_file_deletions().values()
    cutoff = time.time() - (min_age_days * 86400)
    eligible = []
    for row in rows:
        if row["status"] not in ("pending",):
            continue
        if row["marked_at"] and row["marked_at"] > cutoff:
            continue
        eligible.append((row["path"], row["scope"], row["animal_id"], row["exp_id"]))
    return eligible


def size_of_path(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total


def _rmtree_onerror(func, path, exc_info):
    log(f"ERROR deleting: {path} ({exc_info[1]})")


def delete_path(path: Path) -> bool:
    if not path.exists():
        log(f"Skip missing: {path}")
        return False
    if path.is_dir():
        errors = []

        def onerror(func, path_str, exc_info):
            errors.append((path_str, exc_info[1]))
            _rmtree_onerror(func, path_str, exc_info)

        shutil.rmtree(path, onerror=onerror)
        if errors:
            log(f"ERROR deleting dir: {path}")
            return False
        log(f"Deleted dir: {path}")
        return True
    else:
        try:
            path.unlink()
            log(f"Deleted file: {path}")
            return True
        except OSError:
            log(f"ERROR deleting file: {path}")
            return False


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        print(f"[WARN] Failed to write log: {LOG_PATH}")


def map_raw_to_nas(raw_path: Path, raw_root: Path) -> Path:
    """Map a raw server path to its NAS equivalent."""
    try:
        rel = raw_path.relative_to(raw_root)
    except ValueError:
        return NAS_RAW_ROOT / raw_path.name
    return NAS_RAW_ROOT / rel


def safe_delete_nas(nas_path: Path) -> None:
    """Delete only if the path is under the NAS raw root."""
    try:
        nas_path.resolve().relative_to(NAS_RAW_ROOT.resolve())
    except Exception:
        log(f"Skip NAS delete outside root: {nas_path}")
        return False
    return delete_path(nas_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deletion of flagged items.")
    parser.add_argument("--min-age-days", type=float, default=DEFAULT_MIN_AGE_DAYS, help="Minimum age (days) since request.")
    parser.add_argument("--auto", action="store_true", default=DEFAULT_AUTO, help="Do not prompt for confirmation.")
    parser.add_argument(
        "--include-deleted",
        action="store_true",
        default=DEFAULT_INCLUDE_DELETED,
        help="Also attempt deletion for items already marked deleted.",
    )
    args = parser.parse_args()

    paths = DataPaths()
    datastore = DataStore(paths.db_file)

    # Sanity check: ensure we can write to raw storage
    test_path = paths.raw_root / f".delete_runner_test_{os.getpid()}"
    try:
        test_path.write_text("test", encoding="utf-8")
        test_path.unlink()
        log(f"Raw storage writable: {paths.raw_root}")
    except OSError:
        log(f"ERROR: raw storage not writable: {paths.raw_root}")
        sys.exit(1)

    folders = gather_folders(datastore, args.min_age_days)
    files = gather_files(datastore, args.min_age_days)
    if args.include_deleted:
        rows = datastore.load_kill_flags().values()
        cutoff = time.time() - (args.min_age_days * 86400)
        for row in rows:
            if row["status"] != "deleted":
                continue
            if row["marked_at"] and row["marked_at"] > cutoff:
                continue
            folders.append((row["scope"], row["animal_id"], row["exp_id"], row["marked_by"]))

    # Summarize sizes
    def resolve_processed_path(user: str, animal: str, exp: str) -> Path:
        candidates = [
            paths.home_root / user / "Data" / "Repository" / animal / exp,
            paths.home_root / user / "data" / "Repository" / animal / exp,
        ]
        for c in candidates:
            if c.exists():
                return c
        # fall back to first candidate even if missing
        return candidates[0]

    folder_sizes = []
    for scope, animal, exp, marked_by in folders:
        if scope == "raw":
            p = paths.raw_root / animal / exp if exp else paths.raw_root / animal
        else:
            user = marked_by or "unknown"
            p = resolve_processed_path(user, animal, exp or "")
        folder_sizes.append((scope, animal, exp, p, size_of_path(p)))
    file_sizes = []
    for path_str, scope, animal, exp in files:
        p = Path(path_str)
        file_sizes.append((scope, animal, exp, p, size_of_path(p)))

    total_bytes = sum(s for *_rest, s in folder_sizes) + sum(s for *_rest, s in file_sizes)

    log(f"Folders eligible: {len(folder_sizes)}")
    for scope, animal, exp, p, sz in folder_sizes:
        log(f"{scope} {animal}/{exp or ''} -> {p} [{human_size(sz)}]")
    log(f"Files eligible: {len(file_sizes)}")
    for scope, animal, exp, p, sz in file_sizes:
        log(f"{scope} {animal}/{exp or ''} -> {p} [{human_size(sz)}]")
    log(f"Total to delete: {human_size(total_bytes)}")

    if not args.auto:
        resp = input("Clear NAS data already on server before deletion? [y/N]: ").strip().lower()
        if resp == "y":
            nas_clear = Path(__file__).parent / "nas_clear.py"
            if nas_clear.exists():
                log("Running nas_clear.py ...")
                subprocess.run([sys.executable, str(nas_clear)], check=False)
            else:
                log("nas_clear.py not found; skipping.")
        resp = input("Proceed with deletion? [y/N]: ").strip().lower()
        if resp != "y":
            log("Aborted by user.")
            sys.exit(0)

    # Delete folders
    raw_animals = set()
    processed_animals = set()
    for scope, animal, exp, p, _sz in folder_sizes:
        if scope == "raw":
            raw_animals.add(animal)
            nas_path = map_raw_to_nas(p, paths.raw_root)
            if nas_path.exists():
                safe_delete_nas(nas_path)
        elif scope == "processed":
            # track (user, animal) for empty cleanup
            user = (Path(p).parts[2] if len(Path(p).parts) > 2 else None)
            if user:
                processed_animals.add((user, animal))
        if delete_path(p):
            datastore.set_kill_status(scope, animal, exp, status="deleted")
    # Delete files
    for scope, animal, exp, p, _sz in file_sizes:
        if scope == "raw":
            nas_path = map_raw_to_nas(p, paths.raw_root)
            if nas_path.exists():
                safe_delete_nas(nas_path)
        if delete_path(p):
            datastore.clear_file_deletion(str(p))

    # Cleanup empty raw animal folders
    for animal in sorted(raw_animals):
        animal_path = paths.raw_root / animal
        try:
            if animal_path.exists() and animal_path.is_dir() and not any(animal_path.iterdir()):
                delete_path(animal_path)
                log(f"Removed empty animal folder: {animal_path}")
        except OSError:
            log(f"ERROR checking animal folder: {animal_path}")

    # Cleanup empty processed animal folders
    for user, animal in sorted(processed_animals):
        candidates = [
            paths.home_root / user / "Data" / "Repository" / animal,
            paths.home_root / user / "data" / "Repository" / animal,
        ]
        for animal_path in candidates:
            try:
                if animal_path.exists() and animal_path.is_dir() and not any(animal_path.iterdir()):
                    delete_path(animal_path)
                    log(f"Removed empty processed animal folder: {animal_path}")
            except OSError:
                log(f"ERROR checking processed animal folder: {animal_path}")

    log("Deletion complete.")


if __name__ == "__main__":
    main()
