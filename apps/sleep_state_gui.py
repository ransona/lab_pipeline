from pathlib import Path
import os
import runpy
import sys


APP_ROOT = Path(__file__).resolve().parents[1] / "src" / "preprocess_pipeline" / "viewers" / "external" / "sleep_state_gui"


def main() -> None:
    sys.path.insert(0, str(APP_ROOT))
    os.chdir(APP_ROOT)
    runpy.run_path(str(APP_ROOT / "sleep_state_gui.py"), run_name="__main__")


if __name__ == "__main__":
    main()
