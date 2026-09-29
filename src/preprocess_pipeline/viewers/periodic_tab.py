"""Periodic (frequency-encoded) retinotopy tab for the local runner."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from preprocess_pipeline import periodic


class _AnalysisWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int, str)
    finished = QtCore.pyqtSignal(str)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    @QtCore.pyqtSlot()
    def run(self):
        try:
            output = periodic.run_analysis(
                self.config, lambda done, total, text: self.progress.emit(done, total, text)
            )
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.finished.emit(str(output))


class _ImageView(QtWidgets.QLabel):
    """A label that always fits an array inside its available rectangle."""
    def __init__(self, empty_text="No output selected"):
        super().__init__(empty_text)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(1, 1)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Ignored)
        self._image = None
        self._empty_text = empty_text
        self.setStyleSheet("background: #111; color: #ddd; border: 1px solid #555;")

    def set_array(self, array, cmap="gray", low=1, high=99):
        values = np.asarray(array, dtype=np.float32)
        lo, hi = np.nanpercentile(values, (low, high))
        normal = np.clip((values - lo) / max(hi - lo, 1e-12), 0, 1)
        if cmap == "phase":
            hue = ((normal * 359) % 360).astype(np.int16)
            image = QtGui.QImage(hue.data, hue.shape[1], hue.shape[0], hue.strides[0], QtGui.QImage.Format.Format_Grayscale8)
            # QColor's HSV conversion is cheap at map size and avoids a matplotlib dependency.
            rgb = np.empty((*hue.shape, 3), dtype=np.uint8)
            for value in np.unique(hue):
                colour = QtGui.QColor.fromHsv(int(value), 255, 255)
                rgb[hue == value] = (colour.red(), colour.green(), colour.blue())
            self._image = QtGui.QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QtGui.QImage.Format.Format_RGB888).copy()
        else:
            image8 = np.ascontiguousarray((normal * 255).astype(np.uint8))
            self._image = QtGui.QImage(image8.data, image8.shape[1], image8.shape[0], image8.strides[0], QtGui.QImage.Format.Format_Grayscale8).copy()
        self._render()

    def clear_image(self, text=None):
        self._image = None
        self.setPixmap(QtGui.QPixmap())
        self.setText(text or self._empty_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def _render(self):
        if self._image is None:
            return
        self.setText("")
        self.setPixmap(QtGui.QPixmap.fromImage(self._image).scaled(
            self.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        ))


class PeriodicTab(QtWidgets.QWidget):
    """Processed-data adaptation of the standalone periodic_gui application."""
    def __init__(self, exp_id_getter, processed_root_getter, exp_id_setter=None, parent=None):
        super().__init__(parent)
        self._exp_id_getter, self._processed_root_getter = exp_id_getter, processed_root_getter
        self._exp_id_setter = exp_id_setter
        self._sources, self._conditions, self._runs = [], [], []
        self._worker_thread = None
        self._movie = None
        self._raw_movie = None
        self._play_timer = QtCore.QTimer(self)
        self._play_timer.timeout.connect(self._advance_movie)
        self._build_ui()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.exp_id = QtWidgets.QLineEdit(); self.exp_id.editingFinished.connect(self._edited)
        self.folder = QtWidgets.QLineEdit(); self.folder.setReadOnly(True)
        load = QtWidgets.QPushButton("Load experiment"); load.clicked.connect(self.load_experiment)
        top.addWidget(QtWidgets.QLabel("EXP ID")); top.addWidget(self.exp_id, 1); top.addWidget(QtWidgets.QLabel("Processed folder")); top.addWidget(self.folder, 2); top.addWidget(load)
        outer.addLayout(top)
        self.tabs = QtWidgets.QTabWidget(); outer.addWidget(self.tabs, 1)
        analysis = QtWidgets.QWidget(); self.tabs.addTab(analysis, "Analysis")
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal); QtWidgets.QVBoxLayout(analysis).addWidget(split)
        left = QtWidgets.QWidget(); left_layout = QtWidgets.QVBoxLayout(left)
        self.sources = QtWidgets.QListWidget(); self.conditions = QtWidgets.QListWidget(); self.runs = QtWidgets.QListWidget()
        self.conditions.currentRowChanged.connect(self._condition_selected); self.runs.currentRowChanged.connect(self._run_selected)
        for label, widget in (("Recording sources", self.sources), ("Stimulus conditions", self.conditions), ("Cached runs", self.runs)):
            left_layout.addWidget(QtWidgets.QLabel(label)); left_layout.addWidget(widget, 1)
        split.addWidget(left)
        right = QtWidgets.QWidget(); form = QtWidgets.QFormLayout(right)
        self.info = QtWidgets.QPlainTextEdit(); self.info.setReadOnly(True); self.info.setMinimumHeight(140); form.addRow(self.info)
        self.period = self._number(5.0); self.duration = self._number(300.0); self.exclude = self._number(0.0)
        self.frequency = self._number(0.0); self.minimum = self._number(10.0); self.sigma = self._number(5.0); self.temporal = self._integer(5); self.detrend = self._number(30.0)
        self.circular = QtWidgets.QCheckBox("Circular temporal smoothing"); self.circular.setChecked(True)
        for label, widget in (("Stimulus period (s)", self.period), ("Stimulus duration (s)", self.duration), ("Exclude initial stimulus (s)", self.exclude), ("Analysis frequency (Hz; 0 = period)", self.frequency), ("Minimum video value after offset", self.minimum), ("Spatial Gaussian sigma (px)", self.sigma), ("Temporal smoothing (frames)", self.temporal), ("Detrend window (s; 0 = off)", self.detrend), ("", self.circular)):
            form.addRow(label, widget)
        self.run_button = QtWidgets.QPushButton("Run FFT analysis"); self.run_button.clicked.connect(self.run_analysis); form.addRow(self.run_button)
        self.progress = QtWidgets.QProgressBar(); self.status = QtWidgets.QLabel("Load an experiment to begin."); form.addRow(self.progress); form.addRow(self.status)
        split.addWidget(right); split.setSizes([380, 700])

        outputs = QtWidgets.QWidget(); self.tabs.addTab(outputs, "Outputs")
        output_layout = QtWidgets.QVBoxLayout(outputs)
        self.output_run = QtWidgets.QComboBox(); self.output_run.currentIndexChanged.connect(self._load_output)
        output_layout.addWidget(self.output_run)
        grid = QtWidgets.QGridLayout(); output_layout.addLayout(grid, 1)
        self.power = _ImageView("No amplitude map"); self.phase = _ImageView("No phase map"); self.mean = _ImageView("No mean frame"); self.movie_view = _ImageView("No cycle movie")
        for index, (title, view) in enumerate((("Periodic amplitude / F0", self.power), ("Preferred phase", self.phase), ("Mean cycle frame", self.mean), ("Cycle ΔF/F movie", self.movie_view))):
            box = QtWidgets.QGroupBox(title); layout = QtWidgets.QVBoxLayout(box); layout.addWidget(view, 1); grid.addWidget(box, index // 2, index % 2)
        controls = QtWidgets.QHBoxLayout()
        self.raw_movie = QtWidgets.QCheckBox("Show raw cycle"); self.raw_movie.toggled.connect(self._switch_movie)
        self.play_button = QtWidgets.QPushButton("Play"); self.play_button.setFixedWidth(72); self.play_button.clicked.connect(self._toggle_play)
        self.fps = self._integer(15); self.fps.setRange(1, 240)
        controls.addWidget(self.raw_movie); controls.addWidget(self.play_button); controls.addWidget(QtWidgets.QLabel("FPS")); controls.addWidget(self.fps); controls.addStretch()
        output_layout.addLayout(controls)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.slider.valueChanged.connect(self._show_movie_frame); output_layout.addWidget(self.slider)

    @staticmethod
    def _number(value):
        control = QtWidgets.QDoubleSpinBox(); control.setRange(-1e6, 1e6); control.setDecimals(4); control.setValue(value); return control
    @staticmethod
    def _integer(value):
        control = QtWidgets.QSpinBox(); control.setRange(1, 10000); control.setValue(value); return control

    def set_experiment(self, exp_id, processed_root):
        self.exp_id.setText(exp_id)
        if exp_id:
            self.folder.setText(str(Path(processed_root) / exp_id.rsplit("_", 1)[-1] / exp_id))

    def _edited(self):
        exp_id = self.exp_id.text().strip()
        if self._exp_id_setter:
            self._exp_id_setter(exp_id)
        self.set_experiment(exp_id, self._processed_root_getter())

    def _experiment_dir(self):
        folder = Path(self.folder.text())
        if not folder.is_dir():
            raise FileNotFoundError(f"Processed experiment folder not found: {folder}")
        return folder

    def load_experiment(self):
        try:
            exp_dir = self._experiment_dir(); self._sources, self._conditions = periodic.experiment_info(exp_dir)
        except Exception as error:
            QtWidgets.QMessageBox.critical(self, "Periodic retinotopy", str(error)); return
        self.sources.clear(); self.sources.addItems([periodic.source_label(exp_dir, source) for source in self._sources])
        self.conditions.clear(); self.conditions.addItems([self._condition_label(condition) for condition in self._conditions])
        if self.sources.count(): self.sources.setCurrentRow(0)
        if self.conditions.count(): self.conditions.setCurrentRow(0)
        self._refresh_runs()
        self.status.setText(f"Loaded {len(self._sources)} source(s) and {len(self._conditions)} condition(s).")

    @staticmethod
    def _condition_label(condition):
        return " | ".join(f"{key}={value}" for key, value in list(condition.items())[:4]) or "Unnamed condition"

    def _condition_selected(self, row):
        if not 0 <= row < len(self._conditions): return
        condition = self._conditions[row]
        for key in ("F1_speed", "speed"):
            try:
                speed = float(condition[key])
                if speed > 0:
                    self.period.setValue(1 / speed); self.exclude.setValue(1 / speed)
                break
            except (KeyError, TypeError, ValueError): pass
        self.info.setPlainText(json.dumps(condition, indent=2, default=str))

    def _refresh_runs(self):
        try: root = self._experiment_dir() / periodic.OUTPUT_DIRNAME
        except Exception: return
        self._runs = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name) if root.exists() else []
        for widget in (self.runs, self.output_run):
            widget.blockSignals(True); widget.clear()
            if isinstance(widget, QtWidgets.QListWidget): widget.addItems([path.name for path in self._runs])
            else: widget.addItems([path.name for path in self._runs])
            widget.blockSignals(False)
        if self._runs: self.runs.setCurrentRow(len(self._runs) - 1); self.output_run.setCurrentIndex(len(self._runs) - 1)

    def _run_selected(self, row):
        if 0 <= row < len(self._runs):
            config = self._runs[row] / "config.json"
            if config.exists(): self.info.setPlainText(config.read_text())

    def run_analysis(self):
        if self._worker_thread: return
        if self.sources.currentRow() < 0 or self.conditions.currentRow() < 0:
            QtWidgets.QMessageBox.warning(self, "Periodic retinotopy", "Select a recording source and stimulus condition."); return
        try:
            exp_dir = self._experiment_dir(); condition = self._conditions[self.conditions.currentRow()]
            onsets = periodic.condition_times(exp_dir, condition)
            config = {"experiment_dir": str(exp_dir), "source": self.sources.currentItem().text(), "onsets": onsets.tolist(), "period": self.period.value(), "duration": self.duration.value(), "exclude": self.exclude.value(), "frequency": self.frequency.value() or None, "minimum_video_value": self.minimum.value(), "spatial_sigma": self.sigma.value(), "temporal": self.temporal.value(), "detrend": self.detrend.value(), "circular": self.circular.isChecked(), "baseline_floor": 10.0}
        except Exception as error:
            QtWidgets.QMessageBox.warning(self, "Periodic retinotopy", str(error)); return
        self.run_button.setEnabled(False); self._worker_thread = QtCore.QThread(self); self._worker = _AnalysisWorker(config); self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run); self._worker.progress.connect(self._progress); self._worker.finished.connect(self._finished); self._worker.failed.connect(self._failed)
        self._worker.finished.connect(self._worker_thread.quit); self._worker.failed.connect(self._worker_thread.quit); self._worker_thread.finished.connect(self._clear_worker); self._worker_thread.start()

    def _progress(self, done, total, text):
        self.progress.setRange(0, max(1, total)); self.progress.setValue(done); self.status.setText(text)
    def _finished(self, output): self.status.setText(f"Saved: {output}"); self._refresh_runs()
    def _failed(self, message): self.status.setText("Analysis failed."); QtWidgets.QMessageBox.critical(self, "Periodic retinotopy failed", message)
    def _clear_worker(self): self._worker_thread.deleteLater(); self._worker_thread = None; self._worker = None; self.run_button.setEnabled(True)

    def _load_output(self, row):
        if not 0 <= row < len(self._runs): return
        run = self._runs[row]
        try:
            maps = np.load(run / "fft_maps.npz"); raw = np.load(run / "average_cycle_raw.npy", mmap_mode="r"); self._raw_movie = raw; self._movie = np.load(run / "average_cycle_dff.npy", mmap_mode="r")
            self.power.set_array(maps["power_over_f0"]); self.phase.set_array(maps["phase"], "phase", low=0, high=100); self.mean.set_array(np.asarray(raw).mean(axis=0))
            self.slider.blockSignals(True); self.slider.setRange(0, len(self._movie) - 1); self.slider.setValue(0); self.slider.blockSignals(False); self._show_movie_frame(0)
        except Exception as error:
            for view in (self.power, self.phase, self.mean, self.movie_view): view.clear_image("Incomplete periodic output")
            self.status.setText(f"Could not load output: {error}")

    def _show_movie_frame(self, index):
        movie = self._raw_movie if self.raw_movie.isChecked() else self._movie
        if movie is not None: self.movie_view.set_array(np.asarray(movie[index]))

    def _switch_movie(self, _checked):
        self._show_movie_frame(self.slider.value())

    def _toggle_play(self):
        if self._play_timer.isActive():
            self._play_timer.stop(); self.play_button.setText("Play")
        elif self._movie is not None:
            self._play_timer.start(max(1, round(1000 / self.fps.value())))
            self.play_button.setText("Pause")

    def _advance_movie(self):
        if self._movie is None: return
        self.slider.setValue((self.slider.value() + 1) % len(self._movie))
