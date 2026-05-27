import importlib.util
import sys
import types
from pathlib import Path

from preprocess_pipeline.shared import paths


EYE_CHECK_REPO = Path("/home/adamranson/code/eye_check_py")
EYE_CHECK_ENTRYPOINT = EYE_CHECK_REPO / "eye_view_gui_editor.py"


def _compat_organise_paths_module():
    module = types.ModuleType("organise_paths")
    module.find_paths = paths.find_paths
    return module


def _load_eye_check_module():
    if not EYE_CHECK_ENTRYPOINT.exists():
        raise FileNotFoundError(
            f"Could not find eye_check_py entrypoint: {EYE_CHECK_ENTRYPOINT}"
        )

    sys.modules["organise_paths"] = _compat_organise_paths_module()

    spec = importlib.util.spec_from_file_location(
        "external_eye_check_py.eye_view_gui_editor",
        EYE_CHECK_ENTRYPOINT,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec from {EYE_CHECK_ENTRYPOINT}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def launch(user_id=None, exp_id=None):
    module = _load_eye_check_module()
    app = module.QApplication.instance()
    created_app = False
    if app is None:
        app = module.QApplication(sys.argv)
        created_app = True

    win = module.VideoAnalysisApp()
    if user_id:
        win.userIdEdit.setText(user_id)
    if exp_id:
        win.expIdEdit.setText(exp_id)
    win.show()

    if created_app:
        return app.exec_()
    return 0


def main():
    try:
        user_id = sys.argv[1]
        exp_id = sys.argv[2]
    except Exception:
        user_id = None
        exp_id = None
    raise SystemExit(launch(user_id=user_id, exp_id=exp_id))


if __name__ == "__main__":
    main()

