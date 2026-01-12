import sys
import os
import numpy as np
from scipy.ndimage import median_filter
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QSlider, QFileDialog, QHBoxLayout, QLineEdit, QComboBox, QProgressBar,
    QGridLayout, QCheckBox, QSpinBox
)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QPen
from PyQt5.QtCore import Qt, QTimer


class VideoViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Suite2p Binary Viewer (Final Version)")
        self.resize(900, 1000)

        # Assumed per-plane frame size
        self.width, self.height = 512, 512

        # State
        self.datas = []              # list of memmaps, one per plane
        self.total_frames = 0
        self.planes = []
        self.frame_idx = 0
        self.playing = False
        self.showing_mean = False
        self.mean_projection = None

        self.zoom = 1.0
        self.view_x = 0
        self.view_y = 0

        self.autos_vmin = []
        self.autos_vmax = []

        layout = QVBoxLayout()

        # --- user directory ---
        ul = QHBoxLayout()
        ul.addWidget(QLabel("User:"))
        self.user_combo = QComboBox()
        self.populate_users()
        ul.addWidget(self.user_combo)
        layout.addLayout(ul)

        # --- expID and planes ---
        el = QHBoxLayout()
        el.addWidget(QLabel("ExpID:"))
        self.exp_edit = QLineEdit()
        el.addWidget(self.exp_edit)
        layout.addLayout(el)

        pl = QHBoxLayout()
        pl.addWidget(QLabel("Planes:"))
        self.plane_edit = QLineEdit()
        self.plane_edit.setPlaceholderText("e.g., 0 or 0,1,2")
        pl.addWidget(self.plane_edit)
        layout.addLayout(pl)

        # --- pixel stride ---
        sl = QHBoxLayout()
        sl.addWidget(QLabel("Pixel stride:"))
        self.stride_edit = QLineEdit("1")
        sl.addWidget(self.stride_edit)
        layout.addLayout(sl)

        # --- filter mode + sizes ---
        fl = QHBoxLayout()
        fl.addWidget(QLabel("Median filter:"))
        self.filter_mode = QComboBox()
        self.filter_mode.addItems(["None", "Time", "Space"])
        fl.addWidget(self.filter_mode)

        fl.addWidget(QLabel("Time window:"))
        self.time_win = QSpinBox()
        self.time_win.setRange(3, 25)
        self.time_win.setSingleStep(2)
        self.time_win.setValue(3)
        fl.addWidget(self.time_win)

        fl.addWidget(QLabel("Space kernel:"))
        self.space_k = QSpinBox()
        self.space_k.setRange(3, 15)
        self.space_k.setSingleStep(2)
        self.space_k.setValue(3)
        fl.addWidget(self.space_k)
        layout.addLayout(fl)

        # --- load + mean ---
        bl = QHBoxLayout()
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self.load_files)
        bl.addWidget(self.load_btn)

        self.mean_btn = QPushButton("Mean Projection (≤1000 per plane)")
        self.mean_btn.setEnabled(False)
        self.mean_btn.clicked.connect(self.show_mean_projection)
        bl.addWidget(self.mean_btn)

        self.back_btn = QPushButton("Back to Video")
        self.back_btn.setEnabled(False)
        self.back_btn.clicked.connect(self.show_video)
        bl.addWidget(self.back_btn)
        layout.addLayout(bl)

        # --- progress + status ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        # --- image display ---
        self.label = QLabel("No video loaded")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        # --- frame slider ---
        fl2 = QHBoxLayout()
        fl2.addWidget(QLabel("Frame"))
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self.on_slider)
        fl2.addWidget(self.frame_slider)

        # Add label to show current frame number
        self.frame_label = QLabel("0 / 0")
        self.frame_label.setFixedWidth(80)
        fl2.addWidget(self.frame_label)

        layout.addLayout(fl2)


        # --- autoscale + min/max sliders ---
        al = QHBoxLayout()
        self.autoscale_cb = QCheckBox("Autoscale per plane")
        self.autoscale_cb.setChecked(True)
        self.autoscale_cb.stateChanged.connect(self.update_display)
        al.addWidget(self.autoscale_cb)

        al.addWidget(QLabel("Min"))
        self.min_slider = QSlider(Qt.Horizontal)
        self.min_slider.setRange(-32768, 32767)
        self.min_slider.setValue(0)
        self.min_slider.valueChanged.connect(self.update_display)
        al.addWidget(self.min_slider)

        al.addWidget(QLabel("Max"))
        self.max_slider = QSlider(Qt.Horizontal)
        self.max_slider.setRange(-32768, 32767)
        self.max_slider.setValue(2000)
        self.max_slider.valueChanged.connect(self.update_display)
        al.addWidget(self.max_slider)
        layout.addLayout(al)

        # --- zoom / pan controls ---
        grid = QGridLayout()
        self.btn_up = QPushButton("↑"); self.btn_up.clicked.connect(lambda: self.pan(0, -50))
        self.btn_down = QPushButton("↓"); self.btn_down.clicked.connect(lambda: self.pan(0, 50))
        self.btn_left = QPushButton("←"); self.btn_left.clicked.connect(lambda: self.pan(-50, 0))
        self.btn_right = QPushButton("→"); self.btn_right.clicked.connect(lambda: self.pan(50, 0))
        self.btn_zoom_in = QPushButton("+"); self.btn_zoom_in.clicked.connect(lambda: self.zoom_by(1.2))
        self.btn_zoom_out = QPushButton("−"); self.btn_zoom_out.clicked.connect(lambda: self.zoom_by(1/1.2))
        self.btn_reset = QPushButton("Reset View"); self.btn_reset.clicked.connect(self.reset_view)

        grid.addWidget(self.btn_zoom_in, 0, 0)
        grid.addWidget(self.btn_up, 0, 1)
        grid.addWidget(self.btn_zoom_out, 0, 2)
        grid.addWidget(self.btn_left, 1, 0)
        grid.addWidget(self.btn_reset, 1, 1)
        grid.addWidget(self.btn_right, 1, 2)
        grid.addWidget(self.btn_down, 2, 1)
        layout.addLayout(grid)

        # --- play/pause ---
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        layout.addWidget(self.play_btn)

        self.setLayout(layout)
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

    # -----------------------------------------------------
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

    def build_paths(self, planes):
        user = self.user_combo.currentText()
        expID = self.exp_edit.text().strip()
        if not expID or len(expID) < 15:
            return None, "Invalid expID."
        animalID = expID[14:]
        base = os.path.join("/home", user, "data", "Repository", animalID, expID, "suite2p")
        return [os.path.join(base, f"plane{p}", "data.bin") for p in planes], None
    
    def update_frame_label(self):
        if self.total_frames > 0:
            self.frame_label.setText(f"{self.frame_idx+1} / {self.total_frames}")
        else:
            self.frame_label.setText("0 / 0")


    # -----------------------------------------------------
    def load_files(self):
        self.status_label.setText("Mapping files...")
        QApplication.processEvents()

        self.planes = self.parse_planes()
        paths, err = self.build_paths(self.planes)
        if err:
            self.status_label.setText(err)
            return

        self.datas.clear()
        self.autos_vmin.clear()
        self.autos_vmax.clear()

        for path in paths:
            if not os.path.exists(path):
                self.status_label.setText(f"Missing: {path}")
                return
            self.datas.append(np.memmap(path, dtype=np.int16, mode="r"))

        frame_size = self.width * self.height
        totals = [d.size // frame_size for d in self.datas]
        self.total_frames = min(totals) if totals else 0
        if self.total_frames == 0:
            self.status_label.setText("No frames found.")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        n_samp = min(200, self.total_frames)
        for i, d in enumerate(self.datas):
            arr = d[:n_samp * frame_size].reshape(n_samp, self.height, self.width)
            vmin, vmax = np.percentile(arr, [1, 99])
            self.autos_vmin.append(float(vmin))
            self.autos_vmax.append(float(vmax))
            self.progress_bar.setValue(int((i + 1) / len(self.datas) * 100))
            QApplication.processEvents()
        self.progress_bar.setVisible(False)

        self.frame_slider.setRange(0, self.total_frames - 1)
        self.frame_slider.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.mean_btn.setEnabled(True)
        self.back_btn.setEnabled(False)
        self.showing_mean = False
        self.frame_idx = 0
        self.reset_view()
        self.status_label.setText(f"Loaded {len(self.datas)} plane(s); {self.total_frames} frames.")
        self.update_display()
        self.update_frame_label()


    # -----------------------------------------------------
    def get_raw_frame(self, pidx, idx):
        d = self.datas[pidx]
        S = self.width * self.height
        start = idx * S
        end = start + S
        return d[start:end].reshape(self.height, self.width)

    def get_filtered_frame(self, pidx, idx):
        frame = self.get_raw_frame(pidx, idx)
        mode = self.filter_mode.currentText()
        if mode == "Time":
            w = max(3, self.time_win.value() | 1)
            half = w // 2
            i0 = max(0, idx - half)
            i1 = min(self.total_frames - 1, idx + half)
            imgs = [self.get_raw_frame(pidx, i) for i in range(i0, i1 + 1)]
            frame = np.median(np.stack(imgs, axis=0), axis=0)
        elif mode == "Space":
            k = max(3, self.space_k.value() | 1)
            frame = median_filter(frame, size=k)
        try:
            s = int(self.stride_edit.text())
            if s > 1:
                frame = frame[::s, ::s]
        except ValueError:
            pass
        return frame

    # -----------------------------------------------------
    def reset_view(self):
        self.zoom = 1.0
        self.view_x = 0
        self.view_y = 0

    def zoom_by(self, factor):
        self.zoom = np.clip(self.zoom * factor, 1.0, 16.0)
        self.clamp_view()
        self.update_display()

    def pan(self, dx, dy):
        self.view_x += int(dx / max(1, int(self.stride_edit.text() or "1")))
        self.view_y += int(dy / max(1, int(self.stride_edit.text() or "1")))
        self.clamp_view()
        self.update_display()

    def clamp_view(self):
        crop_w = max(1, self.width // self.zoom)
        crop_h = max(1, self.height // self.zoom)
        self.view_x = int(np.clip(self.view_x, 0, max(0, self.width - crop_w)))
        self.view_y = int(np.clip(self.view_y, 0, max(0, self.height - crop_h)))

    def crop_by_view(self, img):
        s = max(1, int(self.stride_edit.text() or "1"))
        vx, vy = self.view_x // s, self.view_y // s
        crop_w = int((self.width // self.zoom) // s)
        crop_h = int((self.height // self.zoom) // s)
        crop_w = min(crop_w, img.shape[1])
        crop_h = min(crop_h, img.shape[0])
        vx = int(np.clip(vx, 0, max(0, img.shape[1] - crop_w)))
        vy = int(np.clip(vy, 0, max(0, img.shape[0] - crop_h)))
        return img[vy:vy + crop_h, vx:vx + crop_w], (vx, vy, crop_w, crop_h)

    # -----------------------------------------------------
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
        for pidx in range(len(self.datas)):
            f = self.get_filtered_frame(pidx, idx)
            f_crop, info = self.crop_by_view(f)
            if viewport is None:
                viewport = info
            imgs8.append(self.scale_plane(f_crop, pidx))
        concat = np.hstack(imgs8) if len(imgs8) > 1 else imgs8[0]
        return concat, viewport

    def compose_mean_concat(self):
        imgs8 = []
        viewport = None
        frame_size = self.width * self.height
        n = min(1000, self.total_frames)
        for pidx, d in enumerate(self.datas):
            arr = d[:n * frame_size].reshape(n, self.height, self.width)
            m = np.mean(arr, axis=0)
            try:
                s = int(self.stride_edit.text())
                if s > 1:
                    m = m[::s, ::s]
            except ValueError:
                pass
            m_crop, info = self.crop_by_view(m)
            if viewport is None:
                viewport = info
            imgs8.append(self.scale_plane(m_crop, pidx))
        concat = np.hstack(imgs8) if len(imgs8) > 1 else imgs8[0]
        return concat, viewport

    def draw_minimap(self, qp, viewport):
        mm_size = 100
        margin = 10
        pen = QPen(Qt.red)
        pen.setWidth(2)
        qp.setPen(pen)
        qp.drawRect(margin, margin, mm_size, mm_size)
        vx, vy, cw, ch = map(int, viewport)
        s = max(1, int(self.stride_edit.text() or "1"))
        vx *= s; vy *= s; cw *= s; ch *= s
        rx = margin + int(vx / self.width * mm_size)
        ry = margin + int(vy / self.height * mm_size)
        rw = max(2, int(cw / self.width * mm_size))
        rh = max(2, int(ch / self.height * mm_size))
        qp.drawRect(rx, ry, rw, rh)

    # -----------------------------------------------------
    def show_frame(self, use_mean=False):
        if not self.datas:
            return
        if use_mean:
            img8, viewport = self.compose_mean_concat()
        else:
            img8, viewport = self.compose_concat(self.frame_idx)
        h, w = img8.shape
        qimg = QImage(img8.data, w, h, w, QImage.Format_Grayscale8)
        pix = QPixmap.fromImage(qimg)
        painter = QPainter(pix)
        self.draw_minimap(painter, viewport)
        painter.end()
        self.label.setPixmap(pix.scaled(self.label.width(), self.label.height(),
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def update_display(self):
        self.show_frame(use_mean=self.showing_mean)

    # -----------------------------------------------------
    def toggle_play(self):
        if self.showing_mean:
            self.show_video()
        if not self.datas:
            return
        self.playing = not self.playing
        if self.playing:
            self.play_btn.setText("Pause")
            self.timer.start(30)
        else:
            self.play_btn.setText("Play")
            self.timer.stop()

    def next_frame(self):
        if not self.datas:
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
        if not self.datas:
            return
        self.timer.stop()
        self.playing = False
        self.play_btn.setText("Play")
        self.showing_mean = True
        self.back_btn.setEnabled(True)
        self.update_display()
        self.status_label.setText("Mean projection (≤1000 per plane).")

    def show_video(self):
        if not self.datas:
            return
        self.showing_mean = False
        self.back_btn.setEnabled(False)
        self.update_display()
        self.status_label.setText("Video view.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = VideoViewer()
    viewer.show()
    sys.exit(app.exec_())
