"""Interactive Retinotopy tab used by the local pipeline runner."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from preprocess_pipeline import retinotopy


class _PreparationWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int, str)
    finished = QtCore.pyqtSignal(list)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, exp_dir: Path, pre: float, post: float, blink_pre: float, blink_post: float, meso_window: bool):
        super().__init__()
        self.exp_dir, self.pre, self.post = exp_dir, pre, post
        self.blink_pre, self.blink_post = blink_pre, blink_post
        self.meso_window = meso_window

    @QtCore.pyqtSlot()
    def run(self):
        try:
            result = retinotopy.prepare_experiment(
                self.exp_dir, self.pre, self.post, self.blink_pre, self.blink_post,
                lambda done, total, text: self.progress.emit(int(done * 1000), int(total * 1000), text),
                meso_window=self.meso_window,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit([str(path) for path in result])


class MontageCanvas(QtWidgets.QWidget):
    position_changed = QtCore.pyqtSignal(int, int)
    probe_frozen_changed = QtCore.pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(420, 360)
        self.setMouseTracking(True)
        self.image: np.ndarray | None = None
        self.vmin, self.vmax = 0.0, 1.0
        self.tool_enabled = False
        self.probe_frozen = False
        self.tool_size = 50
        self.tool_position = (0, 0)
        self._rect = QtCore.QRectF()

    def set_image(self, image: np.ndarray | None, vmin: float, vmax: float):
        self.image = image
        self.vmin, self.vmax = float(vmin), max(float(vmax), float(vmin) + 1e-8)
        self.update()

    def _image_rect(self) -> QtCore.QRectF:
        if self.image is None:
            return QtCore.QRectF()
        h, w = self.image.shape
        scale = min(self.width() / w, self.height() / h)
        return QtCore.QRectF((self.width() - w * scale) / 2, (self.height() - h * scale) / 2, w * scale, h * scale)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("black"))
        if self.image is None:
            painter.setPen(QtGui.QColor("white"))
            painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "Prepare or load a retinotopy montage")
            return
        self._rect = self._image_rect()
        normalised = np.clip((self.image - self.vmin) / (self.vmax - self.vmin), 0, 1)
        image8 = np.ascontiguousarray((normalised * 255).astype(np.uint8))
        qimage = QtGui.QImage(image8.data, image8.shape[1], image8.shape[0], image8.strides[0], QtGui.QImage.Format.Format_Grayscale8)
        painter.drawImage(self._rect, qimage)
        if self.tool_enabled:
            h, w = self.image.shape
            x, y = self.tool_position
            half = self.tool_size / 2
            sx, sy = self._rect.width() / w, self._rect.height() / h
            rect = QtCore.QRectF(self._rect.left() + (x - half) * sx, self._rect.top() + (y - half) * sy, self.tool_size * sx, self.tool_size * sy)
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffd23f") if self.probe_frozen else QtGui.QColor("#00ff66"), 2))
            painter.drawRect(rect)

    def mouseMoveEvent(self, event):
        if self.probe_frozen or not self.tool_enabled or self.image is None or not self._rect.contains(event.position()):
            return
        h, w = self.image.shape
        x = int((event.position().x() - self._rect.left()) / self._rect.width() * w)
        y = int((event.position().y() - self._rect.top()) / self._rect.height() * h)
        self.tool_position = (int(np.clip(x, 0, w - 1)), int(np.clip(y, 0, h - 1)))
        self.position_changed.emit(*self.tool_position)
        self.update()

    def mouseDoubleClickEvent(self, event):
        if self.tool_enabled and self.image is not None and self._rect.contains(event.position()):
            self.probe_frozen = not self.probe_frozen
            self.probe_frozen_changed.emit(self.probe_frozen)
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class TraceGrid(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(420, 360)
        self.traces: np.ndarray | None = None  # y, x, time
        self.times: np.ndarray | None = None
        self.ymin, self.ymax = -0.1, 0.5
        self.x_positions: list[float] = []
        self.y_positions: list[float] = []

    def set_data(self, traces, times, ymin, ymax, x_positions, y_positions):
        self.traces, self.times = traces, times
        self.ymin, self.ymax = float(ymin), max(float(ymax), float(ymin) + 1e-6)
        self.x_positions, self.y_positions = list(x_positions), list(y_positions)
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#181818"))
        if self.traces is None or self.times is None:
            painter.setPen(QtGui.QColor("white")); painter.drawText(self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter, "Enable the sampling tool to view ΔF/F traces")
            return
        ny, nx, _ = self.traces.shape
        left_margin, top_margin, right_margin, bottom_margin = 52, 26, 8, 8
        cell_w = (self.width() - left_margin - right_margin) / nx
        cell_h = (self.height() - top_margin - bottom_margin) / ny
        t0, t1 = self.times[0], max(self.times[-1], self.times[0] + 1e-6)
        painter.setPen(QtGui.QColor("#cccccc"))
        small_font = painter.font(); small_font.setPointSize(max(7, small_font.pointSize() - 2)); painter.setFont(small_font)
        for xi in range(nx):
            text = f"X={self.x_positions[xi]:g}" if xi < len(self.x_positions) else f"X {xi + 1}"
            painter.drawText(QtCore.QRectF(left_margin + xi * cell_w, 2, cell_w, top_margin - 3), QtCore.Qt.AlignmentFlag.AlignCenter, text)
        for yi in range(ny):
            text = f"Y={self.y_positions[yi]:g}" if yi < len(self.y_positions) else f"Y {yi + 1}"
            painter.drawText(QtCore.QRectF(1, top_margin + yi * cell_h, left_margin - 4, cell_h), QtCore.Qt.AlignmentFlag.AlignVCenter | QtCore.Qt.AlignmentFlag.AlignRight, text)
        for yi in range(ny):
            for xi in range(nx):
                rect = QtCore.QRectF(left_margin + xi * cell_w, top_margin + yi * cell_h, cell_w, cell_h)
                painter.setPen(QtGui.QPen(QtGui.QColor("#555555"), 1)); painter.drawRect(rect)
                zero_y = rect.bottom() - (0 - self.ymin) / (self.ymax - self.ymin) * rect.height()
                if rect.top() <= zero_y <= rect.bottom():
                    painter.setPen(QtGui.QPen(QtGui.QColor("#555555"), 1, QtCore.Qt.PenStyle.DashLine)); painter.drawLine(QtCore.QPointF(rect.left(), zero_y), QtCore.QPointF(rect.right(), zero_y))
                trace = self.traces[yi, xi]
                points = []
                for time, value in zip(self.times, trace):
                    px = rect.left() + (time - t0) / (t1 - t0) * rect.width()
                    py = rect.bottom() - (value - self.ymin) / (self.ymax - self.ymin) * rect.height()
                    points.append(QtCore.QPointF(px, py))
                painter.setPen(QtGui.QPen(QtGui.QColor("#55b9ff"), 1.3)); painter.drawPolyline(QtGui.QPolygonF(points))


class RetinotopyTab(QtWidgets.QWidget):
    """Preparation controls, movie player, and non-blocking spatial probe."""
    def __init__(self, exp_id_getter, processed_root_getter, exp_id_setter=None, parent=None):
        super().__init__(parent)
        self._exp_id_getter, self._processed_root_getter = exp_id_getter, processed_root_getter
        self._exp_id_setter = exp_id_setter
        self.movie: np.ndarray | None = None
        self._movie_uses_pixel_encoding = False
        self.pixel_average: np.ndarray | None = None
        self.dff: np.ndarray | None = None
        self.times: np.ndarray | None = None
        self.metadata = {}
        self._pending_position: tuple[int, int] | None = None
        self._update_timer = QtCore.QTimer(self); self._update_timer.setSingleShot(True); self._update_timer.timeout.connect(self._update_traces)
        self._play_timer = QtCore.QTimer(self); self._play_timer.timeout.connect(self._advance_frame)
        self._worker_thread = None
        self._build_ui()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        controls = QtWidgets.QGroupBox("Retinotopy")
        controls.setMaximumWidth(330)
        controls.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Expanding)
        grid = QtWidgets.QGridLayout(controls)
        self.test_path = QtWidgets.QLineEdit()
        self.exp_id_display = QtWidgets.QLineEdit(); self.exp_id_display.editingFinished.connect(self._exp_id_edited)
        load_existing = QtWidgets.QPushButton("Load"); load_existing.clicked.connect(self._load_from_folder)
        browse = QtWidgets.QPushButton("Browse"); browse.clicked.connect(self._browse_test_path)
        self.pre = self._seconds_spin(2.0); self.post = self._seconds_spin(5.0)
        self.blink_pre = self._seconds_spin(0.5); self.blink_post = self._seconds_spin(1.0)
        self.meso_window = QtWidgets.QCheckBox("Meso"); self.meso_window.setChecked(True)
        self.prepare_button = QtWidgets.QPushButton("Process"); self.prepare_button.clicked.connect(self.prepare)
        self.status = QtWidgets.QLabel("No montage loaded.")
        self.source_combo = QtWidgets.QComboBox(); self.source_combo.currentIndexChanged.connect(self.load_selected_source)
        self.movie_combo = QtWidgets.QComboBox(); self.movie_combo.addItems(["Pixel average video", "Blink map", "ΔF/F video"]); self.movie_combo.currentIndexChanged.connect(self._display_movie)
        self.play_button = QtWidgets.QPushButton("Play"); self.play_button.setFixedWidth(70); self.play_button.clicked.connect(self._toggle_play)
        self.fps = QtWidgets.QSpinBox(); self.fps.setRange(1, 120); self.fps.setValue(15); self.fps.valueChanged.connect(self._set_play_interval)
        self.frame_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); self.frame_slider.valueChanged.connect(self._display_frame)
        self.time_label = QtWidgets.QLabel("t = —")
        self.time_label.setMinimumWidth(82)
        self.minimum = QtWidgets.QDoubleSpinBox(); self.maximum = QtWidgets.QDoubleSpinBox()
        for spinner in (self.minimum, self.maximum): spinner.setRange(-1e8, 1e8); spinner.setDecimals(4); spinner.valueChanged.connect(self._redraw)
        grid.addWidget(QtWidgets.QLabel("EXP ID"), 0, 0); grid.addWidget(self.exp_id_display, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Folder"), 1, 0); grid.addWidget(self.test_path, 1, 1)
        grid.addWidget(browse, 2, 1)
        grid.addWidget(load_existing, 3, 1)
        process_row = QtWidgets.QHBoxLayout(); process_row.addWidget(self.prepare_button); process_row.addWidget(self.meso_window)
        grid.addLayout(process_row, 4, 1)
        pre_post = QtWidgets.QHBoxLayout(); pre_post.addWidget(QtWidgets.QLabel("Pre")); pre_post.addWidget(self.pre); pre_post.addWidget(QtWidgets.QLabel("Post")); pre_post.addWidget(self.post)
        grid.addLayout(pre_post, 5, 1)
        blink = QtWidgets.QHBoxLayout(); blink.addWidget(QtWidgets.QLabel("Blink pre")); blink.addWidget(self.blink_pre); blink.addWidget(QtWidgets.QLabel("post")); blink.addWidget(self.blink_post)
        grid.addLayout(blink, 6, 1)
        grid.addWidget(QtWidgets.QLabel("Source"), 7, 0); grid.addWidget(self.source_combo, 7, 1)
        grid.addWidget(QtWidgets.QLabel("Show"), 8, 0); grid.addWidget(self.movie_combo, 8, 1)
        playback = QtWidgets.QHBoxLayout(); playback.addWidget(self.play_button); playback.addWidget(QtWidgets.QLabel("FPS")); playback.addWidget(self.fps); playback.addWidget(self.time_label); playback.addStretch()
        grid.addLayout(playback, 9, 0, 1, 2)
        grid.addWidget(self.frame_slider, 10, 0, 1, 2)
        contrast = QtWidgets.QHBoxLayout(); contrast.addWidget(QtWidgets.QLabel("Contrast min")); contrast.addWidget(self.minimum); contrast.addWidget(QtWidgets.QLabel("max")); contrast.addWidget(self.maximum)
        grid.addLayout(contrast, 11, 0, 1, 2)
        self.status.setWordWrap(True); grid.addWidget(self.status, 12, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        self.movie_canvas = MontageCanvas()
        self.movie_canvas.setMinimumHeight(450)
        self.movie_canvas.setToolTip("Retinotopy montage movie")
        video_panel = QtWidgets.QWidget(); video_layout = QtWidgets.QVBoxLayout(video_panel); video_layout.addWidget(self.movie_canvas, 1)
        video_panel.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        top.addWidget(controls); top.addWidget(video_panel); top.setSizes([290, 1010]); top.setStretchFactor(0, 0); top.setStretchFactor(1, 1); outer.addWidget(top, 2)
        lower = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        left = QtWidgets.QWidget(); left_layout = QtWidgets.QVBoxLayout(left); self.canvas = MontageCanvas(); self.canvas.position_changed.connect(self._queue_trace_update); self.canvas.probe_frozen_changed.connect(self._set_probe_frozen)
        self.tool_toggle = QtWidgets.QPushButton("Enable sampling tool"); self.tool_toggle.setCheckable(True); self.tool_toggle.toggled.connect(self._set_tool_enabled)
        self.tool_size = QtWidgets.QSpinBox(); self.tool_size.setRange(1, 1000); self.tool_size.setValue(50); self.tool_size.valueChanged.connect(self._set_tool_size)
        probe_controls = QtWidgets.QHBoxLayout(); probe_controls.addWidget(self.tool_toggle); probe_controls.addWidget(QtWidgets.QLabel("Square size (px)")); probe_controls.addWidget(self.tool_size); probe_controls.addStretch()
        left_layout.addLayout(probe_controls); left_layout.addWidget(self.canvas, 1)
        right = QtWidgets.QWidget(); right_layout = QtWidgets.QVBoxLayout(right); self.trace_grid = TraceGrid()
        self.trace_min = QtWidgets.QDoubleSpinBox(); self.trace_max = QtWidgets.QDoubleSpinBox()
        for control, value in ((self.trace_min, -0.1), (self.trace_max, 0.5)):
            control.setRange(-1000, 1000); control.setDecimals(3); control.setValue(value); control.valueChanged.connect(self._update_traces)
        trace_controls = QtWidgets.QHBoxLayout(); trace_controls.addWidget(QtWidgets.QLabel("ΔF/F y min")); trace_controls.addWidget(self.trace_min); trace_controls.addWidget(QtWidgets.QLabel("max")); trace_controls.addWidget(self.trace_max); trace_controls.addStretch()
        right_layout.addLayout(trace_controls); right_layout.addWidget(self.trace_grid, 1)
        lower.addWidget(left); lower.addWidget(right); lower.setSizes([650, 650]); lower.setStretchFactor(0, 1); lower.setStretchFactor(1, 1); outer.addWidget(lower, 1)

    @staticmethod
    def _seconds_spin(value):
        control = QtWidgets.QDoubleSpinBox(); control.setRange(0, 120); control.setDecimals(2); control.setSingleStep(0.25); control.setValue(value); return control

    def _browse_test_path(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Select processed experiment folder", self.test_path.text())
        if directory: self.test_path.setText(directory)

    def set_experiment(self, exp_id: str, processed_root: str):
        """Synchronise Tab 1's experiment selection into this tab."""
        if self.exp_id_display.text() != exp_id:
            self.exp_id_display.setText(exp_id)
        if not exp_id:
            return
        animal = exp_id.rsplit("_", 1)[-1]
        self.test_path.setText(str(Path(processed_root) / animal / exp_id))

    def _exp_id_edited(self):
        exp_id = self.exp_id_display.text().strip()
        if self._exp_id_setter:
            self._exp_id_setter(exp_id)
        self.set_experiment(exp_id, self._processed_root_getter())

    def _load_from_folder(self):
        if not self.load_existing():
            QtWidgets.QMessageBox.information(
                self,
                "No retinotopy outputs",
                "No saved retinotopy montages were found. Use ‘Produce retinotopy montages’ first.",
            )

    def _experiment_dir(self):
        path = self.test_path.text().strip()
        if path:
            return retinotopy.find_experiment(self._processed_root_getter(), self.exp_id_display.text().strip(), path)
        return retinotopy.find_experiment(self._processed_root_getter(), self.exp_id_display.text().strip())

    def prepare(self):
        if self._worker_thread:
            return
        try: exp_dir = self._experiment_dir()
        except Exception as exc: QtWidgets.QMessageBox.warning(self, "Retinotopy", str(exc)); return
        self.prepare_button.setEnabled(False); self.status.setText("Preparing montages in the background…")
        self._worker_thread = QtCore.QThread(self)
        self._worker = _PreparationWorker(exp_dir, self.pre.value(), self.post.value(), self.blink_pre.value(), self.blink_post.value(), self.meso_window.isChecked())
        self._worker.moveToThread(self._worker_thread); self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda done, total, text: self.status.setText(f"Preparing: {text} ({done / max(total, 1):.0%})"))
        self._worker.finished.connect(self._prepared); self._worker.failed.connect(self._failed)
        self._worker.finished.connect(self._worker_thread.quit); self._worker.failed.connect(self._worker_thread.quit); self._worker_thread.finished.connect(self._clear_worker)
        self._worker_thread.start()

    def _clear_worker(self):
        if self._worker_thread: self._worker_thread.deleteLater()
        self._worker_thread = None; self._worker = None; self.prepare_button.setEnabled(True)

    def _failed(self, message):
        self.status.setText("Preparation failed."); QtWidgets.QMessageBox.critical(self, "Retinotopy preparation failed", message)

    def _prepared(self, paths):
        self.status.setText(f"Prepared {len(paths)} plane/channel montage(s).")
        self.source_combo.blockSignals(True); self.source_combo.clear()
        for path in paths: self.source_combo.addItem(self._source_display_name(Path(path)), path)
        self.source_combo.blockSignals(False)
        if paths: self.source_combo.setCurrentIndex(0); self.load_selected_source()

    def load_existing(self):
        try: root = self._experiment_dir() / retinotopy.OUTPUT_DIRNAME
        except Exception as exc:
            self.status.setText(f"Could not resolve experiment folder: {exc}")
            return False
        paths = sorted(
            (path for path in root.glob("*plane*_channel*") if (path / "metadata.json").exists()),
            key=lambda path: (not "Meso" in path.name, path.name),
        )
        if paths:
            self.source_combo.blockSignals(True); self.source_combo.clear()
            for path in paths: self.source_combo.addItem(self._source_display_name(path), str(path))
            self.source_combo.blockSignals(False); self.source_combo.setCurrentIndex(0); self.load_selected_source()
            return True
        self.status.setText("No saved retinotopy montages found in this experiment.")
        return False

    @staticmethod
    def _source_display_name(path: Path) -> str:
        try:
            metadata = json.loads((path / "metadata.json").read_text())
        except Exception:
            return path.name
        return "Meso" if metadata.get("roi") == "Meso" else path.name

    def load_selected_source(self):
        path_text = self.source_combo.currentData()
        if not path_text: return
        path = Path(path_text)
        try:
            self.dff = np.load(path / "dff_video.npy", mmap_mode="r")
            self.pixel_average = np.load(path / "pixel_average_video.npy", mmap_mode="r")
            self.times = np.load(path / "time_seconds.npy")
            self.metadata = json.loads((path / "metadata.json").read_text())
        except Exception as exc: QtWidgets.QMessageBox.warning(self, "Retinotopy", f"Could not load output: {exc}"); return
        self._display_movie()

    def _display_movie(self):
        path_text = self.source_combo.currentData()
        if not path_text: return
        names = ["pixel_average_video.npy", "blink_map.npy", "dff_video.npy"]
        self.status.setText(f"Loading {self.movie_combo.currentText()}…")
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        try:
            self.movie = np.load(Path(path_text) / names[self.movie_combo.currentIndex()], mmap_mode="r")
        except Exception as exc:
            self.status.setText("Could not load selected video.")
            QtWidgets.QMessageBox.warning(self, "Retinotopy", f"Could not load video: {exc}")
            return
        self._movie_uses_pixel_encoding = self.movie_combo.currentIndex() in (0, 1)
        self.frame_slider.blockSignals(True); self.frame_slider.setRange(0, len(self.movie) - 1); self.frame_slider.setValue(0); self.frame_slider.blockSignals(False)
        values = self._contrast_sample(self.movie, self._movie_uses_pixel_encoding)
        self.minimum.blockSignals(True); self.maximum.blockSignals(True)
        self.minimum.setValue(float(np.nanpercentile(values, 1))); self.maximum.setValue(float(np.nanpercentile(values, 99)))
        self.minimum.blockSignals(False); self.maximum.blockSignals(False)
        self._display_frame(0)
        self._set_average_image()
        self.status.setText(f"Loaded {self.movie_combo.currentText()}.")

    def _contrast_sample(self, movie: np.ndarray, decode_pixel_values: bool = False, max_frames: int = 20) -> np.ndarray:
        """Use representative frames so a selection change does not materialise a whole video."""
        indices = np.linspace(0, len(movie) - 1, min(len(movie), max_frames), dtype=int)
        frames = [np.asarray(movie[index]) for index in indices]
        if decode_pixel_values:
            frames = [retinotopy._decode_pixel_video(frame, self.metadata) for frame in frames]
        return np.stack(frames)

    def _display_frame(self, index):
        if self.movie is None: return
        frame = np.asarray(self.movie[index])
        if self._movie_uses_pixel_encoding:
            frame = retinotopy._decode_pixel_video(frame, self.metadata)
        self.movie_canvas.set_image(frame, self.minimum.value(), self.maximum.value())
        if self.times is not None and self.movie_combo.currentIndex() != 1 and index < len(self.times):
            self.time_label.setText(f"t = {self.times[index]:+.2f} s")
        else:
            self.time_label.setText(f"frame {index + 1}/{len(self.movie)}")

    def _redraw(self): self._display_frame(self.frame_slider.value())
    def _toggle_play(self):
        if self._play_timer.isActive(): self._play_timer.stop(); self.play_button.setText("Play")
        elif self.movie is not None: self._set_play_interval(); self._play_timer.start(); self.play_button.setText("Pause")
    def _set_play_interval(self): self._play_timer.setInterval(max(1, round(1000 / self.fps.value())))
    def _advance_frame(self):
        if self.movie is None: return
        next_frame = (self.frame_slider.value() + 1) % len(self.movie); self.frame_slider.setValue(next_frame)

    def _set_average_image(self):
        if self.pixel_average is None or not self.metadata: return
        # A FOV-sized image: mean corresponding pixels across position tiles.
        ly, lx = self.metadata["tile_height"], self.metadata["tile_width"]
        ny, nx = len(self.metadata["y_positions"]), len(self.metadata["x_positions"])
        # This deliberately always uses raw pixel averages, not the selected
        # display map.  The sampling square therefore stays spatially legible
        # when the top viewer is switched to ΔF/F or blink.
        sampled = self._contrast_sample(self.pixel_average, True)
        image = sampled.mean(axis=0).reshape(ny, ly, nx, lx).mean(axis=(0, 2))
        self.canvas.tool_position = (lx // 2, ly // 2)
        self._average_image = image
        self.canvas.set_image(image, float(np.nanpercentile(image, 1)), float(np.nanpercentile(image, 99)))

    def _set_tool_enabled(self, enabled):
        self.canvas.tool_enabled = enabled
        self.canvas.probe_frozen = False
        if enabled and hasattr(self, "_average_image"):
            self.canvas.set_image(self._average_image, float(np.nanpercentile(self._average_image, 1)), float(np.nanpercentile(self._average_image, 99)))
            self._queue_trace_update(*self.canvas.tool_position)
        self.tool_toggle.setText("Disable sampling tool" if enabled else "Enable sampling tool")

    def _set_probe_frozen(self, frozen):
        if frozen:
            self.status.setText("Sampling square frozen. Double-click it to resume mouse tracking.")
        else:
            self.status.setText("Sampling square follows the mouse.")
    def _set_tool_size(self, size): self.canvas.tool_size = size; self.canvas.update(); self._queue_trace_update(*self.canvas.tool_position)
    def _queue_trace_update(self, x, y):
        if not self.canvas.tool_enabled or self.dff is None: return
        self._pending_position = (x, y)
        if not self._update_timer.isActive(): self._update_timer.start(60)  # coalesce mouse events

    def _update_traces(self):
        if self._pending_position is None or self.dff is None or self.times is None or not self.metadata: return
        x, y = self._pending_position; ly, lx = self.metadata["tile_height"], self.metadata["tile_width"]
        ny, nx = len(self.metadata["y_positions"]), len(self.metadata["x_positions"])
        half = self.tool_size.value() // 2; y0, y1 = max(0, y-half), min(ly, y+half); x0, x1 = max(0, x-half), min(lx, x+half)
        traces = np.empty((ny, nx, self.dff.shape[0]), dtype=np.float32)
        for yi in range(ny):
            for xi in range(nx): traces[yi, xi] = np.asarray(self.dff[:, yi*ly+y0:yi*ly+y1, xi*lx+x0:xi*lx+x1]).mean(axis=(1, 2))
        self.trace_grid.set_data(
            traces, self.times, self.trace_min.value(), self.trace_max.value(),
            self.metadata["x_positions"], self.metadata["y_positions"],
        )
