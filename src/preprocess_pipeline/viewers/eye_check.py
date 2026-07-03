import importlib.util
import sys
from pathlib import Path

EYE_CHECK_ROOT = Path(__file__).resolve().parent / "external" / "eye_check_py"
EYE_CHECK_ENTRYPOINT = EYE_CHECK_ROOT / "eye_view_gui_editor.py"


def _load_eye_check_module():
    if not EYE_CHECK_ENTRYPOINT.exists():
        raise FileNotFoundError(
            f"Could not find vendored eye-check entrypoint: {EYE_CHECK_ENTRYPOINT}"
        )

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
        return app.exec()
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
