from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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
