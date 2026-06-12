import os
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _prepare_windows_qt_runtime() -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    exe_dir = Path(sys.executable).resolve().parent
    qt_plugin_root = exe_dir / "Library" / "lib" / "qt6" / "plugins"
    qt_platform_root = qt_plugin_root / "platforms"
    pyqt_plugin_root = exe_dir / "Lib" / "site-packages" / "PyQt6" / "Qt6" / "plugins"
    candidates = [
        exe_dir,
        exe_dir / "Library" / "bin",
        exe_dir / "Scripts",
        qt_plugin_root,
        qt_platform_root,
        pyqt_plugin_root,
    ]
    for path in candidates:
        if path.is_dir():
            os.add_dll_directory(str(path))
    if qt_plugin_root.is_dir():
        os.environ["QT_PLUGIN_PATH"] = str(qt_plugin_root)
    if qt_platform_root.is_dir():
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(qt_platform_root)


_prepare_windows_qt_runtime()

if __name__ == "__main__":
    try:
        from preprocess_pipeline.viewers.local_run import main
    except ModuleNotFoundError as exc:
        if exc.name == "PyQt6":
            raise SystemExit(
                "PyQt6 is not available in this environment. Launch local_run from an environment "
                "that has PyQt6 installed."
            )
        raise
    main()
