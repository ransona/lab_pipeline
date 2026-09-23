import argparse
import sys

from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget

from preprocess_pipeline.viewers.s2p_bin_view import S2PBinViewer
from preprocess_pipeline.viewers.tiff_view import TiffViewerWidget


class ImagingView(QMainWindow):
    def __init__(self, bin_paths=None):
        super().__init__()
        self.setWindowTitle("Imaging View")
        self.resize(1500, 950)
        tabs = QTabWidget(self)
        tabs.addTab(S2PBinViewer(initial_bin_paths=bin_paths), "Suite2p Bin")
        tabs.addTab(TiffViewerWidget(), "Raw TIFF")
        self.setCentralWidget(tabs)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect raw TIFF and Suite2p binary movies.")
    parser.add_argument(
        "--bin", dest="bin_paths", nargs="+", default=None,
        help="Suite2p binary file(s) to load on launch.",
    )
    args = parser.parse_args(argv)
    app = QApplication(sys.argv)
    viewer = ImagingView(bin_paths=args.bin_paths)
    viewer.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
