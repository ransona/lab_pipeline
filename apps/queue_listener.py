from pathlib import Path
import runpy
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


if __name__ == "__main__":
    runpy.run_module("preprocess_pipeline.queue.listener", run_name="__main__")
