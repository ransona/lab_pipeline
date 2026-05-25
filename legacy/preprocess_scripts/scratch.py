import sys
import os
import numpy as np
import cv2
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QPushButton,
    QSlider, QFileDialog, QHBoxLayout, QLineEdit, QComboBox, QProgressBar
)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal


# ---------- Worker Thread for File Loading ----------
class LoaderThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(np.ndarray, int)
    error = pyqtSignal(str)

    def __init__(self, filename, width, height, parent=None):
        super().__init__(parent)
        self.filename = filename
        self.width = width
        self.height = height

    def run(self):
        try:
            file_size = os.path.getsize(self.filename)
            bytes_per_frame = self.width * self.height * 2  # int16 = 2 bytes
            num_frames = file_size // bytes_per_frame

            frames = np.zeros((num_frames, self.height, self.width), dtype=np.int16)

            with open(self.filename, "rb") as f:
                for i in range(num_frames):
                    data = np.fromfile(f, dtype=np.int16, count=self.width * self.height)
                    if data.size < self.width * self.height:
                        break
                    frames[i, :, :] = data.reshape((self.height, self.width))

                    if i % 100 == 0 or i == num_frames - 1:
                        pct = int((i + 1) / num_frames * 100)
                        self.progress.emit(pct)

            frames = frames.transpose(1, 2, 0).astype(np.float32)
            self.finished.emit(frames, num_frames)

        except Exception as e:
            self.error.emit(str(e))


# ---------- Main GUI ----------
class VideoViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Suite2p Binary Video Viewer (512x512xN)")
        self.resize(650, 950)

        self.width, self.height = 512, 512
        self.frames = None
        self.frame_idx = 0
        self.playing = False
        self.mean_projection = None
        self.showing_mean = False
        self.loader_thread = None

        layout = QVBoxLayout()

        # --- User selection ---
        user_layout = QHBoxLayout()
        user_label = QLabel("User:")
        self.user_combo = QComboBox()
        self.populate_users()
        user_layout.addWidget(user_label)
        user_layout.addWidget(self.user_combo)
        layout.addLayout(user_layout)

        # --- ExpID input ---
        exp_layout = QHBoxLayout()
        exp_label = QLabel("ExpID:")
        self.exp_edit = QLineEdit()
        exp_layout.addWidget(exp_label)
        exp_layout.addWidget(self.exp_edit)
        layout.addLayout(exp_layout)

        # --- Plane input ---
        plane_layout = QHBoxLayout()
        plane_label = QLabel("Plane:")
        self.plane_edit = QLineEdit()
        self.plane_edit.setPlaceholderText("e.g., 0")
        plane_layout.addWidget(plane_label)
        plane_layout.addWidget(self.plane_edit)
        layout.addLayout(plane_layout)

        # --- Buttons ---
        btn_layout = QHBoxLayout()
        self.load_btn = QPushButton("Load Data")
        self.load_btn.clicked.connect(self.load_file)
        self.mean_btn = QPushButton("Mean Z-Projection")
        self.mean_btn.clicked.connect(self.show_mean_projection)
        self.mean_btn.setEnabled(False)
        self.back_btn = QPushButton("Back to Video")
        self.back_btn.clicked.connect(self.show_video)
        self.back_btn.setEnabled(False)
        btn_layout.addWidget(self.load_btn)
        btn_layout.addWidget(self.mean_btn)
        btn_layout.addWidget(self.back_btn)
        layout.addLayout(btn_layout)

        # --- Progress bar ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # --- Image display ---
        self.label = QLabel("No video loaded")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        # --- Frame slider ---
        frame_layout = QHBoxLayout()
        frame_label = QLabel("Frame")
        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self.update_frame_from_slider)
        frame_layout.addWidget(frame_label)
        frame_layout.addWidget(self.frame_slider)
        layout.addLayout(frame_layout)

        # --- Intensity sliders ---
        min_layout = QHBoxLayout()
        min_label = QLabel("Min")
        self.min_slider = QSlider(Qt.Horizontal)
        self.min_slider.setRange(0, 65535)
        self.min_slider.setValue(0)
        self.min_slider.valueChanged.connect(self.update_display)
        min_layout.addWidget(min_label)
        min_layout.addWidget(self.min_slider)
        layout.addLayout(min_layout)

        max_layout = QHBoxLayout()
        max_label = QLabel("Max")
        self.max_slider = QSlider(Qt.Horizontal)
        self.max_slider.setRange(0, 65535)
        self.max_slider.setValue(2000)
        self.max_slider.valueChanged.connect(self.update_display)
        max_layout.addWidget(max_label)
        max_layout.addWidget(self.max_slider)
        layout.addLayout(max_layout)

        # --- Play button ---
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        layout.addWidget(self.play_btn)

        self.setLayout(layout)

        # --- Timer ---
        self.timer = QTimer()
        self.timer.timeout.connect(self.next_frame)

    # --- Utility methods ---
    def populate_users(self):
        home_dirs = [d for d in os.listdir("/home") if os.path.isdir(os.path.join("/home", d))]
        self.user_combo.addItems(home_dirs)

    def build_path(self):
        user = self.user_combo.currentText()
        expID = self.exp_edit.text().strip()
        plane = self.plane_edit.text().strip()

        if expID == "":
            return None
        if len(expID) < 15:
            self.label.setText("Error: expID must be at least 15 characters.")
            return None

        animalID = expID[14:]
        return os.path.join(
            "/home", user, "data", "Repository", animalID,
            expID, "suite2p", f"plane{plane}", "data.bin"
        )

    # --- File loading ---
    def load_file(self):
        filename = self.build_path()
        if filename is None:
            filename, _ = QFileDialog.getOpenFileName(
                self, "Open Binary File", "", "Binary files (*.bin);;All files (*)"
            )
            if not filename:
                return

        if not os.path.exists(filename):
            self.label.setText(f"File not found:\n{filename}")
            return

        # Disable UI and show progress bar
        self.load_btn.setEnabled(False)
        self.mean_btn.setEnabled(False)
        self.play_btn.setEnabled(False)
        self.frame_slider.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.label.setText("Loading video...")

        # Start loading thread
        self.loader_thread = LoaderThread(filename, self.width, self.height)
        self.loader_thread.progress.connect(self.progress_bar.setValue)
        self.loader_thread.finished.connect(self.on_load_finished)
        self.loader_thread.error.connect(self.on_load_error)
        self.loader_thread.start()

    def on_load_finished(self, frames, num_frames):
        self.frames = frames
        self.progress_bar.setVisible(False)
        self.load_btn.setEnabled(True)
        self.mean_btn.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.frame_slider.setRange(0, num_frames - 1)
        self.frame_slider.setEnabled(True)
        self.frame_idx = 0

        # Set dynamic min/max based on data
        data_min, data_max = np.percentile(frames, [1, 99])  # robust min/max
        self.min_slider.setRange(int(frames.min()), int(frames.max()))
        self.max_slider.setRange(int(frames.min()), int(frames.max()))
        self.min_slider.setValue(int(data_min))
        self.max_slider.setValue(int(data_max))

        self.showing_mean = False
        self.show_frame()
        self.label.setText(f"Loaded {num_frames} frames ({frames.shape}).")

    def on_load_error(self, msg):
        self.label.setText(f"Error loading file:\n{msg}")
        self.progress_bar.setVisible(False)
        self.load_btn.setEnabled(True)

    # --- Display handling ---
    def show_frame(self, use_mean=False):
        if self.frames is None:
            return

        if use_mean:
            frame = self.mean_projection
        else:
            frame = self.frames[:, :, self.frame_idx]

        vmin = self.min_slider.value()
        vmax = self.max_slider.value()
        vmax = max(vmax, vmin + 1)
        frame = np.clip((frame - vmin) / (vmax - vmin) * 255.0, 0, 255).astype(np.uint8)

        qimg = QImage(frame.data, self.width, self.height, self.width, QImage.Format_Grayscale8)
        self.label.setPixmap(QPixmap.fromImage(qimg).scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def update_display(self):
        # Update intensity scaling without changing image type
        self.show_frame(use_mean=self.showing_mean)

    # --- Controls ---
    def toggle_play(self):
        if self.frames is None or self.showing_mean:
            return
        self.playing = not self.playing
        if self.playing:
            self.play_btn.setText("Pause")
            self.timer.start(30)
        else:
            self.play_btn.setText("Play")
            self.timer.stop()

    def next_frame(self):
        if self.frames is None:
            return
        self.frame_idx = (self.frame_idx + 1) % self.frames.shape[2]
        self.frame_slider.setValue(self.frame_idx)
        self.show_frame()

    def update_frame_from_slider(self, value):
        if self.frames is None:
            return
        self.frame_idx = value
        self.show_frame()

    def show_mean_projection(self):
        if self.frames is None:
            return
        self.timer.stop()
        self.playing = False
        self.play_btn.setText("Play")
        self.mean_projection = np.mean(self.frames, axis=2)
        self.showing_mean = True
        self.back_btn.setEnabled(True)
        self.show_frame(use_mean=True)

    def show_video(self):
        if self.frames is None:
            return
        self.showing_mean = False
        self.back_btn.setEnabled(False)
        self.show_frame()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = VideoViewer()
    viewer.show()
    sys.exit(app.exec_())
