import sys
import os
import pickle
import shutil
import cv2
import numpy as np
import pandas as pd

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWidgets import (QMainWindow, QApplication, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QLineEdit, QSlider, QMessageBox)
from PyQt5.QtCore import Qt, QTimer

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5 import NavigationToolbar2QT as NavigationToolbar

import organise_paths

class VideoAnalysisApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.loaded = False
        self.playing = False
        self.last_vline_frame = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.playFrame)
        self.vlines = []
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Video Analysis GUI")
        centralWidget = QWidget()
        self.setCentralWidget(centralWidget)
        mainLayout = QVBoxLayout(centralWidget)

        inputLayout = QHBoxLayout()
        self.userIdEdit = QLineEdit()
        self.userIdEdit.setPlaceholderText("Enter User ID")
        self.expIdEdit = QLineEdit()
        self.expIdEdit.setPlaceholderText("Enter Experiment ID")
        self.loadButton = QPushButton("Load Data")
        self.loadButton.clicked.connect(self.loadData)
        inputLayout.addWidget(QLabel("User ID:"))
        inputLayout.addWidget(self.userIdEdit)
        inputLayout.addWidget(QLabel("Experiment ID:"))
        inputLayout.addWidget(self.expIdEdit)
        inputLayout.addWidget(self.loadButton)
        mainLayout.addLayout(inputLayout)

        controlLayout = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self.updateFrame)
        self.playButton = QPushButton("Play")
        self.playButton.setEnabled(False)
        self.playButton.clicked.connect(self.startPlayback)
        self.stopButton = QPushButton("Stop")
        self.stopButton.setEnabled(False)
        self.stopButton.clicked.connect(self.stopPlayback)
        controlLayout.addWidget(self.slider)
        controlLayout.addWidget(self.playButton)
        controlLayout.addWidget(self.stopButton)
        mainLayout.addLayout(controlLayout)

        videoLayout = QHBoxLayout()
        self.leftVideoLabel = QLabel("Left Eye Video")
        self.leftVideoLabel.setFixedSize(320, 240)
        self.rightVideoLabel = QLabel("Right Eye Video")
        self.rightVideoLabel.setFixedSize(320, 240)
        videoLayout.addWidget(self.leftVideoLabel)
        videoLayout.addWidget(self.rightVideoLabel)
        mainLayout.addLayout(videoLayout)

        percentileLayout = QHBoxLayout()
        self.lowerSlider = QSlider(Qt.Horizontal)
        self.lowerSlider.setMinimum(0)
        self.lowerSlider.setMaximum(100)
        self.lowerSlider.setValue(0)
        self.upperSlider = QSlider(Qt.Horizontal)
        self.upperSlider.setMinimum(0)
        self.upperSlider.setMaximum(100)
        self.upperSlider.setValue(70)
        self.lowerSlider.valueChanged.connect(self.updateFrame)
        self.upperSlider.valueChanged.connect(self.updateFrame)
        percentileLayout.addWidget(QLabel("Lower Clip %"))
        percentileLayout.addWidget(self.lowerSlider)
        percentileLayout.addWidget(QLabel("Upper Clip %"))
        percentileLayout.addWidget(self.upperSlider)
        mainLayout.addLayout(percentileLayout)

        self.figure = Figure(figsize=(8, 6))
        self.canvas = FigureCanvas(self.figure)
        mainLayout.addWidget(self.canvas)

        self.toolbar = NavigationToolbar(self.canvas, self)
        mainLayout.addWidget(self.toolbar)

    def safe_set_ylim(self, ax, data, lower_pct, upper_pct):
        try:
            low = np.nanpercentile(data, lower_pct)
            high = np.nanpercentile(data, upper_pct)
            if np.isnan(low) or np.isnan(high) or np.isinf(low) or np.isinf(high):
                raise ValueError
            ax.set_ylim(low, high)
        except:
            ax.set_ylim(-1, 1)

    def overlay_csv_points(self, frame, pos, eyeX, eyeY, pupilX, pupilY):
        if pos >= eyeX.shape[0] or pos >= pupilX.shape[0]:
            return frame
        h, w = frame.shape[:2]
        for x, y in zip(eyeX[pos], eyeY[pos]):
            if not np.isnan(x) and not np.isnan(y) and 0 <= x < w and 0 <= y < h:
                frame = cv2.circle(frame, (int(x), int(y)), 2, (255, 0, 0), -1)
        for x, y in zip(pupilX[pos], pupilY[pos]):
            if not np.isnan(x) and not np.isnan(y) and 0 <= x < w and 0 <= y < h:
                frame = cv2.circle(frame, (int(x), int(y)), 2, (0, 255, 0), -1)
        return frame

    def overlay_plot(self, frame, position, eyeDat):
        if np.isnan(eyeDat['x'][position]) or np.isnan(eyeDat['y'][position]) or np.isnan(eyeDat['radius'][position]):
            return frame
        color = (0, 0, 255)
        center = (int(eyeDat['x'][position]), int(eyeDat['y'][position]))
        radius = int(eyeDat['radius'][position])
        frame = cv2.circle(frame, center, radius, color, 2)
        return frame

    def playVideoFrame(self, frame_position, video_path, eyedat, side="Left"):
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_position)
        ret, frame = cap.read()
        cap.release()
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = frame[:, :, 0]
            lo = np.percentile(frame, self.lowerSlider.value())
            hi = np.percentile(frame, self.upperSlider.value())
            frame = np.clip(frame, lo, hi)
            frame = (frame - frame.min()) / (frame.max() - frame.min()) * 255
            frame = np.stack((frame,) * 3, axis=-1).astype(np.uint8)
            frame = self.overlay_plot(frame, frame_position, eyedat)
            if side == "Left" and hasattr(self, 'left_eyeX'):
                frame = self.overlay_csv_points(frame, frame_position, self.left_eyeX, self.left_eyeY, self.left_pupilX, self.left_pupilY)
            elif side == "Right" and hasattr(self, 'right_eyeX'):
                frame = self.overlay_csv_points(frame, frame_position, self.right_eyeX, self.right_eyeY, self.right_pupilX, self.right_pupilY)
            return frame
        return None

    def loadData(self):
        self.userID = self.userIdEdit.text().strip()
        self.expID = self.expIdEdit.text().strip()
        if not self.userID or not self.expID:
            QMessageBox.warning(self, "Input Error", "Please enter both User ID and Experiment ID")
            return

        self.animalID, self.remote_repository_root, self.processed_root, \
            self.exp_dir_processed, self.exp_dir_raw = organise_paths.find_paths(self.userID, self.expID)
        self.exp_dir_processed_recordings = os.path.join(self.exp_dir_processed, 'recordings')
        self.exp_dir_processed_cut = os.path.join(self.exp_dir_processed, 'cut')

        self.video_path_left = os.path.join(self.exp_dir_processed, f"{self.expID}_eye1_left.avi")
        self.video_path_right = os.path.join(self.exp_dir_processed, f"{self.expID}_eye1_right.avi")

        if not os.path.isfile(self.video_path_left):
            try:
                shutil.copyfile(os.path.join(self.exp_dir_raw, f"{self.expID}_eye1_left.avi"), self.video_path_left)
                shutil.copyfile(os.path.join(self.exp_dir_raw, f"{self.expID}_eye1_right.avi"), self.video_path_right)
            except Exception as e:
                QMessageBox.critical(self, "File Error", "Eye videos not found. Please check the paths.")
                return

        try:
            with open(os.path.join(self.exp_dir_processed_recordings, 'dlcEyeLeft.pickle'), "rb") as file:
                self.left_eyedat = pickle.load(file)
            with open(os.path.join(self.exp_dir_processed_recordings, 'dlcEyeRight.pickle'), "rb") as file:
                self.right_eyedat = pickle.load(file)
        except Exception as e:
            QMessageBox.critical(self, "Data Error", "Error loading pupil data: " + str(e))
            return

        files = os.listdir(self.exp_dir_processed)
        self.left_csv = next((f for f in files if "leftDLC" in f and f.endswith(".csv")), None)
        self.right_csv = next((f for f in files if "rightDLC" in f and f.endswith(".csv")), None)

        if self.left_csv:
            self.left_dlc_data = pd.read_csv(os.path.join(self.exp_dir_processed, self.left_csv), delimiter=',', skiprows=[0,1,2], header=None)
            self.left_eyeX = self.left_dlc_data.iloc[:,[25,28,31,34]].values
            self.left_eyeY = self.left_dlc_data.loc[:,[26,29,32,35]].values
            self.left_pupilX = self.left_dlc_data.loc[:,1:22:3].values
            self.left_pupilY = self.left_dlc_data.loc[:,2:23:3].values

        if self.right_csv:
            self.right_dlc_data = pd.read_csv(os.path.join(self.exp_dir_processed, self.right_csv), delimiter=',', skiprows=[0,1,2], header=None)
            self.right_eyeX = self.right_dlc_data.iloc[:,[25,28,31,34]].values
            self.right_eyeY = self.right_dlc_data.loc[:,[26,29,32,35]].values
            self.right_pupilX = self.right_dlc_data.loc[:,1:22:3].values
            self.right_pupilY = self.right_dlc_data.loc[:,2:23:3].values

        cap = cv2.VideoCapture(self.video_path_left)
        if not cap.isOpened():
            QMessageBox.critical(self, "Video Error", "Could not open left video file.")
            return
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        self.slider.setMinimum(0)
        self.slider.setMaximum(self.total_frames - 1)
        self.slider.setEnabled(True)
        self.playButton.setEnabled(True)
        self.stopButton.setEnabled(True)
        self.loaded = True

        self.plotPupilProperties()
        self.updateFrame()

    def updateVLines(self, position):
        if self.vlines:
            for vline in self.vlines:
                vline.set_xdata(position)
            self.canvas.draw_idle()

    def updateFrame(self):
        if not self.loaded:
            return
        position = self.slider.value()

        frame_left = self.playVideoFrame(position, self.video_path_left, self.left_eyedat, side="Left")
        if frame_left is not None:
            image_left = QtGui.QImage(frame_left.data, frame_left.shape[1], frame_left.shape[0],
                                      frame_left.strides[0], QtGui.QImage.Format_RGB888)
            pixmap_left = QtGui.QPixmap.fromImage(image_left)
            self.leftVideoLabel.setPixmap(pixmap_left.scaled(self.leftVideoLabel.size(), Qt.KeepAspectRatio))

        frame_right = self.playVideoFrame(position, self.video_path_right, self.right_eyedat, side="Right")
        if frame_right is not None:
            image_right = QtGui.QImage(frame_right.data, frame_right.shape[1], frame_right.shape[0],
                                       frame_right.strides[0], QtGui.QImage.Format_RGB888)
            pixmap_right = QtGui.QPixmap.fromImage(image_right)
            self.rightVideoLabel.setPixmap(pixmap_right.scaled(self.rightVideoLabel.size(), Qt.KeepAspectRatio))

        self.updateVLines(position)

    def startPlayback(self):
        if not self.loaded:
            return
        self.playing = True
        self.timer.start(33)

    def stopPlayback(self):
        self.playing = False
        self.timer.stop()

    def playFrame(self):
        if self.slider.value() < self.total_frames - 1:
            self.slider.setValue(self.slider.value() + 1)
        else:
            self.stopPlayback()

    def plotPupilProperties(self):
        try:
            with open(os.path.join(self.exp_dir_processed_recordings, 'dlcEyeLeft.pickle'), "rb") as file:
                left_dlc = pickle.load(file)
            with open(os.path.join(self.exp_dir_processed_recordings, 'dlcEyeRight.pickle'), "rb") as file:
                right_dlc = pickle.load(file)
        except Exception as e:
            print("Error loading pupil data for plotting:", e)
            return

        lower_pct = self.lowerSlider.value()
        upper_pct = self.upperSlider.value()

        self.figure.clear()
        axs = self.figure.subplots(4, 1, sharex=True)

        left_x = left_dlc['x'] - np.nanmedian(left_dlc['x'])
        left_y = left_dlc['y'] - np.nanmedian(left_dlc['y'])
        ax = axs[0]
        ax.plot(left_x, color='skyblue')
        ax.plot(left_y, color='navy')
        self.safe_set_ylim(ax, np.concatenate([left_x, left_y]), lower_pct, upper_pct)
        ax.set_ylabel('Left Pos')

        right_x = right_dlc['x'] - np.nanmedian(right_dlc['x'])
        right_y = right_dlc['y'] - np.nanmedian(right_dlc['y'])
        ax = axs[1]
        ax.plot(right_x, color='lightcoral')
        ax.plot(right_y, color='maroon')
        self.safe_set_ylim(ax, np.concatenate([right_x, right_y]), lower_pct, upper_pct)
        ax.set_ylabel('Right Pos')

        ax = axs[2]
        ax.plot(left_dlc['radius'], color='blue')
        ax.plot(right_dlc['radius'], color='red')
        self.safe_set_ylim(ax, np.concatenate([left_dlc['radius'], right_dlc['radius']]), lower_pct, upper_pct)
        ax.set_ylabel('Radius')

        ax = axs[3]
        ax.plot(left_dlc['velocity'], color='blue')
        ax.plot(right_dlc['velocity'], color='red')
        self.safe_set_ylim(ax, np.concatenate([left_dlc['velocity'], right_dlc['velocity']]), lower_pct, upper_pct)
        ax.set_ylabel('Velocity')

        self.vlines = []
        current_frame = self.slider.value() if self.loaded else 0
        for ax in axs:
            vline = ax.axvline(x=current_frame, color='k', linestyle='--')
            self.vlines.append(vline)

        self.canvas.draw()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = VideoAnalysisApp()
    win.show()
    sys.exit(app.exec_())
