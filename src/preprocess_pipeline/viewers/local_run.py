import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

from PyQt6 import QtCore, QtGui, QtWidgets


APP_ROOT = Path(__file__).resolve().parents[3] / "apps"
SRC_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_RAW_ROOT = r"F:\Local_Repository"
DEFAULT_PROCESSED_ROOT = r"F:\Local_Repository_Processed"
DEFAULT_NAS_ROOT = r"\\ar-lab-nas1\DataServer\Remote_Repository"
DEFAULT_S2P_CONFIG_ROOT = r"F:\s2p_ops"
DEFAULT_SUITE2P_ENV = "suite2p_1.1.0"


def _console_python_executable() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        python_exe = executable.with_name("python.exe")
        if python_exe.exists():
            return str(python_exe)
    return sys.executable


def _is_exp_id(name: str) -> bool:
    return re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d+_[A-Za-z0-9]+", name) is not None


def _latest_exp_id(local_raw_root: str) -> str:
    root = Path(local_raw_root)
    if not root.is_dir():
        return ""
    candidates = []
    for animal_dir in root.iterdir():
        if not animal_dir.is_dir():
            continue
        for exp_dir in animal_dir.iterdir():
            if exp_dir.is_dir() and _is_exp_id(exp_dir.name):
                candidates.append((exp_dir.stat().st_mtime, exp_dir.name))
    if not candidates:
        return ""
    return sorted(candidates)[-1][1]


def _subdirs(path_text: str) -> list[str]:
    root = Path(path_text)
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir())


def _suite2p_configs(config_root: str, user_id: str) -> list[str]:
    root = Path(config_root) / user_id
    if not root.is_dir():
        return []
    return sorted(path.name for path in root.glob("*.npy"))


def _write_temp_config(prefix: str, text: str, processed_root: str) -> Path:
    root = Path(processed_root) / "_pipeline_jobs" / "local_gui_configs"
    root.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", suffix=".py", prefix=prefix, dir=root, delete=False, encoding="utf-8")
    with handle:
        handle.write(text)
    return Path(handle.name)


class CommandRunner(QtCore.QObject):
    output = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(int)
    failed_to_start = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process: Optional[QtCore.QProcess] = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.state() != QtCore.QProcess.ProcessState.NotRunning

    def start(self, program: str, args: list[str], cwd: Path, env: Optional[Dict[str, str]] = None):
        if self.is_running():
            raise RuntimeError("A command is already running.")

        self.process = QtCore.QProcess(self)
        self.process.setWorkingDirectory(str(cwd))
        process_env = QtCore.QProcessEnvironment.systemEnvironment()
        for key, value in (env or {}).items():
            process_env.insert(key, value)
        self.process.setProcessEnvironment(process_env)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.output.emit("[command] " + " ".join([program, *args]) + "\n")
        self.process.start(program, args)

    def _read_output(self):
        if not self.process:
            return
        data = bytes(self.process.readAllStandardOutput()).decode(errors="replace")
        if data:
            self.output.emit(data)

    def _finished(self, exit_code: int, _exit_status):
        self._read_output()
        self.output.emit(f"\n[finished with exit code {exit_code}]\n")
        self.finished.emit(exit_code)

    def _error(self, error):
        if error == QtCore.QProcess.ProcessError.FailedToStart:
            self.failed_to_start.emit("Failed to start process.")


class LocalRunWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.runner = CommandRunner(self)
        self.runner.output.connect(self._append_output)
        self.runner.failed_to_start.connect(self._append_output)
        self.setWindowTitle("Local Pipeline Run")
        self._build_ui()
        self._refresh_users()
        self._refresh_exp_id()

    def _build_ui(self):
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)

        roots = QtWidgets.QGroupBox("Local paths")
        roots_form = QtWidgets.QFormLayout(roots)
        self.raw_root_edit = QtWidgets.QLineEdit(DEFAULT_RAW_ROOT)
        self.processed_root_edit = QtWidgets.QLineEdit(DEFAULT_PROCESSED_ROOT)
        self.nas_root_edit = QtWidgets.QLineEdit(DEFAULT_NAS_ROOT)
        self.config_root_edit = QtWidgets.QLineEdit(DEFAULT_S2P_CONFIG_ROOT)
        self.suite2p_env_edit = QtWidgets.QLineEdit(DEFAULT_SUITE2P_ENV)
        for label, widget in (
            ("Local raw repository", self.raw_root_edit),
            ("Local processed repository", self.processed_root_edit),
            ("NAS repository", self.nas_root_edit),
            ("Suite2p config root", self.config_root_edit),
            ("Suite2p conda env", self.suite2p_env_edit),
        ):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(widget, 1)
            button = QtWidgets.QPushButton("Browse")
            button.clicked.connect(lambda _checked=False, edit=widget: self._browse_folder(edit))
            row.addWidget(button)
            roots_form.addRow(label, row)
        layout.addWidget(roots)

        split_box = QtWidgets.QGroupBox("1) Split to paths and ROIs")
        split_layout = QtWidgets.QHBoxLayout(split_box)
        self.keep_raw_tifs_check = QtWidgets.QCheckBox("Keep original unsplit TIFFs")
        self.split_button = QtWidgets.QPushButton("Split local repository")
        self.split_button.clicked.connect(self.run_split)
        split_layout.addWidget(self.keep_raw_tifs_check)
        split_layout.addStretch(1)
        split_layout.addWidget(self.split_button)
        layout.addWidget(split_box)

        step1_box = QtWidgets.QGroupBox("2) Run Step 1")
        step1_form = QtWidgets.QFormLayout(step1_box)
        self.user_combo = QtWidgets.QComboBox()
        self.user_combo.setEditable(True)
        self.user_combo.currentTextChanged.connect(self._refresh_configs)
        self.exp_id_edit = QtWidgets.QLineEdit()
        self.config_combo = QtWidgets.QComboBox()
        self.config_combo.setEditable(True)
        self.functional_chan_combo = QtWidgets.QComboBox()
        self.functional_chan_combo.addItems(["1", "2"])
        self.chan2_detection_combo = QtWidgets.QComboBox()
        self.chan2_detection_combo.addItems(["off", "cellpose"])
        self.refresh_button = QtWidgets.QPushButton("Refresh users/configs/expID")
        self.refresh_button.clicked.connect(self._refresh_all)
        self.step1_button = QtWidgets.QPushButton("Run Step 1")
        self.step1_button.clicked.connect(self.run_step1)
        step1_form.addRow("Username", self.user_combo)
        step1_form.addRow("expID", self.exp_id_edit)
        step1_form.addRow("Suite2p config", self.config_combo)
        step1_form.addRow("Functional channel", self.functional_chan_combo)
        step1_form.addRow("Channel 2 detection", self.chan2_detection_combo)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        buttons.addWidget(self.step1_button)
        step1_form.addRow(buttons)
        layout.addWidget(step1_box)

        step2_box = QtWidgets.QGroupBox("3) Run Step 2")
        step2_form = QtWidgets.QFormLayout(step2_box)
        self.pre_secs_spin = QtWidgets.QDoubleSpinBox()
        self.pre_secs_spin.setRange(0, 120)
        self.pre_secs_spin.setValue(5)
        self.post_secs_spin = QtWidgets.QDoubleSpinBox()
        self.post_secs_spin.setRange(0, 120)
        self.post_secs_spin.setValue(5)
        self.step2_button = QtWidgets.QPushButton("Run Step 2: Suite2p timestamps + cut traces")
        self.step2_button.clicked.connect(self.run_step2)
        step2_form.addRow("Pre seconds", self.pre_secs_spin)
        step2_form.addRow("Post seconds", self.post_secs_spin)
        step2_form.addRow(self.step2_button)
        layout.addWidget(step2_box)

        self.output = QtWidgets.QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(260)
        layout.addWidget(QtWidgets.QLabel("Command output"))
        layout.addWidget(self.output, 1)

        self.setCentralWidget(central)
        self.resize(1000, 850)

    def _browse_folder(self, edit: QtWidgets.QLineEdit):
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder", edit.text())
        if selected:
            edit.setText(selected)
            self._refresh_all()

    def _refresh_all(self):
        self._refresh_users()
        self._refresh_exp_id()
        self._refresh_configs()

    def _refresh_users(self):
        current = self.user_combo.currentText().strip()
        users = _subdirs(self.config_root_edit.text().strip())
        self.user_combo.blockSignals(True)
        self.user_combo.clear()
        self.user_combo.addItems(users)
        if current:
            index = self.user_combo.findText(current)
            if index < 0:
                self.user_combo.addItem(current)
                index = self.user_combo.findText(current)
            self.user_combo.setCurrentIndex(index)
        elif users:
            self.user_combo.setCurrentIndex(0)
        else:
            self.user_combo.setEditText(os.environ.get("USERNAME") or os.environ.get("USER") or "adamranson")
        self.user_combo.blockSignals(False)
        self._refresh_configs()

    def _refresh_exp_id(self):
        if not self.exp_id_edit.text().strip():
            self.exp_id_edit.setText(_latest_exp_id(self.raw_root_edit.text().strip()))

    def _refresh_configs(self):
        current = self.config_combo.currentText().strip()
        configs = _suite2p_configs(self.config_root_edit.text().strip(), self.user_combo.currentText().strip())
        self.config_combo.clear()
        self.config_combo.addItems(configs)
        if current:
            index = self.config_combo.findText(current)
            if index < 0:
                self.config_combo.addItem(current)
                index = self.config_combo.findText(current)
            self.config_combo.setCurrentIndex(index)

    def _append_output(self, text: str):
        at_bottom = self.output.verticalScrollBar().value() == self.output.verticalScrollBar().maximum()
        self.output.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.output.insertPlainText(text)
        if at_bottom:
            self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())

    def _start_python(self, args: list[str]):
        env = {"PYTHONPATH": str(SRC_ROOT)}
        self.runner.start(_console_python_executable(), args, cwd=APP_ROOT.parent, env=env)

    def _require_common_fields(self) -> tuple[str, str, str]:
        user_id = self.user_combo.currentText().strip()
        exp_id = self.exp_id_edit.text().strip()
        config_name = self.config_combo.currentText().strip()
        if not user_id:
            raise ValueError("Username is required.")
        if not exp_id:
            raise ValueError("expID is required.")
        if not config_name:
            raise ValueError("Suite2p config is required.")
        return user_id, exp_id, config_name

    def _guard_not_running(self) -> bool:
        if self.runner.is_running():
            QtWidgets.QMessageBox.warning(self, "Command running", "Wait for the current command to finish.")
            return False
        return True

    def run_split(self):
        if not self._guard_not_running():
            return
        exp_id = self.exp_id_edit.text().strip()
        if not exp_id:
            QtWidgets.QMessageBox.warning(self, "Missing expID", "Select or enter the expID to split first.")
            return
        args = [
            "-u",
            "-m",
            "preprocess_pipeline.local.meso_split",
            self.raw_root_edit.text().strip(),
            "--target-exp-id",
            exp_id,
        ]
        if self.keep_raw_tifs_check.isChecked():
            args.append("--keep-raw-tifs")
        self._start_python(args)

    def run_step1(self):
        if not self._guard_not_running():
            return
        try:
            user_id, exp_id, config_name = self._require_common_fields()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Missing Step 1 field", str(exc))
            return

        config_text = f'''from pathlib import Path
import sys
sys.path.insert(0, {str(SRC_ROOT)!r})
from preprocess_pipeline.step1.run_batch import run_step1_batch_universal

step1_config = {{
    "userID": {user_id!r},
    "expIDs": [{exp_id!r}],
    "local_raw_repository_root": {self.raw_root_edit.text().strip()!r},
    "local_processed_repository_root": {self.processed_root_edit.text().strip()!r},
    "local_nas_repository_root": {self.nas_root_edit.text().strip()!r},
    "suite2p_config_root": {self.config_root_edit.text().strip()!r},
    "suite2p_env": {self.suite2p_env_edit.text().strip()!r},
    "suite2p_config": {{
        "default": {{
            "config": {config_name!r},
            "functional_chan": {int(self.functional_chan_combo.currentText())},
            "chan2_detection": {self.chan2_detection_combo.currentText()!r},
        }},
    }},
    "runs2p": True,
    "rundlc": False,
    "runfitpupil": False,
}}
run_step1_batch_universal(step1_config)
'''
        config_path = _write_temp_config("step1_local_", config_text, self.processed_root_edit.text().strip())
        self._start_python(["-u", str(config_path)])

    def run_step2(self):
        if not self._guard_not_running():
            return
        user_id = self.user_combo.currentText().strip()
        exp_id = self.exp_id_edit.text().strip()
        if not user_id or not exp_id:
            QtWidgets.QMessageBox.warning(self, "Missing Step 2 field", "Username and expID are required.")
            return

        config_text = f'''from pathlib import Path
import sys
sys.path.insert(0, {str(SRC_ROOT)!r})
from preprocess_pipeline.step2.run_batch import run_step2_batch

step2_config = {{
    "userID": {user_id!r},
    "expIDs": [{exp_id!r}],
    "local_raw_repository_root": {self.raw_root_edit.text().strip()!r},
    "local_processed_repository_root": {self.processed_root_edit.text().strip()!r},
    "local_nas_repository_root": {self.nas_root_edit.text().strip()!r},
    "pre_secs": {float(self.pre_secs_spin.value())},
    "post_secs": {float(self.post_secs_spin.value())},
    "run_bonvision": False,
    "run_s2p_timestamp": True,
    "run_ephys": False,
    "run_dlc_timestamp": False,
    "run_cuttraces": True,
    "settings": {{
        "neuropil_coeff": [0.7, 0.7],
        "subtract_overall_frame": False,
    }},
}}
run_step2_batch(step2_config)
'''
        config_path = _write_temp_config("step2_local_", config_text, self.processed_root_edit.text().strip())
        self._start_python(["-u", str(config_path)])


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = LocalRunWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
