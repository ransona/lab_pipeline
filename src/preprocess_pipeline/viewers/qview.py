import getpass
import json
import os
import pickle
import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import tifffile
from PyQt6 import QtCore, QtWidgets

from preprocess_pipeline.shared import paths
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


class EditableConfigCombo(QtWidgets.QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)

    def value(self) -> str:
        return self.currentText().strip()

    def set_value(self, value: str):
        self.setCurrentText(value or "")


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
        self.user_totals_list = QtWidgets.QListWidget()
        top_splitter.addWidget(self._group_box("User Compute Times", self.user_totals_list))
        top_splitter.setSizes([360, 360, 180])
        main_splitter.addWidget(top_splitter)

        self.log_list = QtWidgets.QListWidget()
        main_splitter.addWidget(self._group_box("Log Feedback", self.log_list))
        main_splitter.setSizes([320, 260])
        layout.addWidget(main_splitter)

        self.queue_selector.currentIndexChanged.connect(self.on_queue_source_changed)
        self.remove_button.clicked.connect(self.remove_selected_job)
        self.queue_list.itemSelectionChanged.connect(self._remember_selection)
        self.queue_list.itemDoubleClicked.connect(self.show_selected_job_config)

    def _group_box(self, title: str, widget: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox(title)
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.addWidget(widget)
        return box

    def _connect_timers(self):
        self.queue_timer = QtCore.QTimer(self)
        self.queue_timer.timeout.connect(self.refresh_queue_list)
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
            self.log_list.addItem(line.rstrip())
        self.log_list.scrollToBottom()

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

    def show_selected_job_config(self):
        try:
            job_name, queued_command = self._load_selected_job()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Show Job Config", str(exc))
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(f"Queued Job Config: {job_name}")
        dialog.resize(900, 700)
        layout = QtWidgets.QVBoxLayout(dialog)
        text = QtWidgets.QPlainTextEdit(dialog)
        text.setReadOnly(True)
        text.setPlainText(json.dumps(queued_command, indent=2, default=str))
        layout.addWidget(text)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close, parent=dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

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
            self.log_list.addItem(line.rstrip())
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
        layout = QtWidgets.QFormLayout(self)
        self.same_for_both = QtWidgets.QCheckBox("Use same config for both channels")
        self.same_for_both.setChecked(True)
        self.ch1_combo = EditableConfigCombo()
        self.ch2_combo = EditableConfigCombo()
        layout.addRow(self.same_for_both)
        layout.addRow("Channel 1 config", self.ch1_combo)
        layout.addRow("Channel 2 config", self.ch2_combo)
        self.same_for_both.toggled.connect(self._sync_channel_mode)
        self._sync_channel_mode()

    def set_config_files(self, config_files: list[str]):
        self._config_files = list(config_files)
        for combo in (self.ch1_combo, self.ch2_combo):
            current = combo.value()
            combo.clear()
            combo.addItems(self._config_files)
            combo.set_value(current)

    def set_channel_count(self, nchannels: int):
        dual = nchannels >= 2
        self.same_for_both.setVisible(dual)
        if not dual:
            self.same_for_both.setChecked(True)
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
        self.ch1_combo.set_value(preset.get("ch1", ""))
        self.ch2_combo.set_value(preset.get("ch2", ""))
        self.set_channel_count(nchannels)

    def preset_state(self) -> dict:
        return {
            "same_for_both": self.same_for_both.isChecked(),
            "ch1": self.ch1_combo.value(),
            "ch2": self.ch2_combo.value(),
        }


class PathConfigRow(QtWidgets.QWidget):
    def __init__(self, path_name: str, nchannels: int, config_files: list[str], parent=None):
        super().__init__(parent)
        self.path_name = path_name
        self.nchannels = nchannels
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QtWidgets.QLabel(path_name))
        self.ch1_combo = EditableConfigCombo()
        self.ch1_combo.addItems(config_files)
        layout.addWidget(QtWidgets.QLabel("Ch1"))
        layout.addWidget(self.ch1_combo, 1)
        self.same_for_both = QtWidgets.QCheckBox("Same for ch2")
        self.same_for_both.setChecked(True)
        layout.addWidget(self.same_for_both)
        self.ch2_combo = EditableConfigCombo()
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

    def set_context(self, descriptor: ExperimentDescriptor, config_files: list[str]):
        self.descriptor = descriptor
        self.config_files = list(config_files)
        self.global_widget.set_config_files(self.config_files)
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
            row = PathConfigRow(path_name, meta.nchannels, self.config_files)
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
        self._build_ui()
        self.refresh_config_choices()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)

        toolbar = QtWidgets.QHBoxLayout()
        self.load_preset_button = QtWidgets.QPushButton("Load Preset")
        self.save_preset_button = QtWidgets.QPushButton("Save Preset")
        self.submit_button = QtWidgets.QPushButton("Submit Step 1 Job")
        toolbar.addWidget(self.load_preset_button)
        toolbar.addWidget(self.save_preset_button)
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
        self.standard_widget = StandardConfigWidget()
        self.meso_widget = MesoConfigWidget()
        self.config_stack = QtWidgets.QStackedWidget()
        self.config_stack.addWidget(self.standard_widget)
        self.config_stack.addWidget(self.meso_widget)
        config_layout.addWidget(self.config_stack)

        self.settings_json = QtWidgets.QPlainTextEdit("{}")
        self.settings_json.setPlaceholderText('Optional JSON dict for step1_config["settings"]')
        config_layout.addWidget(QtWidgets.QLabel('settings JSON'))
        config_layout.addWidget(self.settings_json)
        right_layout.addWidget(self.config_group)
        main_splitter.addWidget(right)
        main_splitter.setSizes([420, 680])

        self.exp_editor.changed.connect(self.on_exp_list_changed)
        self.user_edit.editingFinished.connect(self.on_exp_list_changed)
        self.load_preset_button.clicked.connect(self.load_preset)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.submit_button.clicked.connect(self.submit_job)

    def refresh_config_choices(self):
        config_dir = S2P_CONFIG_ROOT / self.user_edit.text().strip()
        config_files = sorted(p.name for p in config_dir.glob("*.npy")) if config_dir.exists() else []
        self.standard_widget.set_config_files(config_files)
        if self.detected_descriptor is not None and self.detected_descriptor.topology == "meso":
            self.meso_widget.set_context(self.detected_descriptor, config_files)

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
                self.meso_widget.set_context(first_descriptor, self.standard_widget._config_files)
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
        }
        if self.runhabituate.isChecked():
            config["runhabituate"] = True
        if self.jump_queue.isChecked():
            config["jump_queue"] = True
        if self.queue_combo.currentIndex() == 1:
            config["queue"] = "debug"
        suite2p_env = self.suite2p_env.text().strip()
        if suite2p_env:
            config["suite2p_env"] = suite2p_env
        settings_text = self.settings_json.toPlainText().strip()
        if settings_text and settings_text != "{}":
            config["settings"] = json.loads(settings_text)
        return config

    def _preset_payload(self) -> dict:
        return {
            "userID": self.user_edit.text().strip(),
            "mode": "single" if self.mode_combo.currentIndex() == 0 else "combined",
            "queue": "step1" if self.queue_combo.currentIndex() == 0 else "debug",
            "runs2p": self.runs2p.isChecked(),
            "rundlc": self.rundlc.isChecked(),
            "runfitpupil": self.runfitpupil.isChecked(),
            "runhabituate": self.runhabituate.isChecked(),
            "jump_queue": self.jump_queue.isChecked(),
            "suite2p_env": self.suite2p_env.text().strip(),
            "settings_json": self.settings_json.toPlainText(),
            "topology": self.detected_descriptor.topology if self.detected_descriptor else None,
            "nchannels": self.detected_descriptor.nchannels if self.detected_descriptor else None,
            "standard": self.standard_widget.preset_state(),
            "meso": self.meso_widget.preset_state(),
        }

    def _apply_preset_payload(self, payload: dict):
        if payload.get("userID"):
            self.user_edit.setText(payload["userID"])
        self.refresh_config_choices()
        self.mode_combo.setCurrentIndex(0 if payload.get("mode", "single") == "single" else 1)
        self.queue_combo.setCurrentIndex(0 if payload.get("queue", "step1") == "step1" else 1)
        self.runs2p.setChecked(payload.get("runs2p", True))
        self.rundlc.setChecked(payload.get("rundlc", True))
        self.runfitpupil.setChecked(payload.get("runfitpupil", True))
        self.runhabituate.setChecked(payload.get("runhabituate", False))
        self.jump_queue.setChecked(payload.get("jump_queue", False))
        self.suite2p_env.setText(payload.get("suite2p_env", ""))
        self.settings_json.setPlainText(payload.get("settings_json", "{}"))

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

    def save_preset(self):
        preset_root = _step1_preset_root(self.user_edit.text().strip() or self.username)
        _ensure_preset_dir(preset_root)
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Step 1 Preset", "Preset name:")
        if not ok or not name.strip():
            return
        payload = self._preset_payload()
        path = preset_root / f"{name.strip()}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        QtWidgets.QMessageBox.information(self, "Save Preset", f"Saved preset:\n{path}")

    def load_preset(self):
        preset_root = _step1_preset_root(self.user_edit.text().strip() or self.username)
        _ensure_preset_dir(preset_root)
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Step 1 Preset",
            str(preset_root),
            "JSON (*.json)",
        )
        if not path:
            return
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self._apply_preset_payload(payload)
        if self.detected_descriptor is not None:
            QtWidgets.QMessageBox.information(self, "Load Preset", f"Loaded preset:\n{path}")

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
        outer.addLayout(form)

        self.load_preset_button.clicked.connect(self.load_preset)
        self.save_preset_button.clicked.connect(self.save_preset)
        self.run_button.clicked.connect(self.run_step2)

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
            run_step2_batch(config)
            QtWidgets.QMessageBox.information(self, "Step 2", "Step 2 processing started.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Step 2", str(exc))


class QueueManagerWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lab Queue Manager")
        self.resize(1400, 900)
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(QueueTab(), "Queue")
        tabs.addTab(Step1Tab(), "Step 1")
        tabs.addTab(Step2Tab(), "Step 2")
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
