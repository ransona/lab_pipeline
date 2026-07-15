import json
import os
import subprocess
import sys
from pathlib import Path

from preprocess_pipeline.shared import suite2p_npy


KNOWN_SUITE2P_ENVS = {"suite2p", "suite2p_1.1.0"}
SUITE2P_1X_SETTINGS_SECTIONS = {
    "run",
    "io",
    "registration",
    "detection",
    "classification",
    "extraction",
    "dcnv_preprocess",
}


def _raise_suite2p_config_error(message):
    print("** Suite2p configuration error")
    print(message)
    raise ValueError(message)


def install_numpy_core_pickle_aliases():
    """Allow NumPy 1.x envs to inspect NumPy 2.x-authored .npy configs."""
    suite2p_npy.install_numpy_core_pickle_aliases()


def load_suite2p_config_for_validation(config_path):
    try:
        config = suite2p_npy.load_object_dict(config_path)
    except ModuleNotFoundError as exc:
        if str(exc).startswith("No module named 'numpy._core"):
            return {"__native_suite2p_1x_pickle__": True}
        raise
    return config


def is_native_suite2p_1x_config(config_path):
    config = load_suite2p_config_for_validation(config_path)
    if config.get("__native_suite2p_1x_pickle__"):
        return True
    return suite2p_npy.is_suite2p_1x_payload(config)


def _conda_executable():
    conda_exe = os.environ.get("CONDA_EXE")
    if conda_exe and os.path.exists(conda_exe):
        return conda_exe

    candidates = []
    try:
        candidates.append(Path(sys.executable).parents[2] / "Scripts" / "conda.exe")
        candidates.append(Path(sys.executable).parents[2] / "bin" / "conda")
    except IndexError:
        pass
    candidates.append(Path.home() / "miniconda3" / "bin" / "conda")
    candidates.append(Path.home() / "miniconda3" / "Scripts" / "conda.exe")
    candidates.append(Path.home() / "anaconda3" / "bin" / "conda")
    candidates.append(Path.home() / "anaconda3" / "Scripts" / "conda.exe")

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "conda"


def _conda_env_exists(env_name):
    try:
        result = subprocess.run(
            [_conda_executable(), "env", "list", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False

    for env_path in payload.get("envs", []):
        if Path(env_path).name == env_name:
            return True
    return False


def validate_suite2p_env(suite2p_env, *, context="step1_config"):
    if not isinstance(suite2p_env, str) or not suite2p_env.strip():
        _raise_suite2p_config_error(
            f'{context}["suite2p_env"] is required. '
            'No Suite2p conda environment was specified. '
            'Use "suite2p" for legacy Suite2p configs, "suite2p_1.1.0" for server native '
            'Suite2p 1.x configs, or another existing conda environment name.'
        )
    suite2p_env = suite2p_env.strip()
    if suite2p_env not in KNOWN_SUITE2P_ENVS and not _conda_env_exists(suite2p_env):
        _raise_suite2p_config_error(
            f'{context}["suite2p_env"] is "{suite2p_env}", but no conda environment with that name was found. '
            "Create the environment or choose an existing Suite2p environment."
        )


def validate_suite2p_env_config_compatibility(suite2p_env, config_paths, *, context="step1_config"):
    validate_suite2p_env(suite2p_env, context=context)
    suite2p_env = suite2p_env.strip()
    if suite2p_env != "suite2p":
        return

    if isinstance(config_paths, (str, bytes)):
        paths = str(config_paths).split(",")
    else:
        paths = list(config_paths)

    for path in paths:
        if is_native_suite2p_1x_config(path):
            _raise_suite2p_config_error(
                f'Suite2p env/config mismatch. {context}["suite2p_env"] is "suite2p" '
                f"(legacy Suite2p), but the selected config is a native Suite2p 1.x config: {path}. "
                'Set suite2p_env to "suite2p_1.1.0" or choose a legacy Suite2p ops file.'
            )
