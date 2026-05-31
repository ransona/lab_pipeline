from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step1.run_batch import run_step1_batch_universal

step1_config = {}

# Set userID to the local OS username that owns the local repository tree.
step1_config["userID"] = "adamranson"
step1_config["expIDs"] = [
    "2026-05-11_01_ESRC033",
]
step1_config["local_repository_root"] = r"D:\data\Repository"

step1_config["suite2p_config"] = [
    "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
    "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy",
]

step1_config["runs2p"] = True
step1_config["rundlc"] = False
step1_config["runfitpupil"] = False

run_step1_batch_universal(step1_config)
