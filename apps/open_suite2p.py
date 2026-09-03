"""Launch Suite2p's GUI directly into a processed experiment."""

import argparse
import getpass
from pathlib import Path


def _send_to_running_suite2p(stat_path: Path) -> bool:
    """Ask an existing Suite2p GUI for this user to load ``stat_path``."""
    from qtpy import QtCore, QtNetwork

    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    socket = QtNetwork.QLocalSocket()
    socket.connectToServer(f"suite2p-gui-{getpass.getuser()}")
    if not socket.waitForConnected(300):
        return False
    socket.write(f"{stat_path}\n".encode("utf-8"))
    socket.flush()
    if not socket.waitForBytesWritten(500):
        return False
    if not socket.waitForReadyRead(1000):
        return False
    response = bytes(socket.readAll()).decode("utf-8", errors="replace").strip()
    socket.disconnectFromServer()
    return response == "OK"


def main():
    parser = argparse.ArgumentParser(description="Open a Suite2p stat.npy file in the GUI.")
    parser.add_argument("stat_path", type=Path, help="Path to Suite2p stat.npy")
    args = parser.parse_args()
    stat_path = args.stat_path.expanduser().resolve()
    if stat_path.name != "stat.npy" or not stat_path.is_file():
        parser.error(f"Not a readable Suite2p stat.npy file: {stat_path}")

    if _send_to_running_suite2p(stat_path):
        return

    from suite2p import gui

    gui.run(statfile=str(stat_path))


if __name__ == "__main__":
    main()
