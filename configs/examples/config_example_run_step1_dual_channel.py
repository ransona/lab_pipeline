from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step1.run_batch import run_step1_batch_universal

step1_config = {}

step1_config["userID"] = "adamranson"
step1_config["expIDs"] = [
    "2026-05-11_03_ESRC033",
]

# Two configs trigger the shared-registration dual-channel path:
# - config 1 drives registration and green extraction
# - config 2 drives red extraction into ch2/
step1_config["suite2p_config"] = [
    "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
    "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy",
]

step1_config["runs2p"] = True
step1_config["rundlc"] = True
step1_config["runfitpupil"] = True

run_step1_batch_universal(step1_config)
