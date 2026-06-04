from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from preprocess_pipeline.srdtrans.build_model import run_subcommand_from_config


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: srdtrans_build.py <register|extract|build> <build_config.json>")
    run_subcommand_from_config(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
