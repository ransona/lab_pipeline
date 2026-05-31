import math
import os
import sys
from typing import Optional

import numpy as np
from PIL import Image, ImageSequence
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

try:
    from scipy.ndimage import gaussian_filter as _scipy_gaussian_filter
    _SCIPY_AVAILABLE = True
except Exception:
    _SCIPY_AVAILABLE = False


def _moving_average_stack_trailing(stack: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or stack.shape[0] <= 1:
        return stack
    tcount = stack.shape[0]
    csum = np.cumsum(stack, axis=0, dtype=np.float64)
    out = np.empty_like(stack, dtype=np.float64)
    for i in range(tcount):
        j0 = max(0, i - window + 1)
        if j0 == 0:
            segment_sum = csum[i]
        else:
            segment_sum = csum[i] - csum[j0 - 1]
        n = i - j0 + 1
        out[i] = segment_sum / float(n)
    return out


def _gaussian_kernel1d(sigma: float, radius: Optional[int] = None) -> np.ndarray:
    if sigma <= 0:
        return np.array([1.0], dtype=np.float64)
    if radius is None:
        radius = max(1, int(math.ceil(3.0 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    k = np.exp(-(x * x) / (2.0 * sigma * sigma))
    k /= k.sum()
    return k


def _convolve1d_reflect(a: np.ndarray, k: np.ndarray, axis: int) -> np.ndarray:
    if k.size == 1:
        return a
    radius = (k.size - 1) // 2
    pad_width = [(0, 0)] * a.ndim
    pad_width[axis] = (radius, radius)
    ap = np.pad(a, pad_width, mode="reflect")
    ap = np.moveaxis(ap, axis, 0)
    flat_ap = ap.reshape((ap.shape[0], -1))
    str0, str1 = flat_ap.strides
    n_out = flat_ap.shape[0] - 2 * radius
    win_shape = (n_out, k.size, flat_ap.shape[1])
    win_strides = (str0, str0, str1)
    windows = np.lib.stride_tricks.as_strided(flat_ap, shape=win_shape, strides=win_strides)
    flat_out = np.tensordot(windows, k, axes=([1], [0]))
    out = flat_out.reshape((n_out,) + ap.shape[1:])
    return np.moveaxis(out, 0, axis)


def _gaussian_blur_stack_np(stack: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return stack
    k = _gaussian_kernel1d(sigma)
    out = _convolve1d_reflect(stack, k, axis=1)
    out = _convolve1d_reflect(out, k, axis=2)
    return out


class TiffViewerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.tiff_images = []
        self.current_frame = 0
        self.fps = 10
        self.min_clip = -65536
        self.max_clip = 65536
        self.average_frame = None
        self.loaded_path = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance_frame)
        self._build_ui()
        self._wire_events()
        self.setMinimumSize(1150, 780)

    def _build_ui(self):
        root = QGridLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.left_label = QLabel()
        self.left_label.setObjectName("leftView")
        self.left_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.left_label.setStyleSheet("QLabel#leftView { background: black; }")

        self.right_label = QLabel()
        self.right_label.setObjectName("rightView")
        self.right_label.setStyleSheet("QLabel#rightView { background: black; }")
        self.right_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        root.addWidget(self.left_label, 0, 0)
        root.addWidget(self.right_label, 0, 1)

        top = QHBoxLayout()
        self.btn_open = QPushButton("Open TIFF")
        self.btn_play = QPushButton("Play")
        self.btn_stop = QPushButton("Stop")
        self.btn_play.setEnabled(False)
        self.btn_stop.setEnabled(False)
        top.addWidget(self.btn_open)
        top.addWidget(self.btn_play)
        top.addWidget(self.btn_stop)
        top.addSpacing(16)
        top.addWidget(QLabel("FPS:"))
        self.sld_fps = QSlider(Qt.Orientation.Horizontal)
        self.sld_fps.setRange(1, 60)
        self.sld_fps.setValue(self.fps)
        self.lbl_fps_val = QLabel(str(self.fps))
        top.addWidget(self.sld_fps, stretch=1)
        top.addWidget(self.lbl_fps_val)
        top.addSpacing(16)
        self.chk_preview = QCheckBox("Preview (first 1000 frames)")
        self.chk_preview.setChecked(True)
        top.addWidget(self.chk_preview)
        top.addSpacing(16)
        top.addWidget(QLabel("Start:"))
        self.spin_start = QSpinBox()
        self.spin_start.setRange(0, 2_000_000_000)
        self.spin_start.setValue(0)
        top.addWidget(self.spin_start)
        top.addSpacing(12)
        top.addWidget(QLabel("Span:"))
        self.spin_span = QSpinBox()
        self.spin_span.setRange(1, 2_000_000_000)
        self.spin_span.setValue(1)
        top.addWidget(self.spin_span)
        row1 = QWidget()
        row1.setLayout(top)
        root.addWidget(row1, 1, 0, 1, 2)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Clip % Low:"))
        self.spin_clip_lo = QDoubleSpinBox()
        self.spin_clip_lo.setRange(0.0, 100.0)
        self.spin_clip_lo.setDecimals(1)
        self.spin_clip_lo.setSingleStep(0.5)
        self.spin_clip_lo.setValue(5.0)
        opts.addWidget(self.spin_clip_lo)
        opts.addSpacing(8)
        opts.addWidget(QLabel("High:"))
        self.spin_clip_hi = QDoubleSpinBox()
        self.spin_clip_hi.setRange(0.0, 100.0)
        self.spin_clip_hi.setDecimals(1)
        self.spin_clip_hi.setSingleStep(0.5)
        self.spin_clip_hi.setValue(95.0)
        opts.addWidget(self.spin_clip_hi)
        self.btn_apply_clip = QPushButton("Apply Clip %")
        opts.addWidget(self.btn_apply_clip)
        opts.addSpacing(20)
        opts.addWidget(QLabel("Temporal avg window:"))
        self.spin_tavg = QSpinBox()
        self.spin_tavg.setRange(1, 1_000_000)
        self.spin_tavg.setValue(1)
        opts.addWidget(self.spin_tavg)
        self.btn_apply_tavg = QPushButton("Apply Temporal Avg")
        opts.addWidget(self.btn_apply_tavg)
        opts.addSpacing(20)
        opts.addWidget(QLabel("Gaussian sigma:"))
        self.spin_sigma = QDoubleSpinBox()
        self.spin_sigma.setRange(0.0, 1000.0)
        self.spin_sigma.setDecimals(2)
        self.spin_sigma.setSingleStep(0.1)
        self.spin_sigma.setValue(0.0)
        opts.addWidget(self.spin_sigma)
        self.btn_apply_gauss = QPushButton("Apply Gaussian")
        opts.addWidget(self.btn_apply_gauss)
        row2 = QWidget()
        row2.setLayout(opts)
        root.addWidget(row2, 2, 0, 1, 2)

        self.sld_frame = QSlider(Qt.Orientation.Horizontal)
        self.sld_frame.setRange(0, 0)
        self.sld_frame.setEnabled(False)
        root.addWidget(self.sld_frame, 3, 0, 1, 2)

        clip_layout = QHBoxLayout()
        clip_layout.addWidget(QLabel("Min Clip:"))
        self.sld_min = QSlider(Qt.Orientation.Horizontal)
        self.sld_min.setRange(-65536, 65536)
        self.sld_min.setValue(self.min_clip)
        self.lbl_min_val = QLabel(str(self.min_clip))
        clip_layout.addWidget(self.sld_min, stretch=1)
        clip_layout.addWidget(self.lbl_min_val)
        clip_layout.addSpacing(12)
        clip_layout.addWidget(QLabel("Max Clip:"))
        self.sld_max = QSlider(Qt.Orientation.Horizontal)
        self.sld_max.setRange(-65536, 65536)
        self.sld_max.setValue(self.max_clip)
        self.lbl_max_val = QLabel(str(self.max_clip))
        clip_layout.addWidget(self.sld_max, stretch=1)
        clip_layout.addWidget(self.lbl_max_val)
        clip_row = QWidget()
        clip_row.setLayout(clip_layout)
        root.addWidget(clip_row, 4, 0, 1, 2)

        status_layout = QHBoxLayout()
        self.lbl_status = QLabel("No file loaded.")
        status_layout.addWidget(self.lbl_status)
        status_row = QWidget()
        status_row.setLayout(status_layout)
        root.addWidget(status_row, 5, 0, 1, 2)
        root.setRowStretch(0, 1)
        root.setColumnStretch(0, 1)
        root.setColumnStretch(1, 1)

    def _wire_events(self):
        self.btn_open.clicked.connect(self._open_tiff)
        self.btn_play.clicked.connect(self.play_movie)
        self.btn_stop.clicked.connect(self.stop_movie)
        self.sld_fps.valueChanged.connect(self._on_fps_changed)
        self.sld_frame.valueChanged.connect(self._on_scroll_frame)
        self.sld_min.valueChanged.connect(self._on_min_clip_changed)
        self.sld_max.valueChanged.connect(self._on_max_clip_changed)
        self.btn_apply_clip.clicked.connect(self._apply_clip_percentiles_to_data)
        self.btn_apply_tavg.clicked.connect(self._apply_temporal_avg_to_data)
        self.btn_apply_gauss.clicked.connect(self._apply_gaussian_to_data)

    def _open_tiff(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open TIFF", "", "TIFF Files (*.tif *.tiff)")
        if not path:
            return
        self.loaded_path = path
        self._load_tiff(path)

    def _load_tiff(self, path: str):
        preview = self.chk_preview.isChecked()
        span = max(1, int(self.spin_span.value()))
        start = max(0, int(self.spin_start.value()))
        clip_lo = float(self.spin_clip_lo.value())
        clip_hi = float(self.spin_clip_hi.value())
        if clip_lo > clip_hi:
            clip_lo, clip_hi = clip_hi, clip_lo
        try:
            img = Image.open(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{e}")
            return
        try:
            total_frames = getattr(img, "n_frames", None)
            if total_frames is None:
                total_frames = sum(1 for _ in ImageSequence.Iterator(img))
        except Exception:
            total_frames = 1
        effective_total = min(1000, total_frames) if preview else total_frames
        if effective_total <= 0:
            QMessageBox.warning(self, "Warning", "No frames available.")
            return
        if start >= effective_total:
            start = max(0, effective_total - 1)
            self.spin_start.blockSignals(True)
            self.spin_start.setValue(start)
            self.spin_start.blockSignals(False)
        indices = list(range(start, effective_total, span)) or [start]
        progress = QProgressDialog("Loading TIFF file...", "Cancel", 0, len(indices), self)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        frames = []
        cancelled = False
        try:
            for i, frame_idx in enumerate(indices):
                if progress.wasCanceled():
                    cancelled = True
                    break
                try:
                    img.seek(frame_idx)
                    arr = np.array(img, dtype=np.float32)
                    frames.append(arr)
                except Exception as fe:
                    print(f"Warning: could not read frame {frame_idx}: {fe}")
                progress.setValue(i + 1)
                QApplication.processEvents()
        finally:
            progress.reset()
        if cancelled or len(frames) == 0:
            self.tiff_images = []
            self.average_frame = None
            self.sld_frame.setEnabled(False)
            self.btn_play.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self._clear_views()
            self.lbl_status.setText("Loading canceled or no readable frames.")
            return
        stack = np.stack(frames, axis=0)
        self.tiff_images = [stack[i] for i in range(stack.shape[0])]
        self.average_frame = np.mean(stack, axis=0)
        try:
            self.min_clip = int(np.percentile(stack, clip_lo))
            self.max_clip = int(np.percentile(stack, clip_hi))
        except Exception:
            self.min_clip, self.max_clip = -65536, 65536
        self._apply_new_clip_values()
        self.sld_frame.blockSignals(True)
        self.sld_frame.setRange(0, len(self.tiff_images) - 1)
        self.sld_frame.setValue(0)
        self.sld_frame.setEnabled(True)
        self.sld_frame.blockSignals(False)
        self.current_frame = 0
        self.btn_play.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._display_frame(self.current_frame)
        self._display_average_frame()
        h, w = self.tiff_images[0].shape[:2]
        loaded_count = len(self.tiff_images)
        self.lbl_status.setText(
            f"Loaded {loaded_count}/{effective_total} frames from: {os.path.basename(path)} "
            f"({w}x{h}); clip[{self.min_clip}, {self.max_clip}] from %[{clip_lo:.1f},{clip_hi:.1f}]; "
            f"preview={'on' if preview else 'off'}, start={start}, span={span}"
        )

    def _apply_clip_percentiles_to_data(self):
        if not self.tiff_images:
            return
        clip_lo = float(self.spin_clip_lo.value())
        clip_hi = float(self.spin_clip_hi.value())
        if clip_lo > clip_hi:
            clip_lo, clip_hi = clip_hi, clip_lo
        stack = np.stack(self.tiff_images, axis=0)
        try:
            self.min_clip = int(np.percentile(stack, clip_lo))
            self.max_clip = int(np.percentile(stack, clip_hi))
        except Exception as e:
            print(f"Warning: percentile computation failed: {e}")
            return
        self._apply_new_clip_values()
        self._display_frame(self.current_frame)
        self._display_average_frame()

    def _apply_temporal_avg_to_data(self):
        if not self.tiff_images:
            return
        window = max(1, int(self.spin_tavg.value()))
        if window <= 1:
            return
        stack = np.stack(self.tiff_images, axis=0).astype(np.float64, copy=False)
        stack = _moving_average_stack_trailing(stack, window)
        self.tiff_images = [stack[i] for i in range(stack.shape[0])]
        self.average_frame = np.mean(stack, axis=0)
        self._display_frame(self.current_frame)
        self._display_average_frame()

    def _apply_gaussian_to_data(self):
        if not self.tiff_images:
            return
        sigma = float(self.spin_sigma.value())
        if sigma <= 0.0:
            return
        stack = np.stack(self.tiff_images, axis=0).astype(np.float64, copy=False)
        if _SCIPY_AVAILABLE:
            stack = _scipy_gaussian_filter(stack, sigma=(0.0, sigma, sigma), mode="nearest")
        else:
            stack = _gaussian_blur_stack_np(stack, sigma)
        self.tiff_images = [stack[i] for i in range(stack.shape[0])]
        self.average_frame = np.mean(stack, axis=0)
        self._display_frame(self.current_frame)
        self._display_average_frame()

    def _apply_new_clip_values(self):
        self.sld_min.blockSignals(True)
        self.sld_max.blockSignals(True)
        minv = int(np.clip(self.min_clip, -65536, 65536))
        maxv = int(np.clip(self.max_clip, -65536, 65536))
        if minv > maxv:
            minv, maxv = maxv, minv
        self.min_clip, self.max_clip = minv, maxv
        self.sld_min.setValue(minv)
        self.sld_max.setValue(maxv)
        self.lbl_min_val.setText(str(minv))
        self.lbl_max_val.setText(str(maxv))
        self.sld_min.blockSignals(False)
        self.sld_max.blockSignals(False)

    def play_movie(self):
        if not self.tiff_images:
            return
        self.running = True
        self.btn_play.setEnabled(False)
        self.btn_stop.setEnabled(True)
        interval_ms = max(1, int(round(1000.0 / float(self.fps))))
        self.timer.start(interval_ms)

    def stop_movie(self):
        self.running = False
        self.timer.stop()
        self.btn_play.setEnabled(bool(self.tiff_images))
        self.btn_stop.setEnabled(False)

    def _advance_frame(self):
        if not self.running or not self.tiff_images:
            return
        self.current_frame = (self.current_frame + 1) % len(self.tiff_images)
        self.sld_frame.blockSignals(True)
        self.sld_frame.setValue(self.current_frame)
        self.sld_frame.blockSignals(False)
        self._display_frame(self.current_frame)

    def _on_fps_changed(self, value: int):
        self.fps = int(value)
        self.lbl_fps_val.setText(str(self.fps))
        if self.running:
            self.play_movie()

    def _on_scroll_frame(self, value: int):
        if not self.tiff_images:
            return
        self.current_frame = int(value)
        self._display_frame(self.current_frame)

    def _on_min_clip_changed(self, value: int):
        self.min_clip = int(value)
        self.lbl_min_val.setText(str(self.min_clip))
        if self.min_clip > self.max_clip:
            self.max_clip = self.min_clip
            self.sld_max.blockSignals(True)
            self.sld_max.setValue(self.max_clip)
            self.sld_max.blockSignals(False)
            self.lbl_max_val.setText(str(self.max_clip))
        self._display_frame(self.current_frame)
        self._display_average_frame()

    def _on_max_clip_changed(self, value: int):
        self.max_clip = int(value)
        self.lbl_max_val.setText(str(self.max_clip))
        if self.max_clip < self.min_clip:
            self.min_clip = self.max_clip
            self.sld_min.blockSignals(True)
            self.sld_min.setValue(self.min_clip)
            self.sld_min.blockSignals(False)
            self.lbl_min_val.setText(str(self.min_clip))
        self._display_frame(self.current_frame)
        self._display_average_frame()

    def _clear_views(self):
        self.left_label.clear()
        self.right_label.clear()
        self.left_label.setText("No video loaded")
        self.right_label.setText("No average")

    def _normalize_to_uint8(self, arr: np.ndarray) -> np.ndarray:
        arrf = np.asarray(arr, dtype=np.float32)
        denom = max(1.0, float(self.max_clip - self.min_clip))
        arrf = np.clip((arrf - float(self.min_clip)) / denom, 0.0, 1.0)
        return (arrf * 255.0).astype(np.uint8)

    def _array_to_pixmap(self, arr: np.ndarray, target_label: QLabel) -> QPixmap:
        gray = self._normalize_to_uint8(arr)
        h, w = gray.shape[:2]
        qimg = QImage(gray.data, w, h, w, QImage.Format.Format_Grayscale8)
        pix = QPixmap.fromImage(qimg)
        return pix.scaled(
            target_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _display_frame(self, idx: int):
        if not self.tiff_images:
            return
        pix = self._array_to_pixmap(self.tiff_images[idx], self.left_label)
        self.left_label.setPixmap(pix)

    def _display_average_frame(self):
        if self.average_frame is None:
            self.right_label.clear()
            return
        pix = self._array_to_pixmap(self.average_frame, self.right_label)
        self.right_label.setPixmap(pix)


def main():
    app = QApplication(sys.argv)
    viewer = TiffViewerWidget()
    viewer.setWindowTitle("TIFF Viewer")
    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
