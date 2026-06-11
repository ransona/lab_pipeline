from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step1.run_batch import run_step1_batch_universal

step1_config = {}

step1_config["userID"] = "adamranson"
step1_config["expIDs"] = [
    "2026-05-25_23_ESYB040",
]

# For mesoscope data you can provide one default config for every P*/R* work unit.
step1_config["suite2p_config"] = {
    "default": {"config": "ch_1_depth_1.npy", "functional_chan": 1, "chan2_detection": "off"},
}

step1_config["runs2p"] = True
step1_config["rundlc"] = True
step1_config["runfitpupil"] = True
step1_config["queue"] = "debug"

run_step1_batch_universal(step1_config)
