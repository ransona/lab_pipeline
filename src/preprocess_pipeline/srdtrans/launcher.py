from __future__ import annotations

import base64
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[3]
SRDTRANS_REPO = Path("/home/adamranson/code/SRDTrans")
SRDTRANS_TEST = SRDTRANS_REPO / "test.py"
PATCH_PROGRESS_RE = re.compile(
    r"^\[Model (?P<model>[^\]]+)\] \[Stack (?P<stack>[^\]]+)\] "
    r"\[Patch (?P<patch>\d+)/(?P<total>\d+)\] "
    r"\[Time Cost: (?P<time>[^\]]+)\] \[ETA: (?P<eta>[^\]]+)\]"
)


def _load_model_patch_shape(model_root: Path, model_name: str) -> Tuple[int, int]:
    para_path = model_root / model_name / "para.yaml"
    if not para_path.exists():
        raise FileNotFoundError(f"SRDTrans model para.yaml not found: {para_path}")
    text = para_path.read_text()
    patch_x_match = re.search(r"^patch_x:\s*([0-9]+)\s*$", text, re.MULTILINE)
    patch_t_match = re.search(r"^patch_t:\s*([0-9]+)\s*$", text, re.MULTILINE)
    if not patch_x_match or not patch_t_match:
        raise ValueError(f"Could not parse patch_x/patch_t from {para_path}")
    return int(patch_x_match.group(1)), int(patch_t_match.group(1))


def encode_config_arg(config: dict) -> str:
    payload = json.dumps(config, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decode_config_arg(raw: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _normalize_config(config: Optional[dict]) -> dict:
    cfg = dict(config or {})
    cfg.setdefault("env", "srdtrans")
    cfg.setdefault("repo_root", str(SRDTRANS_REPO))
    cfg.setdefault("model_root", "/home/adamranson/data/srt_models")
    cfg.setdefault("overlap_factor", 0.5)
    cfg.setdefault("gpu", "0,1")
    cfg.setdefault("cleanup", True)
    model_root = cfg.get("model_root")
    model = cfg.get("model")
    if not model_root or not model:
        raise ValueError("SRDTrans config requires model_root and model")
    if "patch_x" not in cfg or "patch_t" not in cfg:
        patch_x, patch_t = _load_model_patch_shape(Path(model_root), str(model))
        cfg.setdefault("patch_x", patch_x)
        cfg.setdefault("patch_t", patch_t)
    return cfg


def _run_with_filtered_output(cmd: list[str], progress_interval: int = 1000) -> None:
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    last_report_by_key: dict[tuple[str, str, int], int] = {}
    for raw_line in process.stdout:
        line = raw_line.rstrip("\r\n")
        match = PATCH_PROGRESS_RE.match(line)
        if match:
            patch = int(match.group("patch"))
            total = int(match.group("total"))
            key = (match.group("model"), match.group("stack"), total)
            should_report = patch == 1 or patch == total or patch % progress_interval == 0
            if not should_report and patch - last_report_by_key.get(key, 0) < progress_interval:
                continue
            last_report_by_key[key] = patch
            print(
                f"[SRDTrans] {match.group('model')} {match.group('stack')} "
                f"patch {patch}/{total} time {match.group('time')} ETA {match.group('eta')}",
                flush=True,
            )
            continue
        if line:
            print(line, flush=True)
    return_code = process.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)


def denoise_binary_inplace(plane_dir: str, input_filename: str, config: Optional[dict] = None) -> None:
    cfg = _normalize_config(config)
    plane_path = Path(plane_dir)
    source_bin = plane_path / input_filename
    if not source_bin.exists():
        raise FileNotFoundError(f"SRDTrans input binary not found: {source_bin}")

    ops_path = plane_path / "ops.npy"
    if not ops_path.exists():
        raise FileNotFoundError(f"SRDTrans requires ops.npy next to binary: {ops_path}")

    repo_root = Path(cfg["repo_root"])
    test_py = repo_root / "test.py"
    if not test_py.exists():
        raise FileNotFoundError(f"SRDTrans test.py not found: {test_py}")

    scratch_root = Path(tempfile.mkdtemp(prefix=f"srdtrans_{source_bin.stem}_", dir=plane_path))
    input_root = scratch_root / "input"
    output_root = scratch_root / "output"
    input_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    staged_bin = input_root / input_filename
    staged_ops = input_root / "ops.npy"
    _link_or_copy(source_bin, staged_bin)
    shutil.copy2(ops_path, staged_ops)

    cmd = [
        "/opt/scripts/conda-run.sh",
        str(cfg["env"]),
        "python",
        str(test_py),
        "--datasets_path",
        str(scratch_root),
        "--datasets_folder",
        "input",
        "--pth_path",
        str(cfg["model_root"]),
        "--denoise_model",
        str(cfg["model"]),
        "--output_path",
        str(output_root),
        "--output_format",
        "bin",
        "--patch_x",
        str(int(cfg["patch_x"])),
        "--patch_t",
        str(int(cfg["patch_t"])),
        "--overlap_factor",
        str(float(cfg["overlap_factor"])),
        "--GPU",
        str(cfg["gpu"]),
    ]
    _run_with_filtered_output(cmd, int(cfg.get("progress_interval", 1000)))

    matches = glob.glob(str(output_root / "**" / input_filename), recursive=True)
    if len(matches) != 1:
        raise FileNotFoundError(
            f"Expected exactly one SRDTrans output named {input_filename} under {output_root}, found {matches}"
        )

    result_bin = Path(matches[0])
    replacement = plane_path / f"{input_filename}.srdtrans_tmp"
    if replacement.exists():
        replacement.unlink()
    shutil.move(str(result_bin), replacement)
    os.replace(replacement, source_bin)

    if cfg.get("cleanup", True):
        shutil.rmtree(scratch_root, ignore_errors=True)


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: srdtrans_launcher.py <plane_dir> <input_filename> [json_config]"
        )
    plane_dir = sys.argv[1]
    input_filename = sys.argv[2]
    config = decode_config_arg(sys.argv[3]) if len(sys.argv) > 3 else {}
    denoise_binary_inplace(plane_dir, input_filename, config)


if __name__ == "__main__":
    main()
