from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step1.run_batch import run_step1_batch_universal

step1_config = {}

step1_config["userID"] = "adamranson"
step1_config["expIDs"] = [
    "2026-03-19_01_ESRC033",
]

# Reuse the successful dual-channel Suite2p config pair from the completed debug job.
step1_config["suite2p_config"] = [
    {"config": "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy", "functional_chan": 1, "chan2_detection": "off"},
    {"config": "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy", "functional_chan": 2, "chan2_detection": "off"},
]

step1_config["runs2p"] = True
step1_config["rundlc"] = True
step1_config["runfitpupil"] = True
step1_config["runsrdtrans"] = True
step1_config["srdtrans"] = {
    # The original denoising pipeline used /home/adamranson/data/srt_models and a
    # missing historical model name. The closest surviving generic GCaMP8 model
    # family is used here; patch sizes are auto-loaded from its para.yaml.
    "model_root": "/home/adamranson/data/srt_models",
    "model": "mixed_axon_soma_g8_202412022250",
    "gpu": "0,1",
    "channels": ["ch1"],
}
step1_config["queue"] = "debug"

run_step1_batch_universal(step1_config)
