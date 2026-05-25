from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preprocess_pipeline.step1.split_combined_s2p import split_combined_suite2p


if __name__ == "__main__":
    split_combined_suite2p()
