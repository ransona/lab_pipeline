import inspect
import logging
import os
import re
import sys
from importlib import metadata as importlib_metadata
from typing import Optional

import numpy as np
import suite2p
from suite2p import io as suite2p_io
from suite2p.run_s2p import run_plane as suite2p_run_plane
from suite2p.registration import register as suite2p_register

from preprocess_pipeline.shared import suite2p_npy


class Suite2pProgressNoiseFilter(logging.Filter):
    """Drop high-frequency Suite2p ROI candidate progress messages."""

    _noisy_patterns = (
        re.compile(r"^ROIs:\s*\d+,\s*candidates:\s*\d+", re.IGNORECASE),
        re.compile(r"^ROIs:\s*\d+,\s*last score:", re.IGNORECASE),
        re.compile(r"current peak score:.*minimum peak score:", re.IGNORECASE),
        re.compile(r"size rejected:", re.IGNORECASE),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().strip()
        return not any(pattern.search(message) for pattern in self._noisy_patterns)


def ensure_suite2p_console_logging() -> None:
    """Attach Suite2p API logger output to stderr for queue log capture."""
    s2p_logger = logging.getLogger("suite2p")
    s2p_logger.setLevel(logging.DEBUG)
    for handler in s2p_logger.handlers:
        if getattr(handler, "_lab_pipeline_console", False):
            if not any(isinstance(item, Suite2pProgressNoiseFilter) for item in handler.filters):
                handler.addFilter(Suite2pProgressNoiseFilter())
            return

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    handler.addFilter(Suite2pProgressNoiseFilter())
    handler._lab_pipeline_console = True
    s2p_logger.addHandler(handler)


def _version_major(version_text: str) -> Optional[int]:
    match = re.match(r"^\s*(\d+)(?:\.|$)", str(version_text))
    if not match:
        return None
    return int(match.group(1))


def suite2p_version() -> str:
    for attr in ("version", "__version__"):
        value = getattr(suite2p, attr, None)
        if value is None or callable(value):
            continue
        version_text = str(value).strip()
        if _version_major(version_text) is not None:
            return version_text
    try:
        return importlib_metadata.version("suite2p")
    except importlib_metadata.PackageNotFoundError:
        return "unknown"


def suite2p_has_settings_api() -> bool:
    try:
        signature = inspect.signature(suite2p.run_s2p)
    except (TypeError, ValueError):
        return False
    return "settings" in signature.parameters


def is_suite2p_1x() -> bool:
    return _version_major(suite2p_version()) == 1 or suite2p_has_settings_api()


REQUIRED_1X_SETTINGS_SECTIONS = (
    "run",
    "io",
    "registration",
    "detection",
    "classification",
    "extraction",
    "dcnv_preprocess",
)


def validate_suite2p_1x_config(config: dict, source: str = "Suite2p config") -> None:
    """Require native Suite2p 1.x nested settings and reject legacy flat ops."""
    missing = [
        key
        for key in REQUIRED_1X_SETTINGS_SECTIONS
        if not isinstance(config.get(key), dict)
    ]
    if missing:
        raise ValueError(
            f"{source} is not a native Suite2p 1.x config/output ops file. "
            f"Missing nested settings section(s): {', '.join(missing)}. "
            "Do not use legacy flat Suite2p ops files with the Suite2p 1.x pipeline; "
            "open/save the config in the new Suite2p version first."
        )
    for key in ("fs", "tau", "diameter"):
        if key not in config:
            raise ValueError(
                f"{source} is missing required Suite2p 1.x setting '{key}'. "
                "Use an ops/settings file created by the new Suite2p version."
            )


def _suite2p_1x_settings_keys() -> set[str]:
    from suite2p.parameters import default_settings

    return set(default_settings().keys())


def _suite2p_1x_db_keys() -> set[str]:
    from suite2p.parameters import default_db

    return set(default_db().keys())


def split_suite2p_1x_config(config: dict, db: Optional[dict] = None) -> tuple[dict, dict]:
    """Split a native Suite2p 1.x ops/settings dict into db and settings dicts."""
    validate_suite2p_1x_config(config)
    settings_keys = _suite2p_1x_settings_keys()
    db_keys = _suite2p_1x_db_keys()

    settings_out = {key: config[key] for key in settings_keys if key in config}
    db_out = {key: config[key] for key in db_keys if key in config}

    if db:
        db_out.update(db)

    save_path = db_out.get("save_path") or config.get("save_path")
    if save_path:
        db_out.setdefault("save_path", save_path)
        db_out.setdefault("db_path", os.path.join(save_path, "db.npy"))
        db_out.setdefault("settings_path", os.path.join(save_path, "settings.npy"))

    settings_out.setdefault("io", {})
    settings_out["io"]["save_ops_orig"] = True
    return db_out, settings_out


def run_s2p_compat(ops: dict, db: dict):
    ensure_suite2p_console_logging()
    if not is_suite2p_1x():
        return suite2p.run_s2p(ops=ops, db=db)
    db_out, settings_out = split_suite2p_1x_config(ops, db)
    return suite2p.run_s2p(db=db_out, settings=settings_out)


def _plane_db_settings_from_ops(plane_ops: dict) -> tuple[dict, dict]:
    db, settings = split_suite2p_1x_config(plane_ops)
    for key in [
        "save_path",
        "db_path",
        "settings_path",
        "reg_file",
        "reg_file_chan2",
        "raw_file",
        "raw_file_chan2",
        "nframes",
        "Ly",
        "Lx",
        "frames_per_folder",
        "frames_per_file",
        "meanImg",
        "iplane",
        "iroi",
    ]:
        if key in plane_ops:
            db[key] = plane_ops[key]
    save_path = db.get("save_path") or plane_ops.get("save_path")
    if save_path:
        db["save_path"] = save_path
        # Plane ops can carry db/settings paths from the canonical registration
        # plane. Extraction into ch2 or another save root must write metadata
        # beside that plane's own outputs or Suite2p combined() cannot reload it.
        db["db_path"] = os.path.join(save_path, "db.npy")
        db["settings_path"] = os.path.join(save_path, "settings.npy")
    settings["io"]["save_ops_orig"] = True
    return db, settings


def run_plane_compat(plane_ops: dict) -> dict:
    ensure_suite2p_console_logging()
    if not is_suite2p_1x():
        result = suite2p_run_plane(plane_ops)
        if "ops_path" not in result and result.get("save_path"):
            result["ops_path"] = os.path.join(result["save_path"], "ops.npy")
        return result

    db, settings = _plane_db_settings_from_ops(plane_ops)
    save_path = db["save_path"]
    os.makedirs(save_path, exist_ok=True)
    suite2p_npy.save_object_npy(db["db_path"], db)
    suite2p_npy.save_object_npy(db["settings_path"], settings)
    suite2p_run_plane(db=db, settings=settings)
    ops_path = plane_ops.get("ops_path") or os.path.join(save_path, "ops.npy")
    result = suite2p_npy.load_object_dict(ops_path)
    result.setdefault("ops_path", ops_path)
    result.setdefault("save_path", save_path)
    if db.get("save_path0") is not None:
        result.setdefault("save_path0", db["save_path0"])
    for key in ("db_path", "settings_path", "reg_file", "reg_file_chan2", "raw_file", "raw_file_chan2"):
        if db.get(key) is not None:
            result.setdefault(key, db[key])
    return result


def binary_file(Ly: int, Lx: int, filename: str, n_frames: Optional[int] = None, write: bool = False):
    if is_suite2p_1x():
        return suite2p_io.BinaryFile(Ly=Ly, Lx=Lx, filename=filename, n_frames=n_frames, write=write)
    return suite2p_io.BinaryFile(Ly=Ly, Lx=Lx, filename=filename, n_frames=n_frames)


def registration_wrapper_compat(binary, ops: dict) -> dict:
    ensure_suite2p_console_logging()
    if not is_suite2p_1x():
        return suite2p_register.registration_wrapper(binary, ops=ops)
    _, settings = split_suite2p_1x_config(ops)
    registration_settings = settings.get("registration", settings)
    device = torch_device_for_1x(settings)
    return suite2p_register.registration_wrapper(
        binary,
        align_by_chan2=bool(registration_settings.get("align_by_chan2", ops.get("align_by_chan2", False))),
        save_path=ops.get("save_path"),
        aspect=float(ops.get("aspect", 1.0)),
        settings=registration_settings,
        device=device,
    )


def add_registration_metrics_compat(binary, ops: dict, registration_outputs: dict) -> dict:
    """Add Suite2p GUI registration metrics to manual registration outputs when requested."""
    if not is_suite2p_1x():
        return registration_outputs
    if {"tPC", "regPC", "regDX"}.issubset(registration_outputs):
        return registration_outputs

    _, settings = split_suite2p_1x_config(ops)
    registration_settings = settings.get("registration", {})
    do_regmetrics = registration_settings.get(
        "do_regmetrics",
        settings.get("run", {}).get("do_regmetrics", True),
    )
    n_frames = int(binary.shape[0])
    if not do_regmetrics or n_frames < 1500:
        return registration_outputs

    yrange = registration_outputs.get("yrange")
    xrange = registration_outputs.get("xrange")
    device = torch_device_for_1x(settings)
    from suite2p import registration as suite2p_registration

    logging.getLogger("suite2p").info(
        "----------- Starting registration metrics calculation (%s frames, device=%s)",
        n_frames,
        device,
    )
    tPC, regPC, regDX = suite2p_registration.get_pc_metrics(
        binary,
        yrange=yrange,
        xrange=xrange,
        settings=registration_settings,
        device=device,
    )
    outputs = dict(registration_outputs)
    outputs["tPC"] = tPC
    outputs["regPC"] = regPC
    outputs["regDX"] = regDX
    return outputs


def merge_registration_outputs(ops: dict, registration_outputs: dict) -> dict:
    merged = dict(ops)
    if not is_suite2p_1x() and hasattr(suite2p_register, "save_registration_outputs_to_ops"):
        return suite2p_register.save_registration_outputs_to_ops(registration_outputs, merged)
    merged.update(registration_outputs)
    return merged


def _blocks_for_1x_nonrigid_offsets(ops: dict, yoff1, xoff1):
    if yoff1 is None or xoff1 is None:
        return None
    if ops.get("blocks") is not None:
        return ops["blocks"]

    from suite2p.registration import nonrigid

    block_size = ops.get("block_size", (128, 128))
    _, settings = split_suite2p_1x_config(ops)
    registration_settings = settings.get("registration", {})
    block_size = registration_settings.get("block_size", block_size)
    subpixel = int(registration_settings.get("subpixel", ops.get("subpixel", 10)))
    return nonrigid.make_blocks(
        int(ops["Ly"]),
        int(ops["Lx"]),
        block_size,
        subpixel=subpixel,
    )


def torch_device_for_1x(settings: dict):
    from suite2p.run_s2p import _assign_torch_device

    return _assign_torch_device(settings.get("torch_device", "cuda"))


def shift_frames_and_write_compat(binary, yoff, xoff, yoff1, xoff1, ops: dict):
    if not is_suite2p_1x():
        return suite2p_register.shift_frames_and_write(
            binary,
            yoff=yoff,
            xoff=xoff,
            yoff1=yoff1,
            xoff1=xoff1,
            ops=ops,
        )
    blocks = _blocks_for_1x_nonrigid_offsets(ops, yoff1, xoff1)
    if blocks is not None:
        ops["blocks"] = blocks
    _, settings = split_suite2p_1x_config(ops)
    device = torch_device_for_1x(settings)
    return suite2p_register.shift_frames_and_write(
        binary,
        batch_size=int(ops.get("batch_size", 100)),
        yoff=yoff,
        xoff=xoff,
        yoff1=yoff1,
        xoff1=xoff1,
        blocks=blocks,
        bidiphase=int(ops.get("bidiphase", 0)),
        device=device,
    )


def enhanced_mean_image(mean_img, ops: dict):
    if not is_suite2p_1x() and hasattr(suite2p_register, "compute_enhanced_mean_image"):
        return suite2p_register.compute_enhanced_mean_image(mean_img, ops)
    from suite2p.registration import utils as registration_utils

    return registration_utils.highpass_mean_image(
        mean_img.astype("float32"),
        aspect=float(ops.get("aspect", 1.0)),
    )
