import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Union

import numpy as np

from preprocess_pipeline.shared import paths


MODEL_ROOT = Path("/data/common/srdtrans_models")
FAST_BUILD_ROOT = Path("/data/fast/lab_pipeline/srdtrans_build")
SRDTRANS_REPO = Path("/home/adamranson/code/SRDTrans")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value).strip()).strip("._")


def build_model_name(indicators: str, effective_frame_rate: str, free_text: str) -> str:
    parts = [
        safe_name(indicators),
        safe_name(f"{effective_frame_rate}Hz" if effective_frame_rate else ""),
        safe_name(free_text),
    ]
    return "_".join(part for part in parts if part)


def model_dir(model_name: str) -> Path:
    safe_model_name = safe_name(model_name)
    if not safe_model_name:
        raise ValueError("Model name is empty.")
    return MODEL_ROOT / safe_model_name


def config_path_for_model(model_name: str) -> Path:
    return model_dir(model_name) / "build_config.json"


def read_build_config(config_path: Union[str, Path]) -> dict:
    return json.loads(Path(config_path).read_text(encoding="utf-8"))


def write_build_config(config: dict) -> Path:
    root = Path(config["model_root"])
    root.mkdir(parents=True, exist_ok=True)
    (root / "train_data").mkdir(parents=True, exist_ok=True)
    (root / "pth").mkdir(parents=True, exist_ok=True)
    (root / "results").mkdir(parents=True, exist_ok=True)
    path = root / "build_config.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def create_build_config(
    *,
    user_id: str,
    model_name: str,
    indicators: str,
    effective_frame_rate: str,
    label: str,
    experiments: list[dict],
    train_params: Optional[dict] = None,
) -> dict:
    root = model_dir(model_name)
    fast_root = FAST_BUILD_ROOT / root.name
    config = {
        "userID": user_id,
        "model_name": root.name,
        "model_root": str(root),
        "fast_build_root": str(fast_root),
        "indicators": indicators,
        "effective_frame_rate": effective_frame_rate,
        "label": label,
        "experiments": experiments,
        "train_params": train_params or default_train_params(),
    }
    write_build_config(config)
    return config


def default_train_params() -> dict:
    return {
        "env": "srdtrans",
        "gpu": "0",
        "n_epochs": 30,
        "patch_x": 128,
        "patch_t": 128,
        "overlap_factor": 0.5,
        "train_datasets_size": 6000,
        "lr": 0.0001,
    }


def list_s2p_configs(user_id: str) -> list[str]:
    root = Path("/data/common/configs/s2p_configs") / user_id
    if not root.exists():
        return []
    return sorted(str(path) for path in root.glob("*.npy"))


def resolve_s2p_config(user_id: str, value: str) -> str:
    config_path = Path(value)
    if config_path.is_absolute():
        return str(config_path)
    return str(Path("/data/common/configs/s2p_configs") / user_id / value)


def experiment_raw_work_units(user_id: str, exp_id: str) -> list[dict]:
    _, _, _, _, exp_dir_raw = paths.find_paths(user_id, exp_id)
    raw_root = Path(exp_dir_raw)
    meso_rois = []
    for path_root in sorted(p for p in raw_root.glob("P*") if p.is_dir()):
        for roi_root in sorted(p for p in path_root.glob("R*") if p.is_dir()):
            meso_rois.append(
                {
                    "name": f"{path_root.name}_{roi_root.name}",
                    "display": f"{path_root.name}/{roi_root.name}",
                    "raw_path": str(roi_root),
                }
            )
    if meso_rois:
        return meso_rois
    return [{"name": "root", "display": "root", "raw_path": str(raw_root)}]


def registered_work_unit_root(config: dict, exp_id: str, work_unit_name: str) -> Path:
    return Path(config["fast_build_root"]) / "registered" / safe_name(exp_id) / safe_name(work_unit_name)


def _copy_config_with_forced_rigid_settings(source_config: Union[str, Path], destination: Path) -> Path:
    ops = np.load(source_config, allow_pickle=True).item()
    if not isinstance(ops, dict):
        raise ValueError(f"Suite2p config is not a dict: {source_config}")
    ops = dict(ops)
    ops["save_mat"] = False
    ops["do_registration"] = 2
    ops["nonrigid"] = False
    ops["roidetect"] = False
    ops["spikedetect"] = False
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.save(destination, ops)
    return destination


def register_experiments(config_path: Union[str, Path]) -> None:
    from preprocess_pipeline.suite2p.launcher import run_shared_registration

    config = read_build_config(config_path)
    user_id = config["userID"]
    for experiment in config["experiments"]:
        exp_id = experiment["expID"]
        s2p_config = resolve_s2p_config(user_id, experiment["suite2p_config"])
        work_units = experiment.get("work_units") or experiment_raw_work_units(user_id, exp_id)
        for work_unit in work_units:
            output_root = registered_work_unit_root(config, exp_id, work_unit["name"])
            forced_config = output_root / "rigid_no_extract_ops.npy"
            _copy_config_with_forced_rigid_settings(s2p_config, forced_config)
            print(f"** Registering {exp_id} {work_unit['display']}")
            print(f"Raw path: {work_unit['raw_path']}")
            print(f"Output: {output_root}")
            output_root.mkdir(parents=True, exist_ok=True)
            run_shared_registration([work_unit["raw_path"]], str(output_root), str(forced_config))
            work_unit["registered_root"] = str(output_root)
    write_build_config(config)


def _load_plane_shape(plane_dir: Path, bin_path: Path) -> tuple[int, int, int, np.dtype]:
    ops_path = plane_dir / "ops.npy"
    if not ops_path.exists():
        raise FileNotFoundError(f"Missing ops.npy for registered binary: {ops_path}")
    ops = np.load(ops_path, allow_pickle=True).item()
    ly = int(ops.get("Ly", ops.get("meanImg", np.empty((0, 0))).shape[0]))
    lx = int(ops.get("Lx", ops.get("meanImg", np.empty((0, 0))).shape[1]))
    dtype = np.dtype("int16")
    pixels = ly * lx
    n_frames = bin_path.stat().st_size // dtype.itemsize // pixels
    if ly <= 0 or lx <= 0 or n_frames <= 0:
        raise ValueError(f"Could not determine valid shape for {bin_path}")
    return n_frames, ly, lx, dtype


def extract_training_frames(config_path: Union[str, Path]) -> None:
    config = read_build_config(config_path)
    train_dir = Path(config["model_root"]) / "train_data"
    train_dir.mkdir(parents=True, exist_ok=True)
    selections = [
        selection for experiment in config["experiments"]
        for selection in experiment.get("training_selections", [])
        if selection.get("use", True)
    ]
    if not selections:
        raise ValueError("No training selections are enabled in build_config.json.")

    for selection in selections:
        exp_id = selection["expID"]
        work_unit = selection["work_unit"]
        plane = int(selection["plane"])
        channel = str(selection["channel"])
        start = int(selection.get("start_frame", 0))
        count = int(selection["n_frames"])
        registered_root = Path(selection["registered_root"])
        plane_dir = registered_root / "suite2p" / f"plane{plane}"
        bin_name = "data_chan2.bin" if channel in {"2", "ch2", "chan2"} else "data.bin"
        source_bin = plane_dir / bin_name
        if not source_bin.exists():
            raise FileNotFoundError(f"Missing source binary: {source_bin}")
        n_frames, ly, lx, dtype = _load_plane_shape(plane_dir, source_bin)
        if start < 0 or count <= 0 or start + count > n_frames:
            raise ValueError(
                f"Invalid frame selection for {source_bin}: start={start}, n_frames={count}, available={n_frames}"
            )

        stem = "__".join(
            [
                safe_name(exp_id),
                safe_name(work_unit),
                f"plane{plane}",
                f"ch{2 if bin_name == 'data_chan2.bin' else 1}",
                f"frames{start}-{start + count - 1}",
            ]
        )
        output_bin = train_dir / f"{stem}.bin"
        output_json = train_dir / f"{stem}.json"
        mm = np.memmap(source_bin, dtype=dtype, mode="r", shape=(n_frames, ly, lx))
        out = np.memmap(output_bin, dtype=dtype, mode="w+", shape=(count, ly, lx))
        chunk = 1000
        for offset in range(0, count, chunk):
            stop = min(count, offset + chunk)
            out[offset:stop] = mm[start + offset:start + stop]
        out.flush()
        del out
        metadata = {
            "source_exp_id": exp_id,
            "work_unit": work_unit,
            "plane": plane,
            "channel": "ch2" if bin_name == "data_chan2.bin" else "ch1",
            "source_bin": str(source_bin),
            "source_ops": str(plane_dir / "ops.npy"),
            "start_frame": start,
            "n_frames": count,
            "Ly": ly,
            "Lx": lx,
            "dtype": str(dtype),
        }
        output_json.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"** Extracted {output_bin}")
    write_build_config(config)


def build_model(config_path: Union[str, Path]) -> None:
    config = read_build_config(config_path)
    params = dict(default_train_params())
    params.update(config.get("train_params", {}))
    model_root = Path(config["model_root"])
    cmd = [
        "/opt/scripts/conda-run.sh",
        str(params["env"]),
        "python",
        str(SRDTRANS_REPO / "train.py"),
        "--datasets_path",
        str(model_root),
        "--datasets_folder",
        "train_data",
        "--pth_path",
        str(model_root / "pth"),
        "--output_path",
        str(model_root / "results"),
        "--n_epochs",
        str(int(params["n_epochs"])),
        "--patch_x",
        str(int(params["patch_x"])),
        "--patch_t",
        str(int(params["patch_t"])),
        "--overlap_factor",
        str(float(params["overlap_factor"])),
        "--train_datasets_size",
        str(int(params["train_datasets_size"])),
        "--lr",
        str(float(params["lr"])),
        "--GPU",
        str(params["gpu"]),
    ]
    print("** Building SRDTrans model")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(SRDTRANS_REPO))


def run_subcommand_from_config(action: str, config_path: Union[str, Path]) -> None:
    if action == "register":
        register_experiments(config_path)
    elif action == "extract":
        extract_training_frames(config_path)
    elif action == "build":
        build_model(config_path)
    else:
        raise ValueError(f"Unknown SRDTrans build action: {action}")


def command_for_action(action: str, config_path: Union[str, Path], env: Optional[str] = None) -> list[str]:
    if action == "register":
        env = env or "suite2p"

    app_path = Path(__file__).resolve().parents[3] / "apps" / "srdtrans_build.py"
    if action in {"extract", "build"}:
        return [sys.executable, str(app_path), action, str(config_path)]
    return ["/opt/scripts/conda-run.sh", str(env), "python", str(app_path), action, str(config_path)]


def remove_registered_outputs(config_path: Union[str, Path]) -> None:
    config = read_build_config(config_path)
    root = Path(config["fast_build_root"]) / "registered"
    if root.exists():
        shutil.rmtree(root)
