"""Frequency-encoded (periodic) retinotopy analysis for processed experiments.

Unlike the original standalone periodic GUI, this module deliberately uses the
Timeline-aligned ``*_all_trials.csv`` and Suite2p's
``timeline_frame_times.npy``.  It therefore needs no raw Timeline MAT file and
can run against either a local processed copy or a user's Repository folder.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter, uniform_filter1d

from preprocess_pipeline.retinotopy import PlaneSource, discover_plane_sources, _source_movie


OUTPUT_DIRNAME = "periodic"


def experiment_info(exp_dir: Path) -> tuple[list[PlaneSource], list[dict]]:
    """Return Suite2p sources and distinct periodic stimulus conditions."""
    trial_files = sorted(exp_dir.glob("*_all_trials.csv"))
    if not trial_files:
        raise FileNotFoundError("No processed *_all_trials.csv found; run Step 2 Bonvision first.")
    trials = pd.read_csv(trial_files[0])
    if "time" not in trials:
        raise ValueError("The processed trial table has no Timeline 'time' column.")
    sources = discover_plane_sources(exp_dir)
    if not sources:
        raise FileNotFoundError("No Suite2p source with a binary and timeline_frame_times.npy found.")
    # Group by stimulus descriptors, not per-trial time or bookkeeping fields.
    ignored = {"time", "trial", "trial_num", "trial_number", "trial_index"}
    columns = [column for column in trials if column not in ignored]
    groups: dict[str, dict] = {}
    for _, row in trials.iterrows():
        if not np.isfinite(pd.to_numeric(row.get("time"), errors="coerce")):
            continue
        values = {key: _json_value(row[key]) for key in columns if pd.notna(row[key])}
        key = json.dumps(values, sort_keys=True)
        groups.setdefault(key, values)
    return sources, list(groups.values())


def _json_value(value):
    return value.item() if isinstance(value, np.generic) else value


def condition_times(exp_dir: Path, condition: dict) -> np.ndarray:
    """Find Timeline onsets whose stimulus descriptors match ``condition``."""
    trial_file = sorted(exp_dir.glob("*_all_trials.csv"))[0]
    trials = pd.read_csv(trial_file)
    matching = np.ones(len(trials), dtype=bool)
    for key, value in condition.items():
        if key not in trials:
            continue
        matching &= trials[key].astype(str).to_numpy() == str(value)
    return pd.to_numeric(trials.loc[matching, "time"], errors="coerce").dropna().to_numpy(float)


def source_label(exp_dir: Path, source: PlaneSource) -> str:
    return str(source.plane_dir.relative_to(exp_dir)) + f" / channel {source.channel}"


def _smooth_cycle(movie: np.ndarray, sigma: float, temporal: int, circular: bool) -> np.ndarray:
    result = movie.copy()
    if sigma > 0:
        radius = int(np.ceil(3 * sigma))
        result = gaussian_filter(result, sigma=(0, sigma, sigma), radius=(0, radius, radius), mode="nearest")
    if temporal > 1:
        result = uniform_filter1d(result, size=temporal, axis=0, mode="wrap" if circular else "nearest")
    return result


def run_analysis(cfg: dict, progress=None) -> Path:
    """Average periodic cycles and save FFT amplitude/phase maps in ``periodic/``."""
    exp_dir = Path(cfg["experiment_dir"])
    source = next(source for source in discover_plane_sources(exp_dir) if source_label(exp_dir, source) == cfg["source"])
    frames, times, _ops = _source_movie(source)
    fs = 1.0 / float(np.median(np.diff(times)))
    period, duration = float(cfg["period"]), float(cfg["duration"])
    exclude = float(cfg.get("exclude", 0.0))
    if period <= 0 or duration <= exclude + period:
        raise ValueError("Duration must contain at least one complete period after the initial exclusion.")
    onsets = np.asarray(cfg["onsets"], dtype=float)
    ncycle = max(2, int(round(period * fs)))
    cycle_offsets = np.arange(ncycle) / fs
    starts = []
    for onset in onsets:
        trial_starts = onset + exclude + np.arange(int((duration - exclude) // period)) * period
        starts.extend(start for start in trial_starts if start + cycle_offsets[-1] <= times[-1])
    starts = np.asarray(starts)
    if not len(starts):
        raise ValueError("No complete stimulus cycles overlap the processed imaging timestamps.")
    raw_cycle = np.zeros((ncycle, frames.shape[1], frames.shape[2]), dtype=np.float32)
    minimum_value = float(cfg.get("minimum_video_value", 10.0))
    source_minimum = float(frames.min())
    offset = max(0.0, minimum_value - source_minimum)
    for index, start in enumerate(starts):
        frame_indices = np.searchsorted(times, start + cycle_offsets)
        frame_indices = np.clip(frame_indices, 0, len(times) - 1)
        before = np.maximum(frame_indices - 1, 0)
        use_before = np.abs(times[before] - (start + cycle_offsets)) < np.abs(times[frame_indices] - (start + cycle_offsets))
        frame_indices[use_before] = before[use_before]
        raw_cycle += frames[frame_indices].astype(np.float32) + offset
        if progress:
            progress(index + 1, len(starts), "Averaging stimulus cycles")
    raw_cycle /= len(starts)
    baseline = raw_cycle.mean(axis=0)
    dff = (raw_cycle - baseline) / np.maximum(np.abs(baseline), float(cfg.get("baseline_floor", 10.0)))
    sigma, temporal = float(cfg.get("spatial_sigma", 5.0)), int(cfg.get("temporal", 5))
    circular = bool(cfg.get("circular", True))
    fft_cycle = _smooth_cycle(raw_cycle, sigma, temporal, circular)
    dff = _smooth_cycle(dff, sigma, temporal, circular)
    detrend_frames = int(round(float(cfg.get("detrend", 0.0)) * fs))
    if 2 < detrend_frames < len(dff):
        dff -= uniform_filter1d(dff, size=detrend_frames, axis=0, mode="wrap" if circular else "nearest")
    frequency = float(cfg.get("frequency") or 1.0 / period)
    frequencies = np.fft.rfftfreq(len(fft_cycle), 1.0 / fs)
    target = int(np.argmin(np.abs(frequencies - frequency)))
    transformed = np.fft.rfft(fft_cycle, axis=0)
    amplitude = 2 * np.abs(transformed[target]) / np.maximum(np.abs(transformed[0]), float(cfg.get("baseline_floor", 10.0)) * len(fft_cycle))
    phase = np.angle(transformed[target])

    key_config = {key: value for key, value in cfg.items() if key not in {"onsets", "experiment_dir"}}
    cache_key = hashlib.sha1(json.dumps(key_config, sort_keys=True, default=str).encode()).hexdigest()[:10]
    root = exp_dir / OUTPUT_DIRNAME
    root.mkdir(exist_ok=True)
    for candidate in root.iterdir():
        config_file = candidate / "config.json"
        if config_file.exists() and json.loads(config_file.read_text()).get("cache_key") == cache_key:
            if progress:
                progress(1, 1, "Using cached analysis")
            return candidate
    numbers = [int(path.name.split("_", 1)[0]) for path in root.iterdir() if path.name.split("_", 1)[0].isdigit()]
    output = root / f"{max(numbers, default=-1) + 1:03d}_{date.today():%y%m%d}"
    output.mkdir()
    metadata = {**key_config, "cache_key": cache_key, "sampling_frequency": fs, "selected_frequency": float(frequencies[target]), "cycles": len(starts), "source_minimum": source_minimum, "applied_video_offset": offset}
    (output / "config.json").write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
    np.save(output / "average_cycle_raw.npy", raw_cycle.astype(np.float32))
    np.save(output / "average_cycle_dff.npy", dff.astype(np.float16))
    np.savez_compressed(output / "fft_maps.npz", phase=phase.astype(np.float32), power_over_f0=amplitude.astype(np.float32), frequencies_hz=frequencies.astype(np.float32))
    if progress:
        progress(1, 1, "Saved periodic analysis")
    return output
