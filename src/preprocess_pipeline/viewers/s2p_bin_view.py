import os
import pickle
import sys
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from scipy.ndimage import median_filter

from preprocess_pipeline.shared import paths


@dataclass
class PlaneBinary:
    path: str
    plane_name: str
    width: int
    height: int
    nframes: int
    data: np.memmap


def _load_ops_for_binary(bin_path: str):
    plane_dir = os.path.dirname(bin_path)
    ops_path = os.path.join(plane_dir, "ops.npy")
    if not os.path.exists(ops_path):
        raise FileNotFoundError(f"Could not find ops.npy beside binary: {bin_path}")
    return np.load(ops_path, allow_pickle=True).item()


def _plane_binary_from_path(bin_path: str):
    ops = _load_ops_for_binary(bin_path)
    width = int(ops["Lx"])
    height = int(ops["Ly"])
    frame_size = width * height
    data = np.memmap(bin_path, dtype=np.int16, mode="r")
    if frame_size <= 0:
        raise ValueError(f"Invalid frame size from ops.npy for {bin_path}")
    nframes = int(data.size // frame_size)
    if nframes <= 0:
        raise ValueError(f"No frames found in binary: {bin_path}")
    plane_name = os.path.basename(os.path.dirname(bin_path))
    return PlaneBinary(
        path=bin_path,
        plane_name=plane_name,
        width=width,
        height=height,
        nframes=nframes,
        data=data,
    )


class S2PBinViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Suite2p Binary Viewer")
        self.resize(1400, 900)

        self.planes: list[int] = []
        self.channel = 0
        self.loaded_planes: list[PlaneBinary] = []
        self.frame_idx = 0
        self.total_frames = 0
        self.playing = False
        self.showing_mean = False
        self.fps = 30
        self.zoom = 1.0
        self.view_x_frac = 0.0
        self.view_y_frac = 0.0
        self.autos_vmin = []
        self.autos_vmax = []

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)

        controls_panel = QWidget()
        controls_panel.setMaximumWidth(330)
        controls_panel.setMinimumWidth(280)
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(8, 8, 8, 8)
        controls_layout.setSpacing(6)

        viewer_layout = QVBoxLayout()
        viewer_layout.setContentsMargins(8, 8, 8, 8)
        viewer_layout.setSpacing(6)

        root_layout.addWidget(controls_panel, 3)
        root_layout.addLayout(viewer_layout, 7)

        ul = QHBoxLayout()
        ul.addWidget(QLabel("User:"))
        self.user_combo = QComboBox()
        self.populate_users()
        ul.addWidget(self.user_combo)
        controls_layout.addLayout(ul)

        el = QHBoxLayout()
        el.addWidget(QLabel("ExpID:"))
        self.exp_edit = QLineEdit()
        el.addWidget(self.exp_edit)
        controls_layout.addLayout(el)

        pl = QHBoxLayout()
        pl.addWidget(QLabel("Planes:"))
        self.plane_edit = QLineEdit()
        self.plane_edit.setPlaceholderText("e.g., 0 or 0,1,2")
        pl.addWidget(self.plane_edit)
        controls_layout.addLayout(pl)

        cl = QHBoxLayout()
        cl.addWidget(QLabel("Channel:"))
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["0", "1"])
        cl.addWidget(self.channel_combo)
        controls_layout.addLayout(cl)

        sl = QHBoxLayout()
        sl.addWidget(QLabel("Pixel stride:"))
        self.stride_edit = QLineEdit("1")
        sl.addWidget(self.stride_edit)
        controls_layout.addLayout(sl)

        filter_group = QGroupBox("Median Filter")
        fl = QGridLayout(filter_group)
        self.time_filter_cb = QCheckBox("Time")
        self.time_filter_cb.stateChanged.connect(self.on_filter_mode_changed)
        fl.addWidget(self.time_filter_cb, 0, 0)
        self.space_filter_cb = QCheckBox("Space")
        self.space_filter_cb.stateChanged.connect(self.on_filter_mode_changed)
        fl.addWidget(self.space_filter_cb, 0, 1)

        self.time_win_label = QLabel("Time frames")
        fl.addWidget(self.time_win_label, 1, 0)
        self.time_win = QSpinBox()
        self.time_win.setRange(3, 25)
        self.time_win.setSingleStep(2)
        self.time_win.setValue(3)
        self.time_win.valueChanged.connect(self.on_filter_mode_changed)
        fl.addWidget(self.time_win, 1, 1)

        self.space_k_label = QLabel("Space px")
        fl.addWidget(self.space_k_label, 2, 0)
        self.space_k = QSpinBox()
        self.space_k.setRange(3, 15)
        self.space_k.setSingleStep(2)
        self.space_k.setValue(3)
        self.space_k.valueChanged.connect(self.on_filter_mode_changed)
        fl.addWidget(self.space_k, 2, 1)
        self.filter_state_label = QLabel("")
        self.filter_state_label.setWordWrap(True)
        fl.addWidget(self.filter_state_label, 3, 0, 1, 2)
        controls_layout.addWidget(filter_group)

        bl = QGridLayout()
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self.load_files)
        bl.addWidget(self.load_btn, 0, 0)
        self.load_bin_btn = QPushButton("Load Bin...")
        self.load_bin_btn.clicked.connect(self.load_bin_files)
        bl.addWidget(self.load_bin_btn, 0, 1)
        self.mean_btn = QPushButton("Mean Projection")
        self.mean_btn.setEnabled(False)
        self.mean_btn.clicked.connect(self.show_mean_projection)
        bl.addWidget(self.mean_btn, 1, 0)
        self.back_btn = QPushButton("Back")
        self.back_btn.setEnabled(False)
        self.back_btn.clicked.connect(self.show_video)
        bl.addWidget(self.back_btn, 1, 1)
        controls_layout.addLayout(bl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        controls_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        controls_layout.addWidget(self.status_label)

        self.label = QLabel("No video loaded")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(700, 650)
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        viewer_layout.addWidget(self.label, 1)

        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("FPS"))
        self.fps_slider = QSlider(Qt.Orientation.Horizontal)
        self.fps_slider.setRange(1, 60)
        self.fps_slider.setValue(self.fps)
        self.fps_slider.valueChanged.connect(self.on_fps_changed)
        fps_layout.addWidget(self.fps_slider)
        self.fps_label = QLabel(str(self.fps))
        self.fps_label.setFixedWidth(40)
        fps_layout.addWidget(self.fps_label)
        viewer_layout.addLayout(fps_layout)

        fl2 = QHBoxLayout()
        fl2.addWidget(QLabel("Frame"))
        self.frame_slider = QSlider(Qt.Orientation.Horizontal)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self.on_slider)
        fl2.addWidget(self.frame_slider)
        self.frame_label = QLabel("0 / 0")
        self.frame_label.setFixedWidth(100)
        fl2.addWidget(self.frame_label)
        viewer_layout.addLayout(fl2)

        al = QGridLayout()
        self.autoscale_cb = QCheckBox("Autoscale per plane")
        self.autoscale_cb.setChecked(True)
        self.autoscale_cb.stateChanged.connect(self.on_autoscale_changed)
        al.addWidget(self.autoscale_cb, 0, 0, 1, 2)
        al.addWidget(QLabel("Min"), 1, 0)
        self.min_slider = QSlider(Qt.Orientation.Horizontal)
        self.min_slider.setRange(-32768, 32767)
        self.min_slider.setValue(0)
        self.min_slider.valueChanged.connect(self.on_intensity_slider_changed)
        al.addWidget(self.min_slider, 1, 1)
        self.min_value_label = QLabel("0")
        self.min_value_label.setFixedWidth(52)
        al.addWidget(self.min_value_label, 1, 2)
        al.addWidget(QLabel("Max"), 2, 0)
        self.max_slider = QSlider(Qt.Orientation.Horizontal)
        self.max_slider.setRange(-32768, 32767)
        self.max_slider.setValue(2000)
        self.max_slider.valueChanged.connect(self.on_intensity_slider_changed)
        al.addWidget(self.max_slider, 2, 1)
        self.max_value_label = QLabel("2000")
        self.max_value_label.setFixedWidth(52)
        al.addWidget(self.max_value_label, 2, 2)
        controls_layout.addLayout(al)

        grid = QGridLayout()
        self.btn_up = QPushButton("↑")
        self.btn_up.clicked.connect(lambda: self.pan(0, -50))
        self.btn_down = QPushButton("↓")
        self.btn_down.clicked.connect(lambda: self.pan(0, 50))
        self.btn_left = QPushButton("←")
        self.btn_left.clicked.connect(lambda: self.pan(-50, 0))
        self.btn_right = QPushButton("→")
        self.btn_right.clicked.connect(lambda: self.pan(50, 0))
        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.clicked.connect(lambda: self.zoom_by(1.2))
        self.btn_zoom_out = QPushButton("−")
        self.btn_zoom_out.clicked.connect(lambda: self.zoom_by(1 / 1.2))
        self.btn_reset = QPushButton("Reset View")
        self.btn_reset.clicked.connect(lambda: self.reset_view(redraw=True))
        grid.addWidget(self.btn_zoom_in, 0, 0)
        grid.addWidget(self.btn_up, 0, 1)
        grid.addWidget(self.btn_zoom_out, 0, 2)
        grid.addWidget(self.btn_left, 1, 0)
        grid.addWidget(self.btn_reset, 1, 1)
        grid.addWidget(self.btn_right, 1, 2)
        grid.addWidget(self.btn_down, 2, 1)
        controls_layout.addLayout(grid)

        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        controls_layout.addWidget(self.play_btn)
        controls_layout.addStretch(1)

        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)
        self.on_filter_mode_changed()

    def populate_users(self):
        homes = [d for d in os.listdir("/home") if os.path.isdir(os.path.join("/home", d))]
        self.user_combo.addItems(homes)

    def parse_planes(self):
        txt = self.plane_edit.text().strip()
        if not txt:
            return [0]
        try:
            return [int(s) for s in txt.split(",")]
        except Exception:
            return [0]

    def parse_channel(self):
        try:
            return int(self.channel_combo.currentText())
        except ValueError:
            return 0

    def get_exp_dir(self):
        user = self.user_combo.currentText()
        expID = self.exp_edit.text().strip()
        if not expID or len(expID) < 15:
            return os.path.join("/home", user)
        animalID, _, _, exp_dir_processed, _ = paths.find_paths(user, expID)
        return exp_dir_processed

    def get_default_bin_dir(self):
        exp_dir = self.get_exp_dir()
        if not os.path.isdir(exp_dir):
            parent = os.path.dirname(exp_dir)
            return parent if os.path.isdir(parent) else exp_dir

        channel = self.parse_channel()
        suite2p_dir = os.path.join(exp_dir, "suite2p")
        if channel == 1:
            ch2_dir = os.path.join(exp_dir, "ch2", "suite2p")
            if os.path.isdir(ch2_dir):
                return ch2_dir
        if os.path.isdir(suite2p_dir):
            return suite2p_dir
        return exp_dir

    def build_paths(self, planes):
        expID = self.exp_edit.text().strip()
        if not expID or len(expID) < 15:
            return None, "Invalid expID."
        exp_dir = self.get_exp_dir()
        if not os.path.isdir(exp_dir):
            return None, "Invalid expID."
        if self.channel == 0:
            suite2p_dir = os.path.join(exp_dir, "suite2p")
            bin_candidates = ["data.bin"]
        else:
            suite2p_dir = os.path.join(exp_dir, "ch2", "suite2p")
            bin_candidates = ["data.bin", "data_chan2.bin"]

        found_paths = []
        for plane in planes:
            plane_dir = os.path.join(suite2p_dir, f"plane{plane}")
            for bin_name in bin_candidates:
                path = os.path.join(plane_dir, bin_name)
                if os.path.exists(path):
                    found_paths.append(path)
                    break
            else:
                tried = ", ".join(os.path.join(plane_dir, name) for name in bin_candidates)
                return None, f"Missing channel {self.channel} binary. Tried: {tried}"
        return found_paths, None

    def update_frame_label(self):
        self.frame_label.setText(f"{self.frame_idx + 1} / {self.total_frames}" if self.total_frames > 0 else "0 / 0")

    def set_intensity_sliders(self, vmin, vmax):
        vmin = int(np.clip(round(vmin), self.min_slider.minimum(), self.min_slider.maximum()))
        vmax = int(np.clip(round(vmax), self.max_slider.minimum(), self.max_slider.maximum()))
        if vmax <= vmin:
            vmax = min(self.max_slider.maximum(), vmin + 1)
        self.min_slider.blockSignals(True)
        self.max_slider.blockSignals(True)
        self.autoscale_cb.blockSignals(True)
        self.min_slider.setValue(vmin)
        self.max_slider.setValue(vmax)
        self.autoscale_cb.blockSignals(False)
        self.min_slider.blockSignals(False)
        self.max_slider.blockSignals(False)
        self.update_intensity_labels()

    def update_autoscale_slider_values(self):
        if self.autos_vmin and self.autos_vmax:
            self.set_intensity_sliders(min(self.autos_vmin), max(self.autos_vmax))

    def update_intensity_labels(self):
        self.min_value_label.setText(str(self.min_slider.value()))
        self.max_value_label.setText(str(self.max_slider.value()))

    def on_intensity_slider_changed(self):
        if self.autoscale_cb.isChecked():
            self.autoscale_cb.blockSignals(True)
            self.autoscale_cb.setChecked(False)
            self.autoscale_cb.blockSignals(False)
        self.update_intensity_labels()
        self.update_display()

    def on_autoscale_changed(self):
        if self.autoscale_cb.isChecked():
            self.update_autoscale_slider_values()
        self.update_display()

    def on_filter_mode_changed(self, *args):
        using_time = self.time_filter_cb.isChecked()
        using_space = self.space_filter_cb.isChecked()
        self.time_win_label.setEnabled(using_time)
        self.time_win.setEnabled(using_time)
        self.space_k_label.setEnabled(using_space)
        self.space_k.setEnabled(using_space)
        parts = []
        if using_time:
            parts.append(f"Temporal median: {self.time_win.value()} frames")
        if using_space:
            parts.append(f"Spatial median: {self.space_k.value()} px kernel")
        self.filter_state_label.setText(" + ".join(parts) if parts else "Off")
        self.update_display()

    def on_fps_changed(self, value):
        self.fps = int(value)
        self.fps_label.setText(str(self.fps))
        if self.playing:
            self.timer.start(max(1, int(round(1000.0 / float(self.fps)))))

    def load_files(self):
        self.status_label.setText("Mapping files...")
        QApplication.processEvents()
        self.planes = self.parse_planes()
        self.channel = self.parse_channel()
        found_paths, err = self.build_paths(self.planes)
        if err:
            self.status_label.setText(err)
            return
        self.load_paths(found_paths, f"channel {self.channel}")

    def load_bin_files(self):
        self.channel = self.parse_channel()
        start_dir = self.get_default_bin_dir()
        found_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Suite2p binary file(s)",
            start_dir,
            "Binary files (*.bin);;All files (*)",
        )
        if not found_paths:
            return
        self.planes = list(range(len(found_paths)))
        self.load_paths(found_paths, "selected bin file")

    def load_paths(self, found_paths, source_label):
        self.status_label.setText("Mapping files...")
        QApplication.processEvents()
        self.loaded_planes.clear()
        self.autos_vmin.clear()
        self.autos_vmax.clear()

        try:
            for path in found_paths:
                self.loaded_planes.append(_plane_binary_from_path(path))
        except Exception as exc:
            self.status_label.setText(str(exc))
            self.loaded_planes.clear()
            return

        self.total_frames = min(plane.nframes for plane in self.loaded_planes) if self.loaded_planes else 0
        if self.total_frames == 0:
            self.status_label.setText("No frames found.")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        for i, plane in enumerate(self.loaded_planes):
            n_samp = min(200, plane.nframes)
            frame_size = plane.width * plane.height
            arr = plane.data[: n_samp * frame_size].reshape(n_samp, plane.height, plane.width)
            vmin, vmax = np.percentile(arr, [1, 99])
            self.autos_vmin.append(float(vmin))
            self.autos_vmax.append(float(vmax))
            self.progress_bar.setValue(int((i + 1) / len(self.loaded_planes) * 100))
            QApplication.processEvents()
        self.progress_bar.setVisible(False)

        if self.autoscale_cb.isChecked():
            self.update_autoscale_slider_values()

        self.frame_slider.setRange(0, self.total_frames - 1)
        self.frame_slider.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.mean_btn.setEnabled(True)
        self.back_btn.setEnabled(False)
        self.showing_mean = False
        self.frame_idx = 0
        self.reset_view(redraw=False)
        first_plane = self.loaded_planes[0]
        self.status_label.setText(
            f"Loaded {source_label}, {len(self.loaded_planes)} file(s); "
            f"{self.total_frames} frames from {os.path.dirname(first_plane.path)} "
            f"({first_plane.width}x{first_plane.height})"
        )
        self.update_display()
        self.update_frame_label()

    def get_raw_frame(self, pidx, idx):
        plane = self.loaded_planes[pidx]
        frame_size = plane.width * plane.height
        start = idx * frame_size
        end = start + frame_size
        return plane.data[start:end].reshape(plane.height, plane.width)

    def get_filtered_frame(self, pidx, idx):
        frame = self.get_raw_frame(pidx, idx)
        if self.time_filter_cb.isChecked():
            w = max(3, self.time_win.value() | 1)
            half = w // 2
            i0 = max(0, idx - half)
            i1 = min(self.total_frames - 1, idx + half)
            imgs = [self.get_raw_frame(pidx, i) for i in range(i0, i1 + 1)]
            frame = np.median(np.stack(imgs, axis=0), axis=0)
        if self.space_filter_cb.isChecked():
            k = max(3, self.space_k.value() | 1)
            frame = median_filter(frame, size=k)
        try:
            s = int(self.stride_edit.text())
            if s > 1:
                frame = frame[::s, ::s]
        except ValueError:
            pass
        return frame

    def reset_view(self, redraw=True):
        self.zoom = 1.0
        self.view_x_frac = 0.0
        self.view_y_frac = 0.0
        self.clamp_view()
        if redraw:
            self.update_display()

    def zoom_by(self, factor):
        self.zoom = float(np.clip(self.zoom * factor, 1.0, 16.0))
        self.clamp_view()
        self.update_display()

    def pan(self, dx, dy):
        if not self.loaded_planes:
            return
        ref_w = self.loaded_planes[0].width
        ref_h = self.loaded_planes[0].height
        self.view_x_frac += dx / max(ref_w, 1)
        self.view_y_frac += dy / max(ref_h, 1)
        self.clamp_view()
        self.update_display()

    def clamp_view(self):
        max_frac = max(0.0, 1.0 - (1.0 / self.zoom))
        self.view_x_frac = float(np.clip(self.view_x_frac, 0.0, max_frac))
        self.view_y_frac = float(np.clip(self.view_y_frac, 0.0, max_frac))

    def crop_by_view(self, img):
        crop_w = max(1, int(round(img.shape[1] / self.zoom)))
        crop_h = max(1, int(round(img.shape[0] / self.zoom)))
        vx = int(round(self.view_x_frac * img.shape[1]))
        vy = int(round(self.view_y_frac * img.shape[0]))
        vx = int(np.clip(vx, 0, max(0, img.shape[1] - crop_w)))
        vy = int(np.clip(vy, 0, max(0, img.shape[0] - crop_h)))
        return img[vy:vy + crop_h, vx:vx + crop_w], (vx, vy, crop_w, crop_h)

    def scale_plane(self, img, pidx):
        if self.autoscale_cb.isChecked() and pidx < len(self.autos_vmin):
            vmin, vmax = self.autos_vmin[pidx], self.autos_vmax[pidx]
        else:
            vmin, vmax = self.min_slider.value(), self.max_slider.value()
            vmax = max(vmax, vmin + 1)
        return np.clip((img - vmin) / (vmax - vmin) * 255, 0, 255).astype(np.uint8)

    def compose_concat(self, idx):
        imgs8 = []
        viewport = None
        for pidx in range(len(self.loaded_planes)):
            frame = self.get_filtered_frame(pidx, idx)
            frame_crop, info = self.crop_by_view(frame)
            if viewport is None:
                viewport = info
            imgs8.append(self.scale_plane(frame_crop, pidx))
        concat = np.hstack(imgs8) if len(imgs8) > 1 else imgs8[0]
        return concat, viewport

    def compose_mean_concat(self):
        imgs8 = []
        viewport = None
        for pidx, plane in enumerate(self.loaded_planes):
            n = min(1000, plane.nframes)
            frame_size = plane.width * plane.height
            arr = plane.data[: n * frame_size].reshape(n, plane.height, plane.width)
            mean_img = np.mean(arr, axis=0)
            try:
                s = int(self.stride_edit.text())
                if s > 1:
                    mean_img = mean_img[::s, ::s]
            except ValueError:
                pass
            mean_crop, info = self.crop_by_view(mean_img)
            if viewport is None:
                viewport = info
            imgs8.append(self.scale_plane(mean_crop, pidx))
        concat = np.hstack(imgs8) if len(imgs8) > 1 else imgs8[0]
        return concat, viewport

    def draw_minimap(self, qp, viewport):
        if not self.loaded_planes:
            return
        mm_size = 100
        margin = 10
        pen = QPen(Qt.GlobalColor.red)
        pen.setWidth(2)
        qp.setPen(pen)
        qp.drawRect(margin, margin, mm_size, mm_size)
        ref_plane = self.loaded_planes[0]
        vx, vy, cw, ch = map(int, viewport)
        rx = margin + int(vx / max(ref_plane.width, 1) * mm_size)
        ry = margin + int(vy / max(ref_plane.height, 1) * mm_size)
        rw = max(2, int(cw / max(ref_plane.width, 1) * mm_size))
        rh = max(2, int(ch / max(ref_plane.height, 1) * mm_size))
        qp.drawRect(rx, ry, rw, rh)

    def show_frame(self, use_mean=False):
        if not self.loaded_planes:
            return
        img8, viewport = self.compose_mean_concat() if use_mean else self.compose_concat(self.frame_idx)
        height, width = img8.shape
        qimg = QImage(img8.data, width, height, width, QImage.Format.Format_Grayscale8)
        pix = QPixmap.fromImage(qimg)
        painter = QPainter(pix)
        self.draw_minimap(painter, viewport)
        painter.end()
        self.label.setPixmap(
            pix.scaled(
                self.label.width(),
                self.label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def update_display(self):
        self.show_frame(use_mean=self.showing_mean)

    def toggle_play(self):
        if self.showing_mean:
            self.show_video()
        if not self.loaded_planes:
            return
        self.playing = not self.playing
        if self.playing:
            self.play_btn.setText("Pause")
            self.timer.start(max(1, int(round(1000.0 / float(self.fps)))))
        else:
            self.play_btn.setText("Play")
            self.timer.stop()

    def next_frame(self):
        if not self.loaded_planes:
            return
        self.frame_idx = (self.frame_idx + 1) % self.total_frames
        self.frame_slider.setValue(self.frame_idx)
        self.update_display()
        self.update_frame_label()

    def on_slider(self, value):
        self.frame_idx = value
        self.update_display()
        self.update_frame_label()

    def show_mean_projection(self):
        if not self.loaded_planes:
            return
        self.timer.stop()
        self.playing = False
        self.play_btn.setText("Play")
        self.showing_mean = True
        self.back_btn.setEnabled(True)
        self.update_display()
        self.status_label.setText("Mean projection (≤1000 frames per plane).")

    def show_video(self):
        if not self.loaded_planes:
            return
        self.showing_mean = False
        self.back_btn.setEnabled(False)
        self.update_display()
        self.status_label.setText("Video view.")


def main():
    app = QApplication(sys.argv)
    viewer = S2PBinViewer()
    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
