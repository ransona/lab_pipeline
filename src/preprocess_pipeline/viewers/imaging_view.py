import sys

from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget

from preprocess_pipeline.viewers.s2p_bin_view import S2PBinViewer
from preprocess_pipeline.viewers.tiff_view import TiffViewerWidget


class ImagingView(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Imaging View")
        self.resize(1500, 950)
        tabs = QTabWidget(self)
        tabs.addTab(S2PBinViewer(), "Suite2p Bin")
        tabs.addTab(TiffViewerWidget(), "Raw TIFF")
        self.setCentralWidget(tabs)


def main():
    app = QApplication(sys.argv)
    viewer = ImagingView()
    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
