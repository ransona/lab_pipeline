from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step2.run_batch import run_step2_batch

step2_config = {}

step2_config["userID"] = "adamranson"
step2_config["expIDs"] = ["2026-05-11_03_ESRC033"]
step2_config["pre_secs"] = 5
step2_config["post_secs"] = 5
step2_config["run_bonvision"] = True
step2_config["run_s2p_timestamp"] = True
step2_config["run_ephys"] = True
step2_config["run_dlc_timestamp"] = True
step2_config["run_cuttraces"] = True

settings = {}
settings["neuropil_coeff"] = [0.7, 0.7]
settings["subtract_overall_frame"] = False
step2_config["settings"] = settings

run_step2_batch(step2_config)
