"""Retinotopy pixel-montage preparation.

The module deliberately uses the frame timestamps exported by Suite2p timestamp
preprocessing (``timeline_frame_times.npy``), rather than deriving timing from
the binary's nominal frame rate.  This keeps trial alignment in Timeline time.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re

import numpy as np
import pandas as pd


OUTPUT_DIRNAME = "retinotopy"


@dataclass(frozen=True)
class PlaneSource:
    plane_dir: Path
    bin_path: Path
    channel: str
    plane: str
    roi: str | None
    acquisition: str | None


def find_experiment(processed_root: str | Path, exp_id: str, test_path: str | Path | None = None) -> Path:
    """Resolve an experiment directory, with a direct path for offline testing."""
    if test_path:
        candidate = Path(test_path).expanduser()
        if candidate.is_dir():
            return candidate
        raise FileNotFoundError(f"Test experiment directory does not exist: {candidate}")
    root = Path(processed_root)
    animal = exp_id.rsplit("_", 1)[-1]
    candidate = root / animal / exp_id
    if candidate.is_dir():
        return candidate
    # Local test repositories are sometimes flat; retain a bounded fallback.
    matches = [p for p in root.glob(f"*/{exp_id}") if p.is_dir()]
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(f"Could not find {exp_id} below {root}")


def _load_ops(path: Path) -> dict:
    value = np.load(path, allow_pickle=True)
    return value.item() if isinstance(value, np.ndarray) and value.shape == () else dict(value)


def discover_plane_sources(exp_dir: Path) -> list[PlaneSource]:
    """Find each canonical Suite2p plane/channel binary once.

    A processed experiment may contain archival ``suite2p_final`` directories.
    The directly named ``suite2p`` directory nearest the experiment is canonical;
    copies below an already selected suite2p directory are ignored.
    """
    selected: dict[tuple[str, str], PlaneSource] = {}
    for plane_dir in exp_dir.rglob("suite2p/plane*"):
        if not plane_dir.is_dir() or not re.fullmatch(r"plane\d+", plane_dir.name):
            continue
        if "suite2p_final" in plane_dir.parts:
            continue
        ops_path = plane_dir / "ops.npy"
        timing_path = plane_dir / "timeline_frame_times.npy"
        if not ops_path.exists() or not timing_path.exists():
            continue
        for filename, channel in (("data.bin", "1"), ("data_chan2.bin", "2")):
            binary = plane_dir / filename
            if not binary.exists():
                continue
            key = (str(plane_dir.relative_to(exp_dir)), channel)
            roi = next((part for part in reversed(plane_dir.relative_to(exp_dir).parts) if re.fullmatch(r"R\d+", part)), None)
            acquisition = next((part for part in reversed(plane_dir.relative_to(exp_dir).parts) if re.fullmatch(r"P\d+", part)), None)
            selected[key] = PlaneSource(plane_dir, binary, channel, plane_dir.name.replace("plane", ""), roi, acquisition)
    return sorted(selected.values(), key=lambda source: (source.plane_dir.as_posix(), source.channel))


def _trial_positions(trials: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    candidates = [("F1_x", "F1_y"), ("x", "y")]
    for x_name, y_name in candidates:
        if x_name in trials and y_name in trials:
            x = pd.to_numeric(trials[x_name], errors="coerce").to_numpy(float)
            y = pd.to_numeric(trials[y_name], errors="coerce").to_numpy(float)
            valid = np.isfinite(x) & np.isfinite(y)
            if valid.any():
                return x, y
    raise KeyError("Trial CSV needs F1_x/F1_y (or x/y) columns to form a retinotopy montage.")


def _nearest_frame_indices(frame_times: np.ndarray, target_times: np.ndarray) -> np.ndarray:
    right = np.searchsorted(frame_times, target_times)
    right = np.clip(right, 0, len(frame_times) - 1)
    left = np.clip(right - 1, 0, len(frame_times) - 1)
    return np.where(np.abs(frame_times[right] - target_times) < np.abs(frame_times[left] - target_times), right, left)


def _source_movie(source: PlaneSource) -> tuple[np.memmap, np.ndarray, dict]:
    ops = _load_ops(source.plane_dir / "ops.npy")
    ly, lx = int(ops["Ly"]), int(ops["Lx"])
    values = np.memmap(source.bin_path, mode="r", dtype=np.int16)
    nframes = values.size // (ly * lx)
    if nframes < 1:
        raise ValueError(f"No complete frames in {source.bin_path}")
    frames = values[: nframes * ly * lx].reshape(nframes, ly, lx)
    times = np.asarray(np.load(source.plane_dir / "timeline_frame_times.npy"), dtype=float)
    n = min(nframes, len(times))
    if n < 2:
        raise ValueError(f"Too few aligned frames for {source.plane_dir}")
    return frames[:n], times[:n], ops


def prepare_plane(
    source: PlaneSource,
    trials: pd.DataFrame,
    output_root: Path,
    pre_seconds: float,
    post_seconds: float,
    blink_pre_seconds: float,
    blink_post_seconds: float,
    progress=None,
) -> Path:
    """Create average, blink, and dF/F montage arrays for one Suite2p binary."""
    frames, frame_times, ops = _source_movie(source)
    if "time" not in trials:
        raise KeyError("Trial CSV is missing timeline-aligned 'time'.")
    x, y = _trial_positions(trials)
    onset = pd.to_numeric(trials["time"], errors="coerce").to_numpy(float)
    valid = np.isfinite(onset) & np.isfinite(x) & np.isfinite(y)
    onset, x, y = onset[valid], x[valid], y[valid]
    if not len(onset):
        raise ValueError("No trials have valid onset times and positions.")

    fs = 1.0 / float(np.median(np.diff(frame_times)))
    offsets = np.arange(-pre_seconds, post_seconds + 0.5 / fs, 1.0 / fs)
    x_values, y_values = np.unique(x), np.unique(y)[::-1]  # visual top row first
    ly, lx = int(ops["Ly"]), int(ops["Lx"])
    montage = np.zeros((len(offsets), len(y_values) * ly, len(x_values) * lx), dtype=np.float32)
    counts = np.zeros((len(y_values), len(x_values)), dtype=int)

    for yi, y_value in enumerate(y_values):
        for xi, x_value in enumerate(x_values):
            condition_onsets = onset[(x == x_value) & (y == y_value)]
            selected = [time for time in condition_onsets if frame_times[0] <= time - pre_seconds and time + post_seconds <= frame_times[-1]]
            if not selected:
                continue
            accumulator = np.zeros((len(offsets), ly, lx), dtype=np.float64)
            for trial_time in selected:
                indices = _nearest_frame_indices(frame_times, trial_time + offsets)
                accumulator += frames[indices].astype(np.float32)
            montage[:, yi * ly:(yi + 1) * ly, xi * lx:(xi + 1) * lx] = accumulator / len(selected)
            counts[yi, xi] = len(selected)
        if progress:
            progress(yi + 1, len(y_values), f"{source.plane_dir.name}, channel {source.channel}: row {yi + 1}/{len(y_values)}")

    baseline = montage[(offsets >= -blink_pre_seconds) & (offsets <= 0)].mean(axis=0)
    denominator = np.maximum(baseline, 10.0)
    dff = (montage - baseline[None, :, :]) / denominator[None, :, :]
    post = montage[(offsets >= 0) & (offsets <= blink_post_seconds)].mean(axis=0)
    blink = np.stack((baseline, post)).astype(np.float32)

    # Plane numbers repeat for independently acquired ScanImage ROIs, so the
    # ROI directory is part of the persistent output identity.
    label = f"{source.acquisition + '_' if source.acquisition else ''}{source.roi + '_' if source.roi else ''}plane{source.plane}_channel{source.channel}"
    destination = output_root / label
    destination.mkdir(parents=True, exist_ok=True)
    np.save(destination / "pixel_average_video.npy", montage)
    np.save(destination / "dff_video.npy", dff.astype(np.float32))
    np.save(destination / "blink_map.npy", blink)
    np.save(destination / "time_seconds.npy", offsets)
    with (destination / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump({
            "plane": source.plane, "channel": source.channel, "roi": source.roi, "acquisition": source.acquisition, "bin": str(source.bin_path),
            "x_positions": x_values.tolist(), "y_positions": y_values.tolist(),
            "trial_counts": counts.tolist(), "frame_rate": fs,
            "pre_seconds": pre_seconds, "post_seconds": post_seconds,
            "blink_pre_seconds": blink_pre_seconds, "blink_post_seconds": blink_post_seconds,
            "tile_height": ly, "tile_width": lx,
        }, handle, indent=2)
    return destination


def _make_meso_window(output_root: Path, sources_and_outputs: list[tuple[PlaneSource, Path]]) -> list[Path]:
    """Combine R001/R002 into a horizontally concatenated Meso source.

    Concatenation is done *inside each retinotopic condition tile*, rather than
    simply putting two complete condition montages next to one another.  Thus
    the normal X/Y condition grid and the sampling tool retain their meaning.
    """
    by_key: dict[tuple[str | None, str, str], dict[str, Path]] = {}
    for source, path in sources_and_outputs:
        if source.roi in {"R001", "R002"}:
            by_key.setdefault((source.acquisition, source.plane, source.channel), {})[source.roi] = path
    results = []
    for (acquisition, plane, channel), paths in by_key.items():
        if not {"R001", "R002"}.issubset(paths):
            continue
        first, second = paths["R001"], paths["R002"]
        first_metadata = json.loads((first / "metadata.json").read_text())
        second_metadata = json.loads((second / "metadata.json").read_text())
        compatible = (
            first_metadata["x_positions"] == second_metadata["x_positions"]
            and first_metadata["y_positions"] == second_metadata["y_positions"]
            and first_metadata["tile_height"] == second_metadata["tile_height"]
            and first_metadata["tile_width"] == second_metadata["tile_width"]
        )
        if not compatible:
            continue
        ny, nx = len(first_metadata["y_positions"]), len(first_metadata["x_positions"])
        ly, lx = first_metadata["tile_height"], first_metadata["tile_width"]
        destination = output_root / f"{acquisition + '_' if acquisition else ''}Meso_plane{plane}_channel{channel}"
        destination.mkdir(parents=True, exist_ok=True)
        for filename in ("pixel_average_video.npy", "dff_video.npy", "blink_map.npy"):
            left, right = np.load(first / filename), np.load(second / filename)
            if left.shape != right.shape:
                break
            frames = left.reshape(left.shape[0], ny, ly, nx, lx)
            frames_right = right.reshape(right.shape[0], ny, ly, nx, lx)
            combined = np.concatenate((frames, frames_right), axis=4).reshape(left.shape[0], ny * ly, nx * 2 * lx)
            np.save(destination / filename, combined.astype(np.float32, copy=False))
        else:
            np.save(destination / "time_seconds.npy", np.load(first / "time_seconds.npy"))
            metadata = dict(first_metadata)
            metadata.update({
                "roi": "Meso", "meso_window": ["R001", "R002"],
                "tile_width": lx * 2,
                "bin": [first_metadata["bin"], second_metadata["bin"]],
            })
            (destination / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            results.append(destination)
    return results


def prepare_experiment(exp_dir: Path, pre_seconds: float, post_seconds: float, blink_pre_seconds: float, blink_post_seconds: float, progress=None, meso_window: bool = True) -> list[Path]:
    trial_csvs = list(exp_dir.glob("*_all_trials.csv"))
    if not trial_csvs:
        raw_candidate = Path("/data/Remote_Repository") / exp_dir.parent.name / exp_dir.name / f"{exp_dir.name}_all_trials.csv"
        if raw_candidate.exists():
            raise FileNotFoundError(
                "The processed experiment has no Timeline-aligned trial table. A raw all_trials CSV exists, "
                "but raw tables do not contain Timeline onset times. Run Step 2 with Bonvision enabled "
                "(run_bonvision=True), then run retinotopy preparation again."
            )
        raise FileNotFoundError(
            f"No timeline-aligned *_all_trials.csv found in {exp_dir}. Run Step 2 with Bonvision enabled first."
        )
    trials = pd.read_csv(trial_csvs[0])
    if "time" not in trials.columns:
        raise ValueError(
            "The trial CSV has no Timeline 'time' column. Retinotopy requires the Bonvision-preprocessed "
            "all_trials CSV; run Step 2 with run_bonvision=True first."
        )
    sources = discover_plane_sources(exp_dir)
    if not sources:
        raise FileNotFoundError("No Suite2p plane with data.bin/data_chan2.bin, ops.npy, and timeline_frame_times.npy found.")
    output_root = exp_dir / OUTPUT_DIRNAME
    source_outputs: list[tuple[PlaneSource, Path]] = []
    total = len(sources)
    for index, source in enumerate(sources):
        def report(row, rows, message, plane_index=index):
            if progress:
                progress(plane_index + row / max(rows, 1), total, message)
        source_outputs.append((source, prepare_plane(source, trials, output_root, pre_seconds, post_seconds, blink_pre_seconds, blink_post_seconds, report)))
    meso_results = _make_meso_window(output_root, source_outputs) if meso_window else []
    return [*meso_results, *(path for _, path in source_outputs)]
