"""Compatibility helpers for Suite2p object ``.npy`` files.

Suite2p ops/stat/settings files are NumPy object arrays, so ``np.save`` uses
pickle internally. NumPy 2-authored pickles may not load in NumPy 1.x. For
legacy Suite2p files, keep writes in a NumPy 1.x process so old Suite2p can
continue to read them.
"""

from __future__ import annotations

import datetime as _datetime
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

import numpy as np


NUMPY1_ENV = os.environ.get("LAB_PIPELINE_NUMPY1_ENV", "numpy1.x")
CONDA_RUN = os.environ.get("LAB_PIPELINE_CONDA_RUN", "/opt/scripts/conda-run.sh")
SUITE2P_OBJECT_FILENAMES = {
    "ops.npy",
    "stat.npy",
    "db.npy",
    "settings.npy",
    "detect_outputs.npy",
    "reg_outputs.npy",
}
SUITE2P_1X_SETTINGS_SECTIONS = {
    "run",
    "io",
    "registration",
    "detection",
    "classification",
    "extraction",
    "dcnv_preprocess",
}


def current_numpy_major() -> int:
    return int(np.__version__.split(".", 1)[0])


def current_conda_env() -> str:
    return os.environ.get("CONDA_DEFAULT_ENV", Path(sys.prefix).name)


def install_numpy_core_pickle_aliases() -> None:
    """Allow NumPy 1.x processes to read some NumPy 2-authored object files."""
    aliases = (
        "numpy.core",
        "numpy.core.multiarray",
        "numpy.core.numeric",
        "numpy.core.umath",
        "numpy.core._multiarray_umath",
        "numpy.core.fromnumeric",
        "numpy.core.shape_base",
        "numpy.core._methods",
    )
    for module_name in aliases:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        alias = module_name.replace("numpy.core", "numpy._core", 1)
        sys.modules.setdefault(alias, module)


def inspect_numpy_pickle_flavor(path: str | os.PathLike[str]) -> str:
    """Return ``numpy1``, ``numpy2``, or ``unknown`` from pickle module refs."""
    try:
        payload = Path(path).read_bytes()
    except OSError:
        return "unknown"
    if b"numpy._core" in payload:
        return "numpy2"
    if b"numpy.core" in payload:
        return "numpy1"
    return "unknown"


def load_npy_compat(path: str | os.PathLike[str], **kwargs):
    install_numpy_core_pickle_aliases()
    return np.load(path, **kwargs)


def load_object_npy(path: str | os.PathLike[str]):
    return load_npy_compat(path, allow_pickle=True)


def load_object_dict(path: str | os.PathLike[str]) -> dict:
    value = load_object_npy(path).item()
    if not isinstance(value, dict):
        raise TypeError(f"Expected {path} to contain a dict, got {type(value).__name__}")
    return value


def is_suite2p_object_path(path: str | os.PathLike[str]) -> bool:
    return Path(path).name in SUITE2P_OBJECT_FILENAMES


def is_suite2p_1x_payload(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(value.get(key), dict) for key in SUITE2P_1X_SETTINGS_SECTIONS
    )


def is_legacy_suite2p_payload(value: Any) -> bool:
    if is_suite2p_1x_payload(value):
        return False
    if isinstance(value, dict):
        legacy_keys = {
            "Ly",
            "Lx",
            "nframes",
            "meanImg",
            "ops_path",
            "reg_file",
            "functional_chan",
            "diameter",
            "threshold_scaling",
        }
        return bool(legacy_keys.intersection(value))
    return False


def classify_suite2p_npy(path: str | os.PathLike[str], value: Any | None = None) -> str:
    """Return ``legacy``, ``native1x``, or ``unknown`` for a Suite2p object file."""
    path = Path(path)
    if value is None and path.exists():
        try:
            value = load_object_npy(path)
            if isinstance(value, np.ndarray) and value.shape == ():
                value = value.item()
        except Exception:
            value = None

    if is_suite2p_1x_payload(value):
        return "native1x"
    if is_legacy_suite2p_payload(value):
        return "legacy"

    if path.name != "ops.npy":
        ops_path = path.with_name("ops.npy")
        if ops_path.exists() and ops_path != path:
            return classify_suite2p_npy(ops_path)

    flavor = inspect_numpy_pickle_flavor(path)
    if flavor == "numpy1":
        return "legacy"
    if flavor == "numpy2":
        return "native1x"
    return "unknown"


def _encode_jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        if value.dtype == object:
            data = [_encode_jsonable(item) for item in value.tolist()]
        else:
            data = value.tolist()
        return {
            "__ndarray__": True,
            "dtype": str(value.dtype),
            "shape": list(value.shape),
            "data": data,
        }
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _encode_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return {"__tuple__": [_encode_jsonable(item) for item in value]}
    if isinstance(value, list):
        return [_encode_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, _datetime.datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, _datetime.date):
        return {"__date__": value.isoformat()}
    if isinstance(value, _datetime.time):
        return {"__time__": value.isoformat()}
    return value


def save_object_npy(path: str | os.PathLike[str], value: Any, *, suite2p_flavor: str | None = None) -> None:
    """Save an object ``.npy`` while preserving legacy Suite2p compatibility."""
    path = Path(path)
    flavor = suite2p_flavor or classify_suite2p_npy(path, value)
    if flavor == "legacy" and current_numpy_major() >= 2 and current_conda_env() != NUMPY1_ENV:
        save_object_npy_with_numpy1(path, value)
        return
    np.save(path, value)


def save_object_npy_with_numpy1(path: Path, value: Any) -> None:
    app_path = Path(__file__).resolve().parents[3] / "apps" / "numpy1_npy_worker.py"
    request = {
        "action": "save",
        "path": str(path),
        "value": _encode_jsonable(value),
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(request, handle)
        request_path = handle.name
    try:
        cmd = [CONDA_RUN, NUMPY1_ENV, "python", str(app_path), request_path]
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Cannot write legacy Suite2p object file with NumPy 1.x because {CONDA_RUN!r} was not found."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Cannot write legacy Suite2p object file with NumPy 1.x env {NUMPY1_ENV!r}: {path}"
        ) from exc
    finally:
        try:
            os.unlink(request_path)
        except OSError:
            pass
