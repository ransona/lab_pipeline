#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


DEFAULT_RAW_ROOT = Path("/data/Remote_Repository")
DEFAULT_USER_MAP = Path("/data/common/configs/data_manager/users.txt")
HABITUATION_USER = "machine-pipeline-access"
EXP_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d+_(?P<animal>.+)$")


@dataclass(frozen=True)
class MetadataPlan:
    exp_dir: Path
    metadata_path: Path
    payload: Dict[str, str]
    reason: str


def load_user_map(path: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            mapping[parts[0].upper()] = parts[1]
    return mapping


def parse_animal_id(exp_id: str) -> Optional[str]:
    match = EXP_ID_RE.match(exp_id)
    if not match:
        return None
    return match.group("animal")


def lookup_user(exp_id: str, animal_id: str, user_map: Dict[str, str]) -> Optional[str]:
    # Matches Data Manager's raw experiment-owner rule: chars 17-18, 1-based.
    if len(exp_id) >= 18:
        initials = exp_id[16:18].upper()
        if initials in user_map:
            return user_map[initials]

    # Fallback for animal IDs without a standard expID prefix.
    if len(animal_id) >= 4:
        initials = animal_id[2:4].upper()
        if initials in user_map:
            return user_map[initials]

    return None


def is_habituation(exp_dir: Path, exp_id: str) -> bool:
    return (exp_dir / f"{exp_id}_habit.mp4").is_file()


def iter_exp_dirs(raw_root: Path) -> Iterable[Path]:
    for animal_dir in sorted(raw_root.iterdir()):
        if not animal_dir.is_dir():
            continue
        for exp_dir in sorted(animal_dir.iterdir()):
            if exp_dir.is_dir():
                yield exp_dir


def build_plan(
    raw_root: Path,
    user_map: Dict[str, str],
    skip_unknown: bool,
) -> tuple[List[MetadataPlan], Dict[str, int]]:
    plans: List[MetadataPlan] = []
    counts = {
        "seen_dirs": 0,
        "existing_metadata": 0,
        "nonstandard_exp_id": 0,
        "unknown_user": 0,
        "planned": 0,
        "habituation": 0,
    }

    for exp_dir in iter_exp_dirs(raw_root):
        counts["seen_dirs"] += 1
        exp_id = exp_dir.name
        metadata_path = exp_dir / f"{exp_id}_experiment_metadata.json"
        if metadata_path.exists():
            counts["existing_metadata"] += 1
            continue

        animal_id = parse_animal_id(exp_id)
        if not animal_id:
            counts["nonstandard_exp_id"] += 1
            continue

        habit = is_habituation(exp_dir, exp_id)
        if habit:
            user = HABITUATION_USER
            reason = "habituation"
            counts["habituation"] += 1
        else:
            user = lookup_user(exp_id, animal_id, user_map)
            reason = "lookup"
            if not user:
                counts["unknown_user"] += 1
                if skip_unknown:
                    continue
                user = "unknown"
                reason = "unknown"

        payload = {
            "expID": exp_id,
            "animalID": animal_id,
            "user": user,
            "description": "habituation" if habit else "",
            "stim_filename": "",
            "remote_experiment_dir": "",
            "created_at": "",
        }
        plans.append(MetadataPlan(exp_dir, metadata_path, payload, reason))
        counts["planned"] += 1

    return plans, counts


def write_metadata(plan: MetadataPlan) -> None:
    tmp_path = plan.metadata_path.with_suffix(plan.metadata_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(plan.payload, handle, indent=2)
        handle.write("\n")
    tmp_path.replace(plan.metadata_path)


def print_plan(plans: List[MetadataPlan], limit: int, sample: bool, seed: Optional[int]) -> None:
    selected = plans
    if sample and len(plans) > limit:
        rng = random.Random(seed)
        selected = rng.sample(plans, limit)
    else:
        selected = plans[:limit]
    for plan in selected:
        print(f"{plan.reason}: {plan.metadata_path}")
        print(json.dumps(plan.payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill <expID>_experiment_metadata.json in raw experiment folders."
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--user-map", type=Path, default=DEFAULT_USER_MAP)
    parser.add_argument("--write", action="store_true", help="Create missing metadata files.")
    parser.add_argument(
        "--skip-unknown",
        action="store_true",
        help="Skip experiments whose initials are not in the lookup table.",
    )
    parser.add_argument("--show", type=int, default=10, help="Number of planned examples to print.")
    parser.add_argument("--sample", action="store_true", help="Show random planned examples.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for --sample.")
    args = parser.parse_args()

    user_map = load_user_map(args.user_map)
    plans, counts = build_plan(args.raw_root, user_map, skip_unknown=args.skip_unknown)

    print("Summary")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    print(f"  mode: {'write' if args.write else 'dry-run'}")
    print()

    if plans and args.show:
        print_plan(plans, args.show, sample=args.sample, seed=args.seed)
        print()

    if args.write:
        for plan in plans:
            write_metadata(plan)
        print(f"Wrote {len(plans)} metadata files.")
    else:
        print("Dry run only. Re-run with --write to create files.")


if __name__ == "__main__":
    main()
