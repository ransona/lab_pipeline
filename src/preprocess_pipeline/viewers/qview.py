import getpass
import ast
import contextlib
import json
import os
import pickle
import re
import sys
import traceback
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import tifffile
from PyQt6 import QtCore, QtGui, QtWidgets
from scipy.io import loadmat

from preprocess_pipeline.shared import paths
from preprocess_pipeline.step1 import split_combined_s2p
from preprocess_pipeline.step1.run_batch import run_step1_batch_universal
from preprocess_pipeline.step2.run_batch import run_step2_batch


NORMAL_QUEUE_DIRECTORY = Path("/data/common/queues/step1")
DEBUG_QUEUE_DIRECTORY = Path("/data/common/queues/debug")
QUEUE_REFRESH_MS = 1000
PRIORITY_REFRESH_MS = 2000
USER_TOTALS_REFRESH_MS = 2000
LOG_REFRESH_MS = 1000
MAX_LOG_LINES = 10000
INITIAL_LOG_LINES = 10000
S2P_CONFIG_ROOT = Path("/data/common/configs/s2p_configs")
CONFIG_ROOT = S2P_CONFIG_ROOT.parent


def _step1_preset_root(username: str) -> Path:
    return CONFIG_ROOT / "step1_configs" / username


def _step2_preset_root(username: str) -> Path:
    return CONFIG_ROOT / "step2_configs" / username


def _ensure_preset_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _safe_preset_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("._")


def _queue_listener_log_path(queue_directory: Path) -> Path:
    return queue_directory / "qlistener-log.txt"


def _read_tail_lines(path: Path, max_lines: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.readlines()[-max_lines:]


def _parse_channel_count(value) -> int:
    if value is None:
        return 1
    if isinstance(value, (list, tuple)):
        return max(1, len(value))
    if hasattr(value, "tolist"):
        try:
            converted = value.tolist()
            return _parse_channel_count(converted)
        except Exception:
            pass
    if isinstance(value, str):
        numbers = re.findall(r"\d+", value)
        return max(1, len(numbers)) if numbers else 1
    try:
        return 1 if int(value) > 0 else 1
    except Exception:
        return 1


@dataclass
class StandardMetadata:
    nplanes: Optional[int]
    nchannels: int
    scan_frame_rate: Optional[float]
    fs: Optional[float]
    tif_path: str


@dataclass
class MesoPathMetadata:
    path_name: str
    nplanes: Optional[int]
    nrois: int
    nchannels: int
    scan_frame_rate: Optional[float]
    fs_per_roi: Optional[float]
    roi_names: list[str]


@dataclass
class ExperimentDescriptor:
    exp_id: str
    topology: str
    nchannels: int
    summary: str
    work_units: list[str]
    per_path: OrderedDict[str, MesoPathMetadata]
    standard: Optional[StandardMetadata] = None


def _read_scanimage_frame_data_from_tiff(tif_path: str) -> dict:
    with tifffile.TiffFile(tif_path) as tif:
        si_meta = getattr(tif, "scanimage_metadata", None)
        if isinstance(si_meta, dict):
            frame_data = si_meta.get("FrameData")
            if isinstance(frame_data, dict):
                return frame_data
    return {}


def _infer_nplanes_from_frame_data(frame_data: dict) -> Optional[int]:
    for key in (
        "SI.hStackManager.numFramesPerVolume",
        "SI.hStackManager.actualNumSlices",
        "SI.hStackManager.numSlices",
    ):
        value = frame_data.get(key)
        try:
            candidate = int(value)
        except Exception:
            continue
        if candidate > 0:
            return candidate
    return None


def _infer_standard_metadata(exp_dir_raw: str) -> StandardMetadata:
    tif_candidates = sorted(Path(exp_dir_raw).glob("*.tif"))
    if not tif_candidates:
        raise FileNotFoundError(f"No TIFFs found in standard experiment root: {exp_dir_raw}")
    tif_path = str(tif_candidates[0])
    frame_data = _read_scanimage_frame_data_from_tiff(tif_path)
    nplanes = _infer_nplanes_from_frame_data(frame_data)
    nchannels = _parse_channel_count(frame_data.get("SI.hChannels.channelSave"))
    scan_frame_rate = frame_data.get("SI.hRoiManager.scanFrameRate")
    try:
        scan_frame_rate = float(scan_frame_rate) if scan_frame_rate is not None else None
    except Exception:
        scan_frame_rate = None
    fs = None
    if scan_frame_rate is not None and nplanes and nplanes > 0:
        fs = scan_frame_rate / float(nplanes)
    return StandardMetadata(
        nplanes=nplanes,
        nchannels=nchannels,
        scan_frame_rate=scan_frame_rate,
        fs=fs,
        tif_path=tif_path,
    )


def _load_meso_header(scanpath_root: Path) -> dict:
    si_meta_path = scanpath_root / "SI_meta.pickle"
    if not si_meta_path.exists():
        raise FileNotFoundError(f"Missing mesoscope sidecar: {si_meta_path}")
    with si_meta_path.open("rb") as handle:
        data = pickle.load(handle)
    meta1 = data.get("Meta1")
    if isinstance(meta1, (list, tuple)) and meta1:
        header = meta1[0]
    elif isinstance(meta1, dict):
        header = meta1
    else:
        raise ValueError(f"Unexpected Meta1 format in {si_meta_path}")
    if not isinstance(header, dict):
        raise ValueError(f"Unexpected mesoscope header type in {si_meta_path}: {type(header)}")
    return header


def _infer_meso_descriptor(exp_dir_raw: str, exp_id: str) -> ExperimentDescriptor:
    root = Path(exp_dir_raw)
    per_path: OrderedDict[str, MesoPathMetadata] = OrderedDict()
    work_units: list[str] = []
    global_nchannels = 1

    for scanpath_root in sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("P")):
        header = _load_meso_header(scanpath_root)
        roi_names = sorted(
            roi.name
            for roi in scanpath_root.iterdir()
            if roi.is_dir() and roi.name.startswith("R")
        )
        if not roi_names:
            continue
        for roi_name in roi_names:
            work_units.append(f"{scanpath_root.name}/{roi_name}")

        nplanes = _infer_nplanes_from_frame_data(header)
        nchannels = _parse_channel_count(header.get("SI.hChannels.channelSave"))
        global_nchannels = max(global_nchannels, nchannels)
        scan_frame_rate = header.get("SI.hRoiManager.scanFrameRate")
        try:
            scan_frame_rate = float(scan_frame_rate) if scan_frame_rate is not None else None
        except Exception:
            scan_frame_rate = None
        fs_per_roi = None
        if scan_frame_rate is not None and nplanes and nplanes > 0:
            fs_per_roi = scan_frame_rate / float(nplanes) / float(len(roi_names))

        per_path[scanpath_root.name] = MesoPathMetadata(
            path_name=scanpath_root.name,
            nplanes=nplanes,
            nrois=len(roi_names),
            nchannels=nchannels,
            scan_frame_rate=scan_frame_rate,
            fs_per_roi=fs_per_roi,
            roi_names=roi_names,
        )

    path_summaries = []
    for path_name, meta in per_path.items():
        path_summaries.append(
            f"{path_name}: {meta.nrois} ROI(s), {meta.nplanes or '?'} plane(s), {meta.nchannels} channel(s)"
        )
    summary = "Meso | " + "; ".join(path_summaries)
    return ExperimentDescriptor(
        exp_id=exp_id,
        topology="meso",
        nchannels=global_nchannels,
        summary=summary,
        work_units=work_units,
        per_path=per_path,
    )


def describe_experiment(user_id: str, exp_id: str) -> ExperimentDescriptor:
    _, _, _, _, exp_dir_raw = paths.find_paths(user_id, exp_id)
    root = Path(exp_dir_raw)
    is_meso = any(
        scanpath.is_dir()
        and scanpath.name.startswith("P")
        and any(roi.is_dir() and roi.name.startswith("R") for roi in scanpath.iterdir())
        for scanpath in root.iterdir()
    )

    if is_meso:
        return _infer_meso_descriptor(exp_dir_raw, exp_id)

    standard = _infer_standard_metadata(exp_dir_raw)
    summary = (
        f"Standard | {standard.nplanes or '?'} plane(s), "
        f"{standard.nchannels} channel(s), "
        f"scanFrameRate={standard.scan_frame_rate or '?'} Hz, "
        f"fs={standard.fs or '?'} Hz"
    )
    return ExperimentDescriptor(
        exp_id=exp_id,
        topology="standard",
        nchannels=standard.nchannels,
        summary=summary,
        work_units=["root"],
        per_path=OrderedDict(),
        standard=standard,
    )


def _timeline_duration_seconds(user_id: str, exp_id: str) -> Optional[float]:
    _, _, _, _, exp_dir_raw = paths.find_paths(user_id, exp_id)
    timeline_path = Path(exp_dir_raw) / f"{exp_id}_Timeline.mat"
    if not timeline_path.exists():
        return None
    timeline = loadmat(str(timeline_path))["timelineSession"]
    timeline_time = np.squeeze(timeline["time"][0][0])
    if timeline_time.size < 2:
        return None
    return float(timeline_time[-1] - timeline_time[0])


def _combined_suite2p_path(channel_root: str) -> str:
    suite2p_combined_path = os.path.join(channel_root, "suite2p_combined")
    if os.path.isdir(suite2p_combined_path):
        return suite2p_combined_path
    suite2p_path = os.path.join(channel_root, "suite2p")
    if os.path.isdir(suite2p_path):
        return suite2p_path
    raise FileNotFoundError(f"Missing suite2p or suite2p_combined folder: {channel_root}")


def inspect_combined_split_sources(user_id: str, exp_id: str) -> list[dict]:
    _, _, _, exp_dir_processed, _ = paths.find_paths(user_id, exp_id)
    split_roots = split_combined_s2p.discover_split_roots(exp_dir_processed)
    if not split_roots:
        raise FileNotFoundError(f"No Suite2p split roots found under {exp_dir_processed}")

    split_root = split_roots[0]
    channel_root = split_combined_s2p.discover_channel_roots(split_root)[0]
    suite2p_path = _combined_suite2p_path(channel_root)
    plane_dirs = sorted(Path(suite2p_path).glob("plane*"))
    if not plane_dirs:
        raise FileNotFoundError(f"No plane folders found in {suite2p_path}")

    plane0_ops = np.load(plane_dirs[0] / "ops.npy", allow_pickle=True).item()
    layout_mode = split_combined_s2p.infer_layout_mode_from_split_root(split_root)
    source_exp_ids = [
        split_combined_s2p.extract_exp_id_from_data_path(data_path, layout_mode)
        for data_path in plane0_ops["data_path"]
    ]
    frames_per_folder = [int(frame_count) for frame_count in plane0_ops.get("frames_per_folder", [])]

    rows = []
    for index, source_exp_id in enumerate(source_exp_ids):
        duration = _timeline_duration_seconds(user_id, source_exp_id)
        frames = frames_per_folder[index] if index < len(frames_per_folder) else None
        rows.append(
            {
                "source_exp_id": source_exp_id,
                "frames": frames,
                "timeline_seconds": duration,
                "split_root": split_root,
                "suite2p_path": suite2p_path,
                "warnings": [],
            }
        )
    if len(frames_per_folder) != len(source_exp_ids):
        warning = (
            f"metadata mismatch: data_path has {len(source_exp_ids)} source experiment(s), "
            f"but frames_per_folder has {len(frames_per_folder)} value(s)"
        )
        if not rows:
            rows.append(
                {
                    "source_exp_id": "?",
                    "frames": None,
                    "timeline_seconds": None,
                    "split_root": split_root,
                    "suite2p_path": suite2p_path,
                    "warnings": [warning],
                }
            )
        else:
            rows[0]["warnings"].append(warning)
    return rows


class EditableConfigCombo(QtWidgets.QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)

    def value(self) -> str:
        return self.currentText().strip()

    def set_value(self, value: str):
        self.setCurrentText(value or "")


S2P_OPS_GROUPS = [
    ("Main settings", [
        "nplanes", "nchannels", "functional_chan", "tau", "fs", "do_bidiphase",
        "bidiphase", "multiplane_parallel", "ignore_flyback",
    ]),
    ("Output settings", [
        "preclassify", "save_mat", "save_NWB", "combined", "reg_tif",
        "reg_tif_chan2", "aspect", "delete_bin", "move_bin",
    ]),
    ("Registration", [
        "do_registration", "align_by_chan", "nimg_init", "batch_size",
        "smooth_sigma", "smooth_sigma_time", "maxregshift", "th_badframes",
        "keep_movie_raw", "two_step_registration",
    ]),
    ("Nonrigid", ["nonrigid", "block_size", "snr_thresh", "maxregshiftNR"]),
    ("1P", ["1Preg", "spatial_hp_reg", "pre_smooth", "spatial_taper"]),
    ("Functional detect", [
        "roidetect", "sparse_mode", "denoise", "spatial_scale", "connected",
        "threshold_scaling", "max_overlap", "max_iterations", "high_pass",
        "spatial_hp_detect",
    ]),
    ("Anat detect", [
        "anatomical_only", "diameter", "cellprob_threshold", "flow_threshold",
        "pretrained_model", "spatial_hp_cp",
    ]),
    ("Extraction/Neuropil", [
        "neuropil_extract", "allow_overlap", "inner_neuropil_radius",
        "min_neuropil_pixels",
    ]),
    ("Classify/Deconv", [
        "soma_crop", "spikedetect", "win_baseline", "sig_baseline", "neucoeff",
    ]),
]


def _display_ops_value(value) -> str:
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple, dict, bool, int, float)) or value is None:
        return repr(value)
    return str(value)


def _parse_ops_value(text: str, old_value):
    stripped = text.strip()
    if isinstance(old_value, np.ndarray):
        return np.asarray(ast.literal_eval(stripped))
    if isinstance(old_value, bool):
        lowered = stripped.lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
        raise ValueError("Boolean values must be true/false or 1/0.")
    if isinstance(old_value, int) and not isinstance(old_value, bool):
        return int(stripped)
    if isinstance(old_value, float):
        return float(stripped)
    if isinstance(old_value, (list, tuple, dict)) or old_value is None:
        return ast.literal_eval(stripped)
    return stripped


class Suite2pOpsEditorDialog(QtWidgets.QDialog):
    def __init__(self, config_path: Path, parent=None, default_save_dir: Optional[Path] = None):
        super().__init__(parent)
        self.config_path = Path(config_path)
        self.default_save_dir = Path(default_save_dir) if default_save_dir else self.config_path.parent
        self.saved_as_path: Optional[Path] = None
        self.ops = np.load(self.config_path, allow_pickle=True).item()
        if not isinstance(self.ops, dict):
            raise ValueError(f"Suite2p config is not a dict: {self.config_path}")
        self.dirty = False
        self.setWindowTitle(f"Edit Suite2p config: {self.config_path.name}")
        self.resize(900, 700)
        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.path_label = QtWidgets.QLabel(str(self.config_path))
        self.path_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Setting", "Value", "Type"])
        self.tree.itemDoubleClicked.connect(self.edit_selected_item)
        layout.addWidget(self.tree)

        buttons = QtWidgets.QHBoxLayout()
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_as_button = QtWidgets.QPushButton("Save As")
        self.close_button = QtWidgets.QPushButton("Close")
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.save_as_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(self.save)
        self.save_as_button.clicked.connect(self.save_as)
        self.close_button.clicked.connect(self.close)
        self.populate_tree()

    def populate_tree(self):
        self.tree.clear()
        grouped_keys = set()
        for group_name, keys in S2P_OPS_GROUPS:
            group_item = QtWidgets.QTreeWidgetItem([group_name, "", ""])
            group_item.setFirstColumnSpanned(True)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)
            self.tree.addTopLevelItem(group_item)
            for key in keys:
                if key in self.ops:
                    grouped_keys.add(key)
                    group_item.addChild(self._setting_item(key))
            group_item.setExpanded(True)

        other_keys = sorted(key for key in self.ops if key not in grouped_keys)
        if other_keys:
            other_item = QtWidgets.QTreeWidgetItem(["Other", "", ""])
            other_item.setFirstColumnSpanned(True)
            font = other_item.font(0)
            font.setBold(True)
            other_item.setFont(0, font)
            self.tree.addTopLevelItem(other_item)
            for key in other_keys:
                other_item.addChild(self._setting_item(key))
            other_item.setExpanded(False)

        self.tree.resizeColumnToContents(0)
        self.tree.resizeColumnToContents(2)

    def _setting_item(self, key: str) -> QtWidgets.QTreeWidgetItem:
        value = self.ops[key]
        item = QtWidgets.QTreeWidgetItem([
            key,
            _display_ops_value(value),
            type(value).__name__,
        ])
        item.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
        return item

    def edit_selected_item(self, item: QtWidgets.QTreeWidgetItem, _column: int):
        key = item.data(0, QtCore.Qt.ItemDataRole.UserRole)
        if not key:
            return
        old_value = self.ops[key]
        text, ok = QtWidgets.QInputDialog.getMultiLineText(
            self,
            "Edit Suite2p Setting",
            f"{key} ({type(old_value).__name__})",
            _display_ops_value(old_value),
        )
        if not ok:
            return
        try:
            new_value = _parse_ops_value(text, old_value)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Invalid Value", str(exc))
            return
        self.ops[key] = new_value
        item.setText(1, _display_ops_value(new_value))
        item.setText(2, type(new_value).__name__)
        self.dirty = True

    def save(self):
        np.save(self.config_path, self.ops)
        self.dirty = False
        QtWidgets.QMessageBox.information(self, "Suite2p Config", f"Saved:\n{self.config_path}")

    def save_as(self) -> bool:
        self.default_save_dir.mkdir(parents=True, exist_ok=True)
        default_path = self.default_save_dir / self.config_path.name
        path_text, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Suite2p Config As",
            str(default_path),
            "NumPy config (*.npy)",
        )
        if not path_text:
            return False
        new_path = Path(path_text)
        if new_path.suffix.lower() != ".npy":
            new_path = new_path.with_suffix(".npy")
        np.save(new_path, self.ops)
        self.config_path = new_path
        self.saved_as_path = new_path
        self.default_save_dir = new_path.parent
        self.dirty = False
        self.path_label.setText(str(self.config_path))
        self.setWindowTitle(f"Edit Suite2p config: {self.config_path.name}")
        QtWidgets.QMessageBox.information(self, "Suite2p Config", f"Saved:\n{self.config_path}")
        return True

    def closeEvent(self, event: QtGui.QCloseEvent):
        if self.dirty:
            response = QtWidgets.QMessageBox.question(
                self,
                "Unsaved Suite2p Config Changes",
                "Save changes before closing?",
                (
                    QtWidgets.QMessageBox.StandardButton.Save
                    | QtWidgets.QMessageBox.StandardButton.Discard
                    | QtWidgets.QMessageBox.StandardButton.Cancel
                ),
                QtWidgets.QMessageBox.StandardButton.Save,
            )
            if response == QtWidgets.QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if response == QtWidgets.QMessageBox.StandardButton.Save:
                np.save(self.config_path, self.ops)
                self.dirty = False
        event.accept()


class Suite2pConfigSelector(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_dir: Optional[Path] = None
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.combo = EditableConfigCombo()
        self.edit_button = QtWidgets.QPushButton("Edit")
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.edit_button)
        self.edit_button.clicked.connect(self.edit_current_config)

    def set_config_dir(self, config_dir: Optional[Path]):
        self.config_dir = Path(config_dir) if config_dir else None

    def clear(self):
        self.combo.clear()

    def addItems(self, values: list[str]):
        self.combo.addItems(values)

    def value(self) -> str:
        return self.combo.value()

    def set_value(self, value: str):
        self.combo.set_value(value)

    def edit_current_config(self):
        config_name = self.value()
        if not config_name:
            QtWidgets.QMessageBox.information(self, "Edit Suite2p Config", "Select a Suite2p config first.")
            return
        config_path = Path(config_name)
        if not config_path.is_absolute():
            if self.config_dir is None:
                QtWidgets.QMessageBox.warning(self, "Edit Suite2p Config", "No Suite2p config directory is set.")
                return
            config_path = self.config_dir / config_name
        if not config_path.exists():
            QtWidgets.QMessageBox.warning(self, "Edit Suite2p Config", f"Config file not found:\n{config_path}")
            return
        dialog = Suite2pOpsEditorDialog(config_path, self, default_save_dir=self.config_dir)
        dialog.exec()


class EmittingTextStream:
    def __init__(self, callback):
        self.callback = callback

    def write(self, text):
        if text:
            self.callback(text)

    def flush(self):
        pass


class Step2Worker(QtCore.QObject):
    output = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    failed = QtCore.pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

    def run(self):
        stream = EmittingTextStream(self.output.emit)
        try:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                run_step2_batch(self.config)
        except Exception as exc:
            self.output.emit(traceback.format_exc())
            self.failed.emit(str(exc))
        else:
            self.finished.emit()


class SplitWorker(QtCore.QObject):
    output = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    failed = QtCore.pyqtSignal(str)

    def __init__(self, user_id: str, exp_id: str):
        super().__init__()
        self.user_id = user_id
        self.exp_id = exp_id

    def run(self):
        stream = EmittingTextStream(self.output.emit)
        try:
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                split_combined_s2p.split_combined_suite2p_for_experiment(
                    self.user_id, self.exp_id
                )
        except Exception as exc:
            self.output.emit(traceback.format_exc())
            self.failed.emit(str(exc))
        else:
            self.finished.emit()


class QueueTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.username = getpass.getuser()
        self.current_queue_directory = NORMAL_QUEUE_DIRECTORY
        self.current_log_size = 0
        self.selected_job_name: Optional[str] = None
        self._build_ui()
        self._connect_timers()
        self.on_queue_source_changed()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel("Queue:"))
        self.queue_selector = QtWidgets.QComboBox()
        self.queue_selector.addItems(["Normal queue", "Debug queue"])
        controls.addWidget(self.queue_selector)
        controls.addStretch(1)
        self.remove_button = QtWidgets.QPushButton("Remove Selected Job")
        controls.addWidget(self.remove_button)
        layout.addLayout(controls)

        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)

        top_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.queue_list = QtWidgets.QListWidget()
        self.queue_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        top_splitter.addWidget(self._group_box("Jobs in Queue", self.queue_list))
        self.prioritised_jobs_list = QtWidgets.QListWidget()
        top_splitter.addWidget(self._group_box("Prioritized Jobs", self.prioritised_jobs_list))

        right_panel = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.completed_jobs_list = QtWidgets.QListWidget()
        self.failed_jobs_list = QtWidgets.QListWidget()
        right_panel.addWidget(self._group_box("Completed Jobs", self.completed_jobs_list))
        right_panel.addWidget(self._group_box("Failed Jobs", self.failed_jobs_list))
        right_panel.setSizes([160, 160])
        top_splitter.addWidget(right_panel)

        self.user_totals_list = QtWidgets.QListWidget()
        top_splitter.addWidget(self._group_box("User Compute Times", self.user_totals_list))
        top_splitter.setSizes([360, 360, 360, 180])
        main_splitter.addWidget(top_splitter)

        self.log_list = QtWidgets.QListWidget()
        main_splitter.addWidget(self._group_box("Log Feedback", self.log_list))
        main_splitter.setSizes([320, 260])
        layout.addWidget(main_splitter)

        self.queue_selector.currentIndexChanged.connect(self.on_queue_source_changed)
        self.remove_button.clicked.connect(self.remove_selected_job)
        self.queue_list.itemSelectionChanged.connect(self._remember_selection)
        self.queue_list.itemDoubleClicked.connect(self.show_selected_job_config)
        self.completed_jobs_list.itemDoubleClicked.connect(self.show_completed_job_config)
        self.failed_jobs_list.itemDoubleClicked.connect(self.show_failed_job_config)

    def _group_box(self, title: str, widget: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox(title)
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.addWidget(widget)
        return box

    def _connect_timers(self):
        self.queue_timer = QtCore.QTimer(self)
        self.queue_timer.timeout.connect(self.refresh_queue_list)
        self.queue_timer.timeout.connect(self.refresh_completed_failed_jobs)
        self.queue_timer.start(QUEUE_REFRESH_MS)

        self.priority_timer = QtCore.QTimer(self)
        self.priority_timer.timeout.connect(self.refresh_prioritised_jobs)
        self.priority_timer.start(PRIORITY_REFRESH_MS)

        self.totals_timer = QtCore.QTimer(self)
        self.totals_timer.timeout.connect(self.refresh_user_totals)
        self.totals_timer.start(USER_TOTALS_REFRESH_MS)

        self.log_timer = QtCore.QTimer(self)
        self.log_timer.timeout.connect(self.refresh_log)
        self.log_timer.start(LOG_REFRESH_MS)

    def on_queue_source_changed(self):
        self.current_queue_directory = (
            NORMAL_QUEUE_DIRECTORY if self.queue_selector.currentIndex() == 0 else DEBUG_QUEUE_DIRECTORY
        )
        self.current_log_size = 0
        self.log_list.clear()
        self.load_initial_log_lines()
        self.refresh_queue_list()
        self.refresh_prioritised_jobs()
        self.refresh_user_totals()
        self.refresh_completed_failed_jobs()

    def _current_log_path(self) -> Optional[Path]:
        path = _queue_listener_log_path(self.current_queue_directory)
        if not path.exists():
            return None
        return path

    def load_initial_log_lines(self):
        path = self._current_log_path()
        if path is None or not path.exists():
            return
        lines = _read_tail_lines(path, INITIAL_LOG_LINES)
        self.current_log_size = path.stat().st_size
        for line in lines:
            self._add_log_line(line.rstrip())
        self.log_list.scrollToBottom()

    def _add_log_line(self, line: str):
        item = QtWidgets.QListWidgetItem()
        display_text = line
        bold = False
        if line.startswith("**"):
            bold = True
            display_text = line[2:].lstrip()
        item.setText(display_text)
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        self.log_list.addItem(item)

    def _parse_displayed_job_name(self, display_text: str) -> Optional[str]:
        match = re.match(r"^[* ]+\d{3}\.\s+(.*)$", display_text)
        return match.group(1) if match else None

    def _remember_selection(self):
        items = self.queue_list.selectedItems()
        self.selected_job_name = self._parse_displayed_job_name(items[0].text()) if items else None

    def _load_selected_job(self):
        items = self.queue_list.selectedItems()
        if not items:
            raise ValueError("Select a queued job first.")
        job_name = self._parse_displayed_job_name(items[0].text())
        if not job_name:
            raise ValueError("Could not parse the selected job name.")
        job_path = self.current_queue_directory / job_name
        if not job_path.exists():
            raise FileNotFoundError("Selected job file no longer exists.")
        with job_path.open("rb") as handle:
            queued_command = pickle.load(handle)
        return job_name, queued_command

    def _load_job_from_list(self, list_widget: QtWidgets.QListWidget, subdirectory: str):
        items = list_widget.selectedItems()
        if not items:
            raise ValueError("Select a job first.")
        job_name = items[0].text()
        job_path = self.current_queue_directory / subdirectory / job_name
        if not job_path.exists():
            raise FileNotFoundError("Selected job file no longer exists.")
        with job_path.open("rb") as handle:
            queued_command = pickle.load(handle)
        return job_name, queued_command

    def show_selected_job_config(self):
        try:
            job_name, queued_command = self._load_selected_job()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Show Job Config", str(exc))
            return
        self._show_job_config_dialog(job_name, queued_command)

    def show_completed_job_config(self):
        try:
            job_name, queued_command = self._load_job_from_list(self.completed_jobs_list, "completed")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Show Completed Job Config", str(exc))
            return
        self._show_job_config_dialog(job_name, queued_command)

    def show_failed_job_config(self):
        try:
            job_name, queued_command = self._load_job_from_list(self.failed_jobs_list, "failed")
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Show Failed Job Config", str(exc))
            return
        self._show_job_config_dialog(job_name, queued_command)

    def _show_job_config_dialog(self, job_name: str, queued_command: dict):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Job Config: {job_name}")
        dialog.resize(1000, 850)
        layout = QtWidgets.QVBoxLayout(dialog)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical, dialog)

        config_text = QtWidgets.QPlainTextEdit(dialog)
        config_text.setReadOnly(True)
        config_text.setPlainText(json.dumps(queued_command, indent=2, default=str))
        splitter.addWidget(self._group_box("Config", config_text))

        feedback_text = QtWidgets.QPlainTextEdit(dialog)
        feedback_text.setReadOnly(True)
        feedback_log_path = self._job_feedback_log_path(job_name)
        feedback_size = {"value": -1}

        def refresh_feedback():
            if not feedback_log_path.exists():
                feedback_text.setPlainText(f"No feedback log found yet:\n{feedback_log_path}")
                feedback_size["value"] = -1
                return
            current_size = feedback_log_path.stat().st_size
            if current_size == feedback_size["value"]:
                return
            at_bottom = (
                feedback_text.verticalScrollBar().value()
                == feedback_text.verticalScrollBar().maximum()
            )
            feedback_text.setPlainText(
                feedback_log_path.read_text(encoding="utf-8", errors="replace")
            )
            feedback_size["value"] = current_size
            if at_bottom:
                feedback_text.verticalScrollBar().setValue(
                    feedback_text.verticalScrollBar().maximum()
                )

        refresh_feedback()
        splitter.addWidget(self._group_box("Feedback", feedback_text))
        splitter.setSizes([360, 490])
        layout.addWidget(splitter)

        timer = QtCore.QTimer(dialog)
        timer.timeout.connect(refresh_feedback)
        timer.start(LOG_REFRESH_MS)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close, parent=dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _job_feedback_log_path(self, job_name: str) -> Path:
        log_name = job_name[:-7] + ".txt" if job_name.endswith(".pickle") else job_name + ".txt"
        return self.current_queue_directory / "logs" / log_name

    def refresh_queue_list(self):
        current_selection = self.selected_job_name
        self.queue_list.clear()
        queue_files = sorted(p.name for p in self.current_queue_directory.glob("*.pickle"))
        for index, job_name in enumerate(queue_files, start=1):
            prefix = f"{index:03}."
            display = f"* {prefix} {job_name}" if self.username in job_name else f"  {prefix} {job_name}"
            self.queue_list.addItem(display)

        if current_selection:
            for row in range(self.queue_list.count()):
                parsed = self._parse_displayed_job_name(self.queue_list.item(row).text())
                if parsed == current_selection:
                    self.queue_list.setCurrentRow(row)
                    break

    def refresh_prioritised_jobs(self):
        self.prioritised_jobs_list.clear()
        file_path = self.current_queue_directory / "prioritised_jobs.txt"
        if file_path.exists():
            for line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
                self.prioritised_jobs_list.addItem(line)

    def _refresh_job_history_list(self, list_widget: QtWidgets.QListWidget, subdirectory: str):
        list_widget.clear()
        history_dir = self.current_queue_directory / subdirectory
        if not history_dir.exists():
            return
        jobs = sorted(
            history_dir.glob("*.pickle"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:50]
        for job_path in jobs:
            list_widget.addItem(job_path.name)

    def refresh_completed_failed_jobs(self):
        self._refresh_job_history_list(self.completed_jobs_list, "completed")
        self._refresh_job_history_list(self.failed_jobs_list, "failed")

    def refresh_user_totals(self):
        self.user_totals_list.clear()
        file_path = self.current_queue_directory / "user_totals.txt"
        if file_path.exists():
            for line in file_path.read_text(encoding="utf-8", errors="replace").splitlines():
                self.user_totals_list.addItem(f"{line} mins")

    def refresh_log(self):
        path = self._current_log_path()
        if path is None or not path.exists():
            return
        auto_scroll = self.log_list.verticalScrollBar().value() == self.log_list.verticalScrollBar().maximum()
        current_size = path.stat().st_size
        if current_size < self.current_log_size:
            self.log_list.clear()
            self.current_log_size = 0
            self.load_initial_log_lines()
            return
        if current_size == self.current_log_size:
            return

        with path.open("rb") as handle:
            handle.seek(self.current_log_size)
            data = handle.read()
        self.current_log_size = current_size
        text = data.decode("utf-8", errors="replace")
        for line in text.splitlines():
            self._add_log_line(line.rstrip())
        while self.log_list.count() > MAX_LOG_LINES:
            self.log_list.takeItem(0)
        if auto_scroll:
            self.log_list.scrollToBottom()

    def remove_selected_job(self):
        try:
            job_name, queued_command = self._load_selected_job()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Remove Job", f"Could not read job file:\n{exc}")
            return
        job_path = self.current_queue_directory / job_name
        if queued_command.get("userID") != self.username:
            QtWidgets.QMessageBox.warning(self, "Remove Job", "You can only remove your own queued jobs.")
            return
        response = QtWidgets.QMessageBox.question(
            self,
            "Remove Job",
            f"Remove queued job?\n{job_name}",
        )
        if response != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        job_path.unlink()
        self.selected_job_name = None
        self.refresh_queue_list()


class ExperimentListEditor(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()

    def __init__(self, parent=None, buttons_first: bool = False):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        button_layout = QtWidgets.QHBoxLayout()
        self.line_edit = QtWidgets.QLineEdit()
        self.line_edit.setPlaceholderText("YYYY-MM-DD_NN_ANIMALID")
        self.add_button = QtWidgets.QPushButton("Add")
        self.remove_button = QtWidgets.QPushButton("Remove Selected")
        self.clear_button = QtWidgets.QPushButton("Clear")
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.clear_button)
        button_layout.addStretch(1)

        if buttons_first:
            layout.addLayout(button_layout)
            layout.addWidget(self.line_edit)
        else:
            add_layout = QtWidgets.QHBoxLayout()
            add_layout.addWidget(self.line_edit)
            add_layout.addLayout(button_layout)
            layout.addLayout(add_layout)

        self.list_widget = QtWidgets.QListWidget()
        layout.addWidget(self.list_widget)

        self.add_button.clicked.connect(self.add_current)
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button.clicked.connect(self.clear_all)
        self.line_edit.returnPressed.connect(self.add_current)

    def values(self) -> list[str]:
        return [self.list_widget.item(i).text() for i in range(self.list_widget.count())]

    def set_values(self, values: list[str]):
        self.list_widget.clear()
        for value in values:
            self.list_widget.addItem(value)
        self.changed.emit()

    def add_current(self):
        value = self.line_edit.text().strip()
        if not value:
            return
        if value not in self.values():
            self.list_widget.addItem(value)
            self.changed.emit()
        self.line_edit.clear()

    def remove_selected(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.list_widget.takeItem(row)
            self.changed.emit()

    def clear_all(self):
        self.list_widget.clear()
        self.changed.emit()


class StandardConfigWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._config_files: list[str] = []
        self._config_dir: Optional[Path] = None
        layout = QtWidgets.QFormLayout(self)
        self.same_for_both = QtWidgets.QCheckBox("Use same config for both channels")
        self.same_for_both.setChecked(True)
        self.register_with_summed_channel = QtWidgets.QCheckBox("Register with averaged channels")
        self.register_with_summed_channel.setChecked(False)
        self.register_with_summed_channel.setEnabled(False)
        self.ch1_combo = Suite2pConfigSelector()
        self.ch2_combo = Suite2pConfigSelector()
        layout.addRow(self.same_for_both)
        layout.addRow(self.register_with_summed_channel)
        layout.addRow("Channel 1 config", self.ch1_combo)
        layout.addRow("Channel 2 config", self.ch2_combo)
        self.same_for_both.toggled.connect(self._sync_channel_mode)
        self._sync_channel_mode()

    def set_config_files(self, config_files: list[str], config_dir: Optional[Path] = None):
        self._config_files = list(config_files)
        self._config_dir = Path(config_dir) if config_dir else None
        for combo in (self.ch1_combo, self.ch2_combo):
            current = combo.value()
            combo.set_config_dir(self._config_dir)
            combo.clear()
            combo.addItems(self._config_files)
            combo.set_value(current)

    def set_channel_count(self, nchannels: int):
        dual = nchannels >= 2
        self.same_for_both.setVisible(dual)
        self.register_with_summed_channel.setVisible(dual)
        self.register_with_summed_channel.setEnabled(dual)
        if not dual:
            self.same_for_both.setChecked(True)
            self.register_with_summed_channel.setChecked(False)
        self.ch2_combo.setVisible(dual)
        self._sync_channel_mode()

    def _sync_channel_mode(self):
        use_same = self.same_for_both.isChecked()
        self.ch2_combo.setEnabled(not use_same and self.ch2_combo.isVisible())

    def config_value(self, nchannels: int):
        ch1 = self.ch1_combo.value()
        if not ch1:
            raise ValueError("Channel 1 Suite2p config is required.")
        if nchannels < 2:
            return ch1
        if self.same_for_both.isChecked():
            return ch1
        ch2 = self.ch2_combo.value()
        if not ch2:
            raise ValueError("Channel 2 Suite2p config is required for dual-channel runs.")
        return [ch1, ch2]

    def apply_preset(self, preset: dict, nchannels: int):
        self.same_for_both.setChecked(preset.get("same_for_both", True))
        self.register_with_summed_channel.setChecked(preset.get("register_with_summed_channel", False))
        self.ch1_combo.set_value(preset.get("ch1", ""))
        self.ch2_combo.set_value(preset.get("ch2", ""))
        self.set_channel_count(nchannels)

    def preset_state(self) -> dict:
        return {
            "same_for_both": self.same_for_both.isChecked(),
            "register_with_summed_channel": self.register_with_summed_channel.isChecked(),
            "ch1": self.ch1_combo.value(),
            "ch2": self.ch2_combo.value(),
        }

    def register_with_summed_channel_enabled(self) -> bool:
        return self.register_with_summed_channel.isVisible() and self.register_with_summed_channel.isChecked()


class PathConfigRow(QtWidgets.QWidget):
    def __init__(
        self,
        path_name: str,
        nchannels: int,
        config_files: list[str],
        config_dir: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.path_name = path_name
        self.nchannels = nchannels
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QtWidgets.QLabel(path_name))
        self.ch1_combo = Suite2pConfigSelector()
        self.ch1_combo.set_config_dir(config_dir)
        self.ch1_combo.addItems(config_files)
        layout.addWidget(QtWidgets.QLabel("Ch1"))
        layout.addWidget(self.ch1_combo, 1)
        self.same_for_both = QtWidgets.QCheckBox("Same for ch2")
        self.same_for_both.setChecked(True)
        layout.addWidget(self.same_for_both)
        self.ch2_combo = Suite2pConfigSelector()
        self.ch2_combo.set_config_dir(config_dir)
        self.ch2_combo.addItems(config_files)
        layout.addWidget(QtWidgets.QLabel("Ch2"))
        layout.addWidget(self.ch2_combo, 1)
        self.ch2_combo.setVisible(nchannels >= 2)
        self.same_for_both.setVisible(nchannels >= 2)
        self.same_for_both.toggled.connect(self._sync_channel_mode)
        self._sync_channel_mode()

    def _sync_channel_mode(self):
        self.ch2_combo.setEnabled(not self.same_for_both.isChecked() and self.ch2_combo.isVisible())

    def config_value(self):
        ch1 = self.ch1_combo.value()
        if not ch1:
            raise ValueError(f"{self.path_name}: channel 1 config is required.")
        if self.nchannels < 2:
            return ch1
        if self.same_for_both.isChecked():
            return [ch1, ch1]
        ch2 = self.ch2_combo.value()
        if not ch2:
            raise ValueError(f"{self.path_name}: channel 2 config is required.")
        return [ch1, ch2]

    def apply_value(self, value):
        if isinstance(value, dict):
            same_for_both = value.get("same_for_both", True)
            ch1 = value.get("ch1", "") or ""
            ch2 = value.get("ch2", ch1) or ch1
            self.same_for_both.setChecked(bool(same_for_both))
            self.ch1_combo.set_value(ch1)
            self.ch2_combo.set_value(ch2)
            self._sync_channel_mode()
            return
        if isinstance(value, (list, tuple)):
            ch1 = value[0] if value else ""
            ch2 = value[1] if len(value) > 1 else ch1
            self.same_for_both.setChecked(ch1 == ch2)
            self.ch1_combo.set_value(ch1)
            self.ch2_combo.set_value(ch2)
            self._sync_channel_mode()
        else:
            self.same_for_both.setChecked(True)
            self.ch1_combo.set_value(value or "")
            self.ch2_combo.set_value(value or "")
            self._sync_channel_mode()

    def preset_state(self):
        return {
            "same_for_both": self.same_for_both.isChecked(),
            "ch1": self.ch1_combo.value(),
            "ch2": self.ch2_combo.value(),
        }


class MesoConfigWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_files: list[str] = []
        self.config_dir: Optional[Path] = None
        self.descriptor: Optional[ExperimentDescriptor] = None
        layout = QtWidgets.QVBoxLayout(self)
        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.addWidget(QtWidgets.QLabel("Config mode:"))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems([
            "Same config over all paths/ROIs",
            "Common config per path",
        ])
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch(1)
        layout.addLayout(mode_layout)

        self.stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.stack)

        self.global_widget = StandardConfigWidget()
        self.global_container = QtWidgets.QWidget()
        global_layout = QtWidgets.QVBoxLayout(self.global_container)
        global_layout.addWidget(self.global_widget)
        global_layout.addStretch(1)
        self.stack.addWidget(self.global_container)

        self.path_container = QtWidgets.QWidget()
        self.path_layout = QtWidgets.QVBoxLayout(self.path_container)
        self.path_layout.addStretch(1)
        self.stack.addWidget(self.path_container)

        self.mode_combo.currentIndexChanged.connect(self.stack.setCurrentIndex)
        self.path_rows: OrderedDict[str, PathConfigRow] = OrderedDict()

    def set_context(
        self,
        descriptor: ExperimentDescriptor,
        config_files: list[str],
        config_dir: Optional[Path] = None,
    ):
        self.descriptor = descriptor
        self.config_files = list(config_files)
        self.config_dir = Path(config_dir) if config_dir else None
        self.global_widget.set_config_files(self.config_files, self.config_dir)
        self.global_widget.set_channel_count(descriptor.nchannels)
        for row in list(self.path_rows.values()):
            row.setParent(None)
        self.path_rows.clear()

        # remove all but stretch
        while self.path_layout.count():
            item = self.path_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for path_name, meta in descriptor.per_path.items():
            row = PathConfigRow(path_name, meta.nchannels, self.config_files, self.config_dir)
            roi_label = QtWidgets.QLabel(f"ROIs: {', '.join(meta.roi_names)}")
            container = QtWidgets.QWidget()
            container_layout = QtWidgets.QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.addWidget(row)
            container_layout.addWidget(roi_label)
            self.path_layout.addWidget(container)
            self.path_rows[path_name] = row
        self.path_layout.addStretch(1)

    def config_value(self):
        if self.descriptor is None:
            raise ValueError("No mesoscope experiment has been detected yet.")
        if self.mode_combo.currentIndex() == 0:
            return {"default": self.global_widget.config_value(self.descriptor.nchannels)}

        mapping = {}
        for path_name, meta in self.descriptor.per_path.items():
            path_value = self.path_rows[path_name].config_value()
            for roi_name in meta.roi_names:
                mapping[f"{path_name}/{roi_name}"] = path_value
        return mapping

    def apply_preset(self, preset: dict):
        if self.descriptor is None:
            return
        mode = preset.get("config_scope", "all")
        self.mode_combo.setCurrentIndex(0 if mode == "all" else 1)
        self.global_widget.apply_preset(preset.get("global", {}), self.descriptor.nchannels)
        for path_name, row in self.path_rows.items():
            row.apply_value(preset.get("paths", {}).get(path_name, ""))

    def preset_state(self):
        return {
            "config_scope": "all" if self.mode_combo.currentIndex() == 0 else "per_path",
            "global": self.global_widget.preset_state(),
            "paths": {path_name: row.preset_state() for path_name, row in self.path_rows.items()},
        }


class Step1Tab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.username = getpass.getuser()
        self.detected_descriptor: Optional[ExperimentDescriptor] = None
        self.pending_preset: Optional[dict] = None
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setInterval(500)
        self.preview_timer.timeout.connect(self.update_config_preview)
        self._build_ui()
        self.refresh_config_choices()
        self.preview_timer.start()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)

        toolbar = QtWidgets.QHBoxLayout()
        self.submit_button = QtWidgets.QPushButton("Submit Step 1 Job")
        toolbar.addStretch(1)
        toolbar.addWidget(self.submit_button)
        outer.addLayout(toolbar)

        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        outer.addWidget(main_splitter)

        left = QtWidgets.QWidget()
        left_form = QtWidgets.QFormLayout(left)
        self.user_edit = QtWidgets.QLineEdit(self.username)
        left_form.addRow("userID", self.user_edit)
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["Single experiment(s)", "Combined experiment"])
        left_form.addRow("Mode", self.mode_combo)
        self.queue_combo = QtWidgets.QComboBox()
        self.queue_combo.addItems(["Normal", "Debug"])
        left_form.addRow("Queue", self.queue_combo)

        self.exp_editor = ExperimentListEditor(buttons_first=True)
        exp_box = QtWidgets.QGroupBox("expIDs")
        exp_box_layout = QtWidgets.QVBoxLayout(exp_box)
        exp_box_layout.addWidget(self.exp_editor)
        left_form.addRow(exp_box)

        self.runs2p = QtWidgets.QCheckBox()
        self.runs2p.setChecked(True)
        left_form.addRow("runs2p", self.runs2p)
        self.rundlc = QtWidgets.QCheckBox()
        self.rundlc.setChecked(True)
        left_form.addRow("rundlc", self.rundlc)
        self.runfitpupil = QtWidgets.QCheckBox()
        self.runfitpupil.setChecked(True)
        left_form.addRow("runfitpupil", self.runfitpupil)
        self.runsrdtrans = QtWidgets.QCheckBox()
        self.runsrdtrans.setChecked(False)
        left_form.addRow("runsrdtrans", self.runsrdtrans)
        self.runhabituate = QtWidgets.QCheckBox()
        self.runhabituate.setChecked(False)
        self.jump_queue = QtWidgets.QCheckBox()
        self.jump_queue.setChecked(False)
        if self.username == "adamranson":
            left_form.addRow("jump_queue", self.jump_queue)
        self.suite2p_env = QtWidgets.QLineEdit()
        self.suite2p_env.setPlaceholderText("Optional")
        left_form.addRow("suite2p_env", self.suite2p_env)

        self.summary_box = QtWidgets.QPlainTextEdit()
        self.summary_box.setReadOnly(True)
        self.summary_box.document().setMaximumBlockCount(200)
        left_form.addRow("Detected", self.summary_box)
        main_splitter.addWidget(left)

        right = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right)
        self.config_group = QtWidgets.QGroupBox("Suite2p Config Builder")
        config_layout = QtWidgets.QVBoxLayout(self.config_group)
        self.preset_group = QtWidgets.QGroupBox("Saved Step 1 Configs")
        preset_layout = QtWidgets.QVBoxLayout(self.preset_group)
        self.preset_list = QtWidgets.QListWidget()
        self.preset_list.setMaximumHeight(140)
        preset_layout.addWidget(self.preset_list)
        preset_buttons = QtWidgets.QHBoxLayout()
        self.load_preset_button = QtWidgets.QPushButton("Load")
        self.save_preset_button = QtWidgets.QPushButton("Save")
        self.delete_preset_button = QtWidgets.QPushButton("Delete")
        self.rename_preset_button = QtWidgets.QPushButton("Rename")
        self.load_s2p_config_button = QtWidgets.QPushButton("Load S2P config")
        self.help_preset_button = QtWidgets.QPushButton("Help")
        preset_buttons.addWidget(self.load_preset_button)
        preset_buttons.addWidget(self.save_preset_button)
        preset_buttons.addWidget(self.delete_preset_button)
        preset_buttons.addWidget(self.rename_preset_button)
        preset_buttons.addWidget(self.load_s2p_config_button)
        preset_buttons.addStretch(1)
        preset_buttons.addWidget(self.help_preset_button)
        preset_layout.addLayout(preset_buttons)
        config_layout.addWidget(self.preset_group)
        self.standard_widget = StandardConfigWidget()
        self.meso_widget = MesoConfigWidget()
        self.config_stack = QtWidgets.QStackedWidget()
        self.config_stack.addWidget(self.standard_widget)
        self.config_stack.addWidget(self.meso_widget)
        config_layout.addWidget(self.config_stack)

        self.settings_json = QtWidgets.QPlainTextEdit("{}")
        self.settings_json.setPlaceholderText('Optional JSON dict for step1_config["settings"]')
        self.settings_json.setMaximumHeight(90)
        config_layout.addWidget(QtWidgets.QLabel('Optional settings override JSON'))
        config_layout.addWidget(self.settings_json)
        self.srdtrans_json = QtWidgets.QPlainTextEdit(
            '{"model_root": "/home/adamranson/data/srt_models", "model": "", "patch_x": 160, "patch_t": 160, "overlap_factor": 0.5, "gpu": "0", "channels": ["ch1"]}'
        )
        self.srdtrans_json.setPlaceholderText('JSON dict for step1_config["srdtrans"]')
        self.srdtrans_json.setMaximumHeight(90)
        config_layout.addWidget(QtWidgets.QLabel('SRDTrans JSON'))
        config_layout.addWidget(self.srdtrans_json)
        self.config_preview = QtWidgets.QPlainTextEdit()
        self.config_preview.setReadOnly(True)
        self.config_preview.setPlaceholderText("Generated step1_config preview")
        config_layout.addWidget(QtWidgets.QLabel("Generated step1_config JSON"))
        config_layout.addWidget(self.config_preview)
        right_layout.addWidget(self.config_group)
        main_splitter.addWidget(right)
        main_splitter.setSizes([420, 680])

        self.exp_editor.changed.connect(self.on_exp_list_changed)
        self.user_edit.editingFinished.connect(self.on_user_edit_finished)
        self.load_preset_button.clicked.connect(self.load_preset)
        self.delete_preset_button.clicked.connect(self.delete_preset)
        self.rename_preset_button.clicked.connect(self.rename_preset)
        self.load_s2p_config_button.clicked.connect(self.load_s2p_config_from_file)
        self.help_preset_button.clicked.connect(self.show_preset_help)
        self.preset_list.itemDoubleClicked.connect(lambda _item: self.load_preset())
        self.save_preset_button.clicked.connect(self.save_preset)
        self.submit_button.clicked.connect(self.submit_job)
        self.refresh_preset_list()
        self.update_config_preview()

    def on_user_edit_finished(self):
        self.refresh_preset_list()
        self.on_exp_list_changed()

    def refresh_config_choices(self):
        config_dir = S2P_CONFIG_ROOT / self.user_edit.text().strip()
        config_files = sorted(p.name for p in config_dir.glob("*.npy")) if config_dir.exists() else []
        self.standard_widget.set_config_files(config_files, config_dir)
        if self.detected_descriptor is not None and self.detected_descriptor.topology == "meso":
            self.meso_widget.set_context(self.detected_descriptor, config_files, config_dir)

    def _preset_root(self) -> Path:
        return _step1_preset_root(self.user_edit.text().strip() or self.username)

    def refresh_preset_list(self):
        preset_root = self._preset_root()
        _ensure_preset_dir(preset_root)
        selected_path = self._selected_preset_path()
        selected_name = selected_path.name if selected_path else None
        self.preset_list.clear()
        for path in sorted(preset_root.glob("*.json")):
            item = QtWidgets.QListWidgetItem(path.stem)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(path))
            self.preset_list.addItem(item)
            if selected_name and path.name == selected_name:
                self.preset_list.setCurrentItem(item)

    def _selected_preset_path(self) -> Optional[Path]:
        item = self.preset_list.currentItem()
        if item is None:
            return None
        path_text = item.data(QtCore.Qt.ItemDataRole.UserRole)
        return Path(path_text) if path_text else None

    def on_exp_list_changed(self):
        self.detected_descriptor = None
        self.summary_box.clear()
        exp_ids = self.exp_editor.values()
        user_id = self.user_edit.text().strip()
        self.refresh_config_choices()
        if not exp_ids or not user_id:
            return

        try:
            first_descriptor = describe_experiment(user_id, exp_ids[0])
            self.detected_descriptor = first_descriptor
            self.refresh_config_choices()
            if first_descriptor.topology == "standard":
                self.config_stack.setCurrentWidget(self.standard_widget)
                self.standard_widget.set_channel_count(first_descriptor.nchannels)
            else:
                self.config_stack.setCurrentWidget(self.meso_widget)
                self.meso_widget.set_context(
                    first_descriptor,
                    self.standard_widget._config_files,
                    self.standard_widget._config_dir,
                )
            lines = [f"{exp_ids[0]}: {first_descriptor.summary}"]

            for extra_exp_id in exp_ids[1:]:
                extra = describe_experiment(user_id, extra_exp_id)
                compatible, reason = self._is_compatible(first_descriptor, extra)
                prefix = "OK" if compatible else "MISMATCH"
                lines.append(f"{extra_exp_id}: {prefix} - {extra.summary}")
                if not compatible:
                    lines.append(f"  Reason: {reason}")
            self.summary_box.setPlainText("\n".join(lines))
            if self.pending_preset is not None:
                self._apply_preset_payload(self.pending_preset)
                self.pending_preset = None
        except Exception as exc:
            self.summary_box.setPlainText(f"Detection failed:\n{exc}")

    def _is_compatible(self, reference: ExperimentDescriptor, other: ExperimentDescriptor) -> tuple[bool, str]:
        if reference.topology != other.topology:
            return False, "topology differs"
        if reference.nchannels != other.nchannels:
            return False, "channel count differs"
        if reference.topology == "meso":
            if list(reference.per_path.keys()) != list(other.per_path.keys()):
                return False, "path structure differs"
            for path_name in reference.per_path:
                if reference.per_path[path_name].roi_names != other.per_path[path_name].roi_names:
                    return False, f"ROI structure differs for {path_name}"
        return True, ""

    def _build_step1_config(self) -> dict:
        user_id = self.user_edit.text().strip()
        exp_ids = self.exp_editor.values()
        if not user_id or not exp_ids:
            raise ValueError("userID and at least one expID are required.")
        if self.detected_descriptor is None:
            raise ValueError("No experiment metadata has been detected yet.")

        if self.mode_combo.currentIndex() == 0:
            exp_value = exp_ids
        else:
            if len(exp_ids) < 2:
                raise ValueError("Combined mode requires at least two expIDs.")
            exp_value = [exp_ids]

        if self.detected_descriptor.topology == "standard":
            suite2p_config = self.standard_widget.config_value(self.detected_descriptor.nchannels)
        else:
            suite2p_config = self.meso_widget.config_value()

        config = {
            "userID": user_id,
            "expIDs": exp_value,
            "suite2p_config": suite2p_config,
            "runs2p": self.runs2p.isChecked(),
            "rundlc": self.rundlc.isChecked(),
            "runfitpupil": self.runfitpupil.isChecked(),
            "runsrdtrans": self.runsrdtrans.isChecked(),
        }
        if self.runhabituate.isChecked():
            config["runhabituate"] = True
        if self.jump_queue.isChecked():
            config["jump_queue"] = True
        if self._register_with_summed_channel_requested():
            config["register_with_summed_channel"] = True
        if self.queue_combo.currentIndex() == 1:
            config["queue"] = "debug"
        suite2p_env = self.suite2p_env.text().strip()
        if suite2p_env:
            config["suite2p_env"] = suite2p_env
        settings_text = self.settings_json.toPlainText().strip()
        if settings_text and settings_text != "{}":
            config["settings"] = json.loads(settings_text)
        if self.runsrdtrans.isChecked():
            config["srdtrans"] = json.loads(self.srdtrans_json.toPlainText().strip() or "{}")
        return config

    def _register_with_summed_channel_requested(self) -> bool:
        if self.detected_descriptor is None or self.detected_descriptor.nchannels < 2:
            return False
        if self.detected_descriptor.topology == "standard":
            return self.standard_widget.register_with_summed_channel_enabled()
        if self.meso_widget.mode_combo.currentIndex() == 0:
            return self.meso_widget.global_widget.register_with_summed_channel_enabled()
        return False

    def update_config_preview(self):
        try:
            config = self._build_step1_config()
            preview = json.dumps(config, indent=2)
        except Exception as exc:
            preview = (
                "Config preview will appear once the Step 1 form is complete.\n\n"
                f"Current issue: {exc}"
            )
        if self.config_preview.toPlainText() != preview:
            self.config_preview.setPlainText(preview)

    def _preset_payload(self) -> dict:
        return {
            "userID": self.user_edit.text().strip(),
            "mode": "single" if self.mode_combo.currentIndex() == 0 else "combined",
            "queue": "step1" if self.queue_combo.currentIndex() == 0 else "debug",
            "runs2p": self.runs2p.isChecked(),
            "rundlc": self.rundlc.isChecked(),
            "runfitpupil": self.runfitpupil.isChecked(),
            "runsrdtrans": self.runsrdtrans.isChecked(),
            "runhabituate": self.runhabituate.isChecked(),
            "jump_queue": self.jump_queue.isChecked(),
            "suite2p_env": self.suite2p_env.text().strip(),
            "settings_json": self.settings_json.toPlainText(),
            "srdtrans_json": self.srdtrans_json.toPlainText(),
            "topology": self.detected_descriptor.topology if self.detected_descriptor else None,
            "nchannels": self.detected_descriptor.nchannels if self.detected_descriptor else None,
            "standard": self.standard_widget.preset_state(),
            "meso": self.meso_widget.preset_state(),
        }

    def _apply_preset_payload(self, payload: dict):
        if payload.get("userID"):
            self.user_edit.setText(payload["userID"])
            self.refresh_preset_list()
        self.refresh_config_choices()
        self.mode_combo.setCurrentIndex(0 if payload.get("mode", "single") == "single" else 1)
        self.queue_combo.setCurrentIndex(0 if payload.get("queue", "step1") == "step1" else 1)
        self.runs2p.setChecked(payload.get("runs2p", True))
        self.rundlc.setChecked(payload.get("rundlc", True))
        self.runfitpupil.setChecked(payload.get("runfitpupil", True))
        self.runsrdtrans.setChecked(payload.get("runsrdtrans", False))
        self.runhabituate.setChecked(payload.get("runhabituate", False))
        self.jump_queue.setChecked(payload.get("jump_queue", False))
        self.suite2p_env.setText(payload.get("suite2p_env", ""))
        self.settings_json.setPlainText(payload.get("settings_json", "{}"))
        self.srdtrans_json.setPlainText(
            payload.get(
                "srdtrans_json",
                '{"model_root": "/home/adamranson/data/srt_models", "model": "", "patch_x": 160, "patch_t": 160, "overlap_factor": 0.5, "gpu": "0", "channels": ["ch1"]}',
            )
        )

        if self.detected_descriptor is None:
            self.pending_preset = payload
            self.summary_box.setPlainText(
                "Preset loaded.\n"
                "Add at least one expID to detect experiment topology and apply "
                "Suite2p-specific preset settings."
            )
            return

        if self.detected_descriptor.topology == "standard":
            self.standard_widget.apply_preset(payload.get("standard", {}), self.detected_descriptor.nchannels)
        else:
            self.meso_widget.apply_preset(payload.get("meso", {}))

    def _preset_compatibility_warning(self, payload: dict) -> Optional[str]:
        if self.detected_descriptor is None:
            return (
                "No experiment metadata is currently selected.\n\n"
                "Add at least one expID first so the GUI can check whether this saved config "
                "matches the experiment topology and channel count."
            )

        warnings = []
        for exp_id in self.exp_editor.values()[1:]:
            try:
                extra_descriptor = describe_experiment(self.user_edit.text().strip(), exp_id)
            except Exception as exc:
                warnings.append(f"could not inspect selected expID {exp_id}: {exc}")
                continue
            compatible, reason = self._is_compatible(self.detected_descriptor, extra_descriptor)
            if not compatible:
                warnings.append(f"selected expID {exp_id} is incompatible with the first expID: {reason}")

        preset_topology = payload.get("topology")
        if preset_topology and preset_topology != self.detected_descriptor.topology:
            warnings.append(
                f"topology differs: preset is {preset_topology}, "
                f"selected experiment is {self.detected_descriptor.topology}"
            )
        preset_nchannels = payload.get("nchannels")
        if preset_nchannels and int(preset_nchannels) != int(self.detected_descriptor.nchannels):
            warnings.append(
                f"channel count differs: preset has {preset_nchannels}, "
                f"selected experiment has {self.detected_descriptor.nchannels}"
            )

        if self.detected_descriptor.topology == "meso":
            preset_paths = set((payload.get("meso", {}).get("paths") or {}).keys())
            selected_paths = set(self.detected_descriptor.per_path.keys())
            if preset_paths and preset_paths != selected_paths:
                warnings.append(
                    "mesoscope path set differs: preset has "
                    f"{', '.join(sorted(preset_paths))}; selected experiment has "
                    f"{', '.join(sorted(selected_paths))}"
                )

        if not warnings:
            return None
        return "This saved config may be incompatible with the selected expIDs:\n\n- " + "\n- ".join(warnings)

    def save_preset(self):
        preset_root = self._preset_root()
        _ensure_preset_dir(preset_root)
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Step 1 Preset", "Preset name:")
        if not ok or not name.strip():
            return
        safe_name = _safe_preset_name(name)
        if not safe_name:
            QtWidgets.QMessageBox.warning(self, "Save Preset", "Preset name is not valid.")
            return
        payload = self._preset_payload()
        path = preset_root / f"{safe_name}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.refresh_preset_list()
        QtWidgets.QMessageBox.information(self, "Save Preset", f"Saved preset:\n{path}")

    def load_preset(self):
        path = self._selected_preset_path()
        if not path:
            QtWidgets.QMessageBox.information(self, "Load Preset", "Select a saved config first.")
            return
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        warning = self._preset_compatibility_warning(payload)
        if warning is not None:
            response = QtWidgets.QMessageBox.warning(
                self,
                "Load Preset",
                warning + "\n\nLoad it anyway?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if response != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self._apply_preset_payload(payload)
        if self.detected_descriptor is not None:
            QtWidgets.QMessageBox.information(self, "Load Preset", f"Loaded preset:\n{path}")

    def delete_preset(self):
        path = self._selected_preset_path()
        if not path:
            QtWidgets.QMessageBox.information(self, "Delete Preset", "Select a saved config first.")
            return
        response = QtWidgets.QMessageBox.question(
            self,
            "Delete Preset",
            f"Delete saved config?\n{path}",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if response != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        path.unlink()
        self.refresh_preset_list()

    def rename_preset(self):
        path = self._selected_preset_path()
        if not path:
            QtWidgets.QMessageBox.information(self, "Rename Preset", "Select a saved config first.")
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Rename Step 1 Preset",
            "New preset name:",
            text=path.stem,
        )
        if not ok or not name.strip():
            return
        safe_name = _safe_preset_name(name)
        if not safe_name:
            QtWidgets.QMessageBox.warning(self, "Rename Preset", "Preset name is not valid.")
            return
        new_path = path.with_name(f"{safe_name}.json")
        if new_path.exists() and new_path != path:
            QtWidgets.QMessageBox.warning(self, "Rename Preset", f"Preset already exists:\n{new_path}")
            return
        path.rename(new_path)
        self.refresh_preset_list()

    def show_preset_help(self):
        QtWidgets.QMessageBox.information(
            self,
            "Saved Step 1 Configs",
            "First add exp IDs, then load a saved config or configure a new one.\n\n"
            "The GUI uses the selected exp IDs to detect standard vs mesoscope layout, "
            "channel count, paths, and ROIs. Loading a saved config before adding exp IDs "
            "prevents that compatibility check.",
        )

    def load_s2p_config_from_file(self):
        config_dir = S2P_CONFIG_ROOT / (self.user_edit.text().strip() or self.username)
        path_text, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Suite2p Config",
            str(config_dir if config_dir.exists() else S2P_CONFIG_ROOT),
            "NumPy config (*.npy)",
        )
        if not path_text:
            return
        try:
            dialog = Suite2pOpsEditorDialog(Path(path_text), self, default_save_dir=config_dir)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Load Suite2p Config", str(exc))
            return
        dialog.exec()
        self.refresh_config_choices()

    def submit_job(self):
        try:
            config = self._build_step1_config()
            run_step1_batch_universal(config)
            QtWidgets.QMessageBox.information(self, "Step 1", "Step 1 job submitted.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Step 1", str(exc))


class Step2Tab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.username = getpass.getuser()
        self.step2_thread = None
        self.step2_worker = None
        self._build_ui()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        toolbar = QtWidgets.QHBoxLayout()
        self.load_preset_button = QtWidgets.QPushButton("Load Preset")
        self.save_preset_button = QtWidgets.QPushButton("Save Preset")
        self.run_button = QtWidgets.QPushButton("Run Step 2")
        toolbar.addWidget(self.load_preset_button)
        toolbar.addWidget(self.save_preset_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.run_button)
        outer.addLayout(toolbar)

        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        controls_widget = QtWidgets.QWidget()
        controls_layout = QtWidgets.QVBoxLayout(controls_widget)

        form = QtWidgets.QFormLayout()
        self.user_edit = QtWidgets.QLineEdit(self.username)
        form.addRow("userID", self.user_edit)
        self.exp_editor = ExperimentListEditor()
        form.addRow("expIDs", self.exp_editor)
        self.pre_secs = QtWidgets.QDoubleSpinBox()
        self.pre_secs.setRange(0, 600)
        self.pre_secs.setValue(5)
        form.addRow("pre_secs", self.pre_secs)
        self.post_secs = QtWidgets.QDoubleSpinBox()
        self.post_secs.setRange(0, 600)
        self.post_secs.setValue(5)
        form.addRow("post_secs", self.post_secs)

        self.run_bonvision = QtWidgets.QCheckBox()
        self.run_bonvision.setChecked(True)
        form.addRow("run_bonvision", self.run_bonvision)
        self.run_s2p_timestamp = QtWidgets.QCheckBox()
        self.run_s2p_timestamp.setChecked(True)
        form.addRow("run_s2p_timestamp", self.run_s2p_timestamp)
        self.run_ephys = QtWidgets.QCheckBox()
        self.run_ephys.setChecked(True)
        form.addRow("run_ephys", self.run_ephys)
        self.run_dlc_timestamp = QtWidgets.QCheckBox()
        self.run_dlc_timestamp.setChecked(True)
        form.addRow("run_dlc_timestamp", self.run_dlc_timestamp)
        self.run_cuttraces = QtWidgets.QCheckBox()
        self.run_cuttraces.setChecked(True)
        form.addRow("run_cuttraces", self.run_cuttraces)

        self.settings_json = QtWidgets.QPlainTextEdit(
            json.dumps(
                {
                    "neuropil_coeff": [0.7, 0.7],
                    "subtract_overall_frame": False,
                },
                indent=2,
            )
        )
        form.addRow("settings JSON", self.settings_json)
        controls_layout.addLayout(form)
        controls_layout.addStretch(1)

        self.step2_output = QtWidgets.QPlainTextEdit()
        self.step2_output.setReadOnly(True)

        main_splitter.addWidget(controls_widget)
        main_splitter.addWidget(self._group_box("Step 2 Output", self.step2_output))
        main_splitter.setSizes([520, 720])
        outer.addWidget(main_splitter)

        self.load_preset_button.clicked.connect(self.load_preset)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.run_button.clicked.connect(self.run_step2)

    def _group_box(self, title: str, widget: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox(title)
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.addWidget(widget)
        return box

    def _build_config(self) -> dict:
        user_id = self.user_edit.text().strip()
        exp_ids = self.exp_editor.values()
        if not user_id or not exp_ids:
            raise ValueError("userID and at least one expID are required.")
        config = {
            "userID": user_id,
            "expIDs": exp_ids,
            "pre_secs": self.pre_secs.value(),
            "post_secs": self.post_secs.value(),
            "run_bonvision": self.run_bonvision.isChecked(),
            "run_s2p_timestamp": self.run_s2p_timestamp.isChecked(),
            "run_ephys": self.run_ephys.isChecked(),
            "run_dlc_timestamp": self.run_dlc_timestamp.isChecked(),
            "run_cuttraces": self.run_cuttraces.isChecked(),
        }
        settings_text = self.settings_json.toPlainText().strip()
        if settings_text:
            config["settings"] = json.loads(settings_text)
        return config

    def _preset_payload(self) -> dict:
        return {
            "userID": self.user_edit.text().strip(),
            "pre_secs": self.pre_secs.value(),
            "post_secs": self.post_secs.value(),
            "run_bonvision": self.run_bonvision.isChecked(),
            "run_s2p_timestamp": self.run_s2p_timestamp.isChecked(),
            "run_ephys": self.run_ephys.isChecked(),
            "run_dlc_timestamp": self.run_dlc_timestamp.isChecked(),
            "run_cuttraces": self.run_cuttraces.isChecked(),
            "settings_json": self.settings_json.toPlainText(),
        }

    def _apply_preset_payload(self, payload: dict):
        if payload.get("userID"):
            self.user_edit.setText(payload["userID"])
        self.pre_secs.setValue(float(payload.get("pre_secs", 5)))
        self.post_secs.setValue(float(payload.get("post_secs", 5)))
        self.run_bonvision.setChecked(payload.get("run_bonvision", True))
        self.run_s2p_timestamp.setChecked(payload.get("run_s2p_timestamp", True))
        self.run_ephys.setChecked(payload.get("run_ephys", True))
        self.run_dlc_timestamp.setChecked(payload.get("run_dlc_timestamp", True))
        self.run_cuttraces.setChecked(payload.get("run_cuttraces", True))
        self.settings_json.setPlainText(payload.get("settings_json", "{}"))

    def save_preset(self):
        preset_root = _step2_preset_root(self.user_edit.text().strip() or self.username)
        _ensure_preset_dir(preset_root)
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Step 2 Preset", "Preset name:")
        if not ok or not name.strip():
            return
        path = preset_root / f"{name.strip()}.json"
        path.write_text(json.dumps(self._preset_payload(), indent=2), encoding="utf-8")
        QtWidgets.QMessageBox.information(self, "Save Preset", f"Saved preset:\n{path}")

    def load_preset(self):
        preset_root = _step2_preset_root(self.user_edit.text().strip() or self.username)
        _ensure_preset_dir(preset_root)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Step 2 Preset",
            str(preset_root),
            "JSON (*.json)",
        )
        if not path:
            return
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self._apply_preset_payload(payload)

    def run_step2(self):
        try:
            config = self._build_config()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Step 2", str(exc))
            return

        if self.step2_thread is not None:
            QtWidgets.QMessageBox.warning(self, "Step 2", "Step 2 is already running.")
            return

        self.step2_output.clear()
        self._append_step2_output("** Starting Step 2\n")
        self.run_button.setEnabled(False)

        self.step2_thread = QtCore.QThread(self)
        self.step2_worker = Step2Worker(config)
        self.step2_worker.moveToThread(self.step2_thread)
        self.step2_thread.started.connect(self.step2_worker.run)
        self.step2_worker.output.connect(self._append_step2_output)
        self.step2_worker.finished.connect(self._step2_finished)
        self.step2_worker.failed.connect(self._step2_failed)
        self.step2_worker.finished.connect(self.step2_thread.quit)
        self.step2_worker.failed.connect(self.step2_thread.quit)
        self.step2_thread.finished.connect(self.step2_worker.deleteLater)
        self.step2_thread.finished.connect(self.step2_thread.deleteLater)
        self.step2_thread.finished.connect(self._clear_step2_worker)
        self.step2_thread.start()

    def _append_step2_output(self, text: str):
        at_bottom = (
            self.step2_output.verticalScrollBar().value()
            == self.step2_output.verticalScrollBar().maximum()
        )
        self.step2_output.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.step2_output.insertPlainText(text)
        if at_bottom:
            self.step2_output.verticalScrollBar().setValue(
                self.step2_output.verticalScrollBar().maximum()
            )

    def _step2_finished(self):
        self._append_step2_output("\n** Step 2 finished without errors\n")
        self.run_button.setEnabled(True)

    def _step2_failed(self, message: str):
        self._append_step2_output(f"\n** Step 2 failed: {message}\n")
        self.run_button.setEnabled(True)

    def _clear_step2_worker(self):
        self.step2_thread = None
        self.step2_worker = None


class SplitTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.username = getpass.getuser()
        self.split_thread = None
        self.split_worker = None
        self._build_ui()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        toolbar = QtWidgets.QHBoxLayout()
        self.expand_button = QtWidgets.QPushButton("Expand")
        self.split_button = QtWidgets.QPushButton("Split")
        toolbar.addStretch(1)
        toolbar.addWidget(self.expand_button)
        toolbar.addWidget(self.split_button)
        outer.addLayout(toolbar)

        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        left_widget = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_widget)

        form = QtWidgets.QFormLayout()
        self.user_edit = QtWidgets.QLineEdit(self.username)
        form.addRow("userID", self.user_edit)
        self.exp_edit = QtWidgets.QLineEdit()
        self.exp_edit.setPlaceholderText("Combined/base expID")
        form.addRow("combined expID", self.exp_edit)
        left_layout.addLayout(form)

        self.source_table = QtWidgets.QTableWidget(0, 3)
        self.source_table.setHorizontalHeaderLabels(
            ["Source expID", "Frames", "Timeline seconds"]
        )
        self.source_table.horizontalHeader().setStretchLastSection(True)
        self.source_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.source_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        left_layout.addWidget(self.source_table)

        self.split_output = QtWidgets.QPlainTextEdit()
        self.split_output.setReadOnly(True)

        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(self._group_box("Split Output", self.split_output))
        main_splitter.setSizes([620, 620])
        outer.addWidget(main_splitter)

        self.expand_button.clicked.connect(self.expand_combined_experiment)
        self.split_button.clicked.connect(self.run_split)

    def _group_box(self, title: str, widget: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox(title)
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.addWidget(widget)
        return box

    def _split_inputs(self) -> tuple[str, str]:
        user_id = self.user_edit.text().strip()
        exp_id = self.exp_edit.text().strip()
        if not user_id or not exp_id:
            raise ValueError("userID and combined expID are required.")
        return user_id, exp_id

    def expand_combined_experiment(self):
        try:
            user_id, exp_id = self._split_inputs()
            rows = inspect_combined_split_sources(user_id, exp_id)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Split Expand", str(exc))
            return

        self.source_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            seconds = row["timeline_seconds"]
            seconds_text = "?" if seconds is None else f"{seconds:.2f}"
            frames_text = "?" if row["frames"] is None else str(row["frames"])
            values = [row["source_exp_id"], frames_text, seconds_text]
            for col_index, value in enumerate(values):
                self.source_table.setItem(row_index, col_index, QtWidgets.QTableWidgetItem(value))
        self.source_table.resizeColumnsToContents()
        if rows:
            first = rows[0]
            self._append_split_output(
                f"Expanded {exp_id}\n"
                f"Split root: {first['split_root']}\n"
                f"Suite2p source: {first['suite2p_path']}\n"
            )
            warnings = [warning for row in rows for warning in row.get("warnings", [])]
            for warning in warnings:
                self._append_split_output(f"WARNING: {warning}\n")

    def run_split(self):
        try:
            user_id, exp_id = self._split_inputs()
            rows = inspect_combined_split_sources(user_id, exp_id)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Split", str(exc))
            return

        if any(row["frames"] is None for row in rows):
            QtWidgets.QMessageBox.critical(
                self,
                "Split",
                "Cannot split because combined Suite2p metadata is incomplete. "
                "Expand the experiment and check the warning in Split Output.",
            )
            return

        if self.split_thread is not None:
            QtWidgets.QMessageBox.warning(self, "Split", "Split is already running.")
            return

        self.split_output.clear()
        self._append_split_output(f"** Starting split for {exp_id}\n")
        self.expand_button.setEnabled(False)
        self.split_button.setEnabled(False)

        self.split_thread = QtCore.QThread(self)
        self.split_worker = SplitWorker(user_id, exp_id)
        self.split_worker.moveToThread(self.split_thread)
        self.split_thread.started.connect(self.split_worker.run)
        self.split_worker.output.connect(self._append_split_output)
        self.split_worker.finished.connect(self._split_finished)
        self.split_worker.failed.connect(self._split_failed)
        self.split_worker.finished.connect(self.split_thread.quit)
        self.split_worker.failed.connect(self.split_thread.quit)
        self.split_thread.finished.connect(self.split_worker.deleteLater)
        self.split_thread.finished.connect(self.split_thread.deleteLater)
        self.split_thread.finished.connect(self._clear_split_worker)
        self.split_thread.start()

    def _append_split_output(self, text: str):
        at_bottom = (
            self.split_output.verticalScrollBar().value()
            == self.split_output.verticalScrollBar().maximum()
        )
        self.split_output.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.split_output.insertPlainText(text)
        if at_bottom:
            self.split_output.verticalScrollBar().setValue(
                self.split_output.verticalScrollBar().maximum()
            )

    def _split_finished(self):
        self._append_split_output("\n** Split finished without errors\n")
        self.expand_button.setEnabled(True)
        self.split_button.setEnabled(True)

    def _split_failed(self, message: str):
        self._append_split_output(f"\n** Split failed: {message}\n")
        self.expand_button.setEnabled(True)
        self.split_button.setEnabled(True)

    def _clear_split_worker(self):
        self.split_thread = None
        self.split_worker = None


class QueueManagerWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lab Queue Manager")
        self.resize(1400, 900)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(QueueTab(), "Queue")
        tabs.addTab(Step1Tab(), "Step 1")
        tabs.addTab(Step2Tab(), "Step 2")
        tabs.addTab(SplitTab(), "Split")
        self.setCentralWidget(tabs)


def launch():
    app = QtWidgets.QApplication.instance()
    created = False
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
        created = True
    win = QueueManagerWindow()
    win.show()
    if created:
        return app.exec()
    return 0


def main():
    raise SystemExit(launch())


if __name__ == "__main__":
    main()
