"""Generate a shifted random-pattern TIFF and demonstrate Suite2p 1.x failures.

Run from the Suite2p 1.1 env, for example:

    /home/adamranson/miniconda3/envs/suite2p_1.1.0/bin/python scripts/debug_suite2p_no_roi.py

The script exits 0 when Suite2p fails before completing both planes. A
"no ROIs were found" ValueError is the expected detection-stage failure, but a
registration-stage failure is also useful because it demonstrates that the
standard Suite2p pipeline does not complete the two-plane synthetic dataset.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import tifffile
from suite2p.parameters import default_db, default_settings
from suite2p.run_s2p import run_s2p


EXPECTED_NO_ROI_MESSAGE = "no ROIs were found"
DEFAULT_LOG_ROOT = Path("/home/adamranson/data/suite2p_debug/no_roi_multiplane")


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def build_shifted_random_tiff(
    path: Path,
    nplanes: int,
    nframes_per_plane: int,
    ly: int,
    lx: int,
    max_shift: int,
    seed: int,
) -> None:
    rng = np.random.default_rng(seed)
    total_frames = int(nplanes) * int(nframes_per_plane)
    base_pattern = rng.integers(500, 2500, size=(ly, lx), dtype=np.uint16)
    movie = np.empty((total_frames, ly, lx), dtype=np.uint16)
    for frame_idx in range(total_frames):
        y_shift = int(rng.integers(-max_shift, max_shift + 1))
        x_shift = int(rng.integers(-max_shift, max_shift + 1))
        movie[frame_idx] = np.roll(base_pattern, shift=(y_shift, x_shift), axis=(0, 1))
    tifffile.imwrite(path, movie, photometric="minisblack")


def build_suite2p_settings(args: argparse.Namespace) -> dict:
    settings = default_settings()
    # Keep the default Suite2p processing path by default: registration and
    # detection both run, and detection thresholds are Suite2p defaults.
    settings["io"]["delete_bin"] = False
    settings["io"]["move_bin"] = False
    settings["io"]["save_mat"] = False
    if args.no_registration:
        settings["run"]["do_registration"] = 0
        settings["run"]["do_regmetrics"] = False
    if args.nbins is not None:
        settings["detection"]["nbins"] = int(args.nbins)
    if args.threshold_scaling is not None:
        settings["detection"]["threshold_scaling"] = float(args.threshold_scaling)
    return settings


def build_suite2p_db(raw_dir: Path, output_dir: Path, nplanes: int) -> dict:
    db = default_db()
    db.update(
        {
            "data_path": [str(raw_dir)],
            "save_path0": str(output_dir),
            "nplanes": int(nplanes),
            "nchannels": 1,
            "functional_chan": 1,
        }
    )
    return db


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=None, help=f"Output directory. Defaults to {DEFAULT_LOG_ROOT}/run_<timestamp>.")
    parser.add_argument("--nplanes", type=int, default=2, help="Number of planes to declare to Suite2p.")
    parser.add_argument("--nframes-per-plane", type=int, default=240)
    parser.add_argument("--ly", type=int, default=512)
    parser.add_argument("--lx", type=int, default=512)
    parser.add_argument("--max-shift", type=int, default=10, help="Maximum random x/y pixel shift applied to each generated frame.")
    parser.add_argument("--seed", type=int, default=1, help="Random seed for reproducible generated data.")
    parser.add_argument("--nbins", type=int, default=None, help="Override Suite2p detection nbins. Default keeps Suite2p default.")
    parser.add_argument("--threshold-scaling", type=float, default=None, help="Override Suite2p threshold scaling. Default keeps Suite2p default.")
    parser.add_argument("--no-registration", action="store_true", help="Disable registration; default keeps standard Suite2p registration enabled.")
    args = parser.parse_args()

    if args.work_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = DEFAULT_LOG_ROOT / f"run_{timestamp}"
        root.mkdir(parents=True, exist_ok=False)
    else:
        root = args.work_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)

    raw_dir = root / "raw"
    output_dir = root / "suite2p_output"
    raw_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    tiff_path = raw_dir / "shifted_random_pattern.tif"
    log_path = root / "suite2p_no_roi_multiplane.log"

    with log_path.open("w", encoding="utf-8", buffering=1) as log_handle:
        tee_out = Tee(sys.__stdout__, log_handle)
        tee_err = Tee(sys.__stderr__, log_handle)
        with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
            logging.basicConfig(stream=tee_err, level=logging.INFO)
            return run_debug(args, root, raw_dir, output_dir, tiff_path, log_path)


def run_debug(args: argparse.Namespace, root: Path, raw_dir: Path, output_dir: Path, tiff_path: Path, log_path: Path) -> int:
    print(f"Work dir: {root}")
    print(f"Log path: {log_path}")
    print(f"Writing generated TIFF: {tiff_path}")
    print(f"Generated data: nplanes={args.nplanes}, nframes_per_plane={args.nframes_per_plane}, total_frames={args.nplanes * args.nframes_per_plane}, Ly={args.ly}, Lx={args.lx}")
    print(f"Synthetic movie: fixed random pattern, random per-frame x/y shifts up to {args.max_shift} px, seed={args.seed}")
    print("Suite2p mode: standard run_s2p path; registration enabled unless --no-registration is used.")
    build_shifted_random_tiff(tiff_path, args.nplanes, args.nframes_per_plane, args.ly, args.lx, args.max_shift, args.seed)

    settings = build_suite2p_settings(args)
    db = build_suite2p_db(raw_dir, output_dir, args.nplanes)
    print(f"Suite2p db: data_path={db['data_path']}, save_path0={db['save_path0']}, nplanes={db['nplanes']}, nchannels={db['nchannels']}")
    print(f"Suite2p run settings: do_registration={settings['run']['do_registration']}, do_detection={settings['run']['do_detection']}")
    print(f"Suite2p detection settings: algorithm={settings['detection']['algorithm']}, nbins={settings['detection']['nbins']}, threshold_scaling={settings['detection']['threshold_scaling']}")

    try:
        run_s2p(db=db, settings=settings)
    except ValueError as exc:
        traceback.print_exc()
        if EXPECTED_NO_ROI_MESSAGE in str(exc):
            print("EXPECTED SUITE2P FAILURE OBSERVED:")
            print(f"{type(exc).__name__}: {exc}")
            print_plane_completion_summary(output_dir)
            print(f"Debug outputs kept in: {root}")
            print(f"Log file: {log_path}")
            return 0
        print("SUITE2P FAILURE OBSERVED BEFORE COMPLETING ALL PLANES:")
        print(f"{type(exc).__name__}: {exc}")
        print_plane_completion_summary(output_dir)
        print(f"Debug outputs kept in: {root}")
        print(f"Log file: {log_path}")
        return 0
    except Exception as exc:
        traceback.print_exc()
        print("SUITE2P FAILURE OBSERVED BEFORE COMPLETING ALL PLANES:")
        print(f"{type(exc).__name__}: {exc}")
        print_plane_completion_summary(output_dir)
        print(f"Debug outputs kept in: {root}")
        print(f"Log file: {log_path}")
        return 0

    print("UNEXPECTED SUCCESS: Suite2p completed without raising a no-ROI error.")
    print_plane_completion_summary(output_dir)
    print(f"Debug outputs kept in: {root}")
    print(f"Log file: {log_path}")
    return 1


def print_plane_completion_summary(output_dir: Path) -> None:
    suite2p_dir = output_dir / "suite2p"
    print("Plane completion summary:")
    if not suite2p_dir.exists():
        print(f"  Suite2p output folder was not created: {suite2p_dir}")
        return
    plane_dirs = sorted(path for path in suite2p_dir.glob("plane*") if path.is_dir())
    if not plane_dirs:
        print(f"  No plane folders found under: {suite2p_dir}")
        return
    for plane_dir in plane_dirs:
        files = sorted(path.name for path in plane_dir.iterdir() if path.is_file())
        roi_files = [name for name in ("ops.npy", "stat.npy", "iscell.npy", "F.npy", "Fneu.npy", "spks.npy") if name in files]
        print(f"  {plane_dir.name}: files={roi_files}")


if __name__ == "__main__":
    raise SystemExit(main())
