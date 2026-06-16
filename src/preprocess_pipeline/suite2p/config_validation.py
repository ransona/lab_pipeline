import importlib
import sys

import numpy as np


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


def install_numpy_core_pickle_aliases():
    """Allow NumPy 1.x envs to inspect NumPy 2.x-authored .npy configs."""
    for module_name in (
        "numpy.core",
        "numpy.core.multiarray",
        "numpy.core.numeric",
        "numpy.core.umath",
        "numpy.core._multiarray_umath",
    ):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        alias = module_name.replace("numpy.core", "numpy._core", 1)
        sys.modules.setdefault(alias, module)


def load_suite2p_config_for_validation(config_path):
    install_numpy_core_pickle_aliases()
    try:
        config = np.load(config_path, allow_pickle=True).item()
    except ModuleNotFoundError as exc:
        if str(exc).startswith("No module named 'numpy._core"):
            return {"__native_suite2p_1x_pickle__": True}
        raise
    if not isinstance(config, dict):
        raise ValueError(f"Suite2p config is not a dict: {config_path}")
    return config


def is_native_suite2p_1x_config(config_path):
    config = load_suite2p_config_for_validation(config_path)
    if config.get("__native_suite2p_1x_pickle__"):
        return True
    return all(isinstance(config.get(key), dict) for key in SUITE2P_1X_SETTINGS_SECTIONS)


def validate_suite2p_env(suite2p_env, *, context="step1_config"):
    if not isinstance(suite2p_env, str) or not suite2p_env.strip():
        raise ValueError(
            f'{context}["suite2p_env"] is required. '
            'Use "suite2p" for the legacy Suite2p env or "suite2p_1.1.0" for native Suite2p 1.x configs.'
        )
    if suite2p_env not in KNOWN_SUITE2P_ENVS:
        raise ValueError(
            f'Unknown suite2p_env "{suite2p_env}". Known values: '
            + ", ".join(sorted(KNOWN_SUITE2P_ENVS))
        )


def validate_suite2p_env_config_compatibility(suite2p_env, config_paths, *, context="step1_config"):
    validate_suite2p_env(suite2p_env, context=context)
    if suite2p_env != "suite2p":
        return

    if isinstance(config_paths, (str, bytes)):
        paths = str(config_paths).split(",")
    else:
        paths = list(config_paths)

    for path in paths:
        if is_native_suite2p_1x_config(path):
            raise ValueError(
                f"Cannot run native Suite2p 1.x config with legacy suite2p env: {path}. "
                'Set suite2p_env to "suite2p_1.1.0".'
            )
