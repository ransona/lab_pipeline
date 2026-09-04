"""Launch Suite2p's GUI directly into a processed experiment."""

import argparse
import getpass
from pathlib import Path


def _send_to_running_suite2p(stat_path: Path) -> bool:
    """Ask an existing Suite2p GUI for this user to load ``stat_path``.

    A successful connection identifies a live GUI control endpoint.  Do not
    wait for the GUI to finish loading and reply: that operation can take
    seconds and previously caused the launcher to start a duplicate instance.
    """
    from qtpy import QtCore, QtNetwork

    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    socket = QtNetwork.QLocalSocket()
    socket.connectToServer(f"suite2p-gui-{getpass.getuser()}")
    if not socket.waitForConnected(1000):
        return False
    request = f"{stat_path}\n".encode("utf-8")
    queued_bytes = socket.write(request)
    socket.flush()
    socket.disconnectFromServer()
    # A live endpoint has already accepted this local connection.  Some Qt
    # platform backends report waitForBytesWritten() as false while still
    # delivering the queued request; treating that as failure launched a
    # duplicate GUI even though the existing one loaded the experiment.
    return queued_bytes == len(request)


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
