"""Generate a flat TIFF and demonstrate Suite2p 1.x crashes when no ROIs are found.

Run from the Suite2p 1.1 env, for example:

    /home/adamranson/miniconda3/envs/suite2p_1.1.0/bin/python scripts/debug_suite2p_no_roi.py --keep

The script exits 0 when Suite2p raises the expected "no ROIs were found"
ValueError. It exits non-zero if Suite2p completes unexpectedly or fails for a
different reason.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import numpy as np
import tifffile
from suite2p.parameters import default_db, default_settings
from suite2p.run_s2p import run_s2p


EXPECTED_NO_ROI_MESSAGE = "no ROIs were found"


def build_flat_tiff(path: Path, nframes: int, ly: int, lx: int) -> None:
    movie = np.full((nframes, ly, lx), 1000, dtype=np.uint16)
    tifffile.imwrite(path, movie, photometric="minisblack")


def build_suite2p_settings(nbins: int, threshold_scaling: float) -> dict:
    settings = default_settings()
    settings["fs"] = 10.0
    settings["tau"] = 1.0
    settings["diameter"] = [12.0, 12.0]
    settings["run"]["do_registration"] = 0
    settings["run"]["do_regmetrics"] = False
    settings["run"]["do_detection"] = True
    settings["io"]["delete_bin"] = False
    settings["io"]["move_bin"] = False
    settings["io"]["save_mat"] = False
    settings["detection"]["nbins"] = int(nbins)
    settings["detection"]["threshold_scaling"] = float(threshold_scaling)
    settings["detection"]["sparsery_settings"]["spatial_scale"] = 1
    return settings


def build_suite2p_db(raw_dir: Path, output_dir: Path) -> dict:
    db = default_db()
    db.update(
        {
            "data_path": [str(raw_dir)],
            "save_path0": str(output_dir),
            "nplanes": 1,
            "nchannels": 1,
            "functional_chan": 1,
        }
    )
    return db


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=None, help="Output directory. Defaults to /tmp.")
    parser.add_argument("--keep", action="store_true", help="Do not delete generated TIFF/Suite2p outputs.")
    parser.add_argument("--nframes", type=int, default=240)
    parser.add_argument("--ly", type=int, default=64)
    parser.add_argument("--lx", type=int, default=64)
    parser.add_argument("--nbins", type=int, default=60)
    parser.add_argument("--threshold-scaling", type=float, default=10.0)
    args = parser.parse_args()

    if args.work_dir is None:
        root = Path(tempfile.mkdtemp(prefix="suite2p_no_roi_debug_", dir="/tmp"))
        cleanup_root = root
    else:
        root = args.work_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        cleanup_root = None

    raw_dir = root / "raw"
    output_dir = root / "suite2p_output"
    raw_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    tiff_path = raw_dir / "flat_no_roi.tif"

    print(f"Work dir: {root}")
    print(f"Writing generated TIFF: {tiff_path}")
    build_flat_tiff(tiff_path, args.nframes, args.ly, args.lx)

    settings = build_suite2p_settings(args.nbins, args.threshold_scaling)
    db = build_suite2p_db(raw_dir, output_dir)

    try:
        run_s2p(db=db, settings=settings)
    except ValueError as exc:
        if EXPECTED_NO_ROI_MESSAGE in str(exc):
            print("EXPECTED SUITE2P FAILURE OBSERVED:")
            print(f"{type(exc).__name__}: {exc}")
            if args.keep:
                print(f"Kept debug outputs in: {root}")
            elif cleanup_root is not None:
                shutil.rmtree(cleanup_root, ignore_errors=True)
            return 0
        print("UNEXPECTED ValueError:")
        print(f"{type(exc).__name__}: {exc}")
        if args.keep:
            print(f"Kept debug outputs in: {root}")
        return 2
    except Exception as exc:
        print("UNEXPECTED EXCEPTION:")
        print(f"{type(exc).__name__}: {exc}")
        if args.keep:
            print(f"Kept debug outputs in: {root}")
        return 3

    print("UNEXPECTED SUCCESS: Suite2p completed without raising a no-ROI error.")
    if args.keep:
        print(f"Kept debug outputs in: {root}")
    elif cleanup_root is not None:
        shutil.rmtree(cleanup_root, ignore_errors=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
