from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step1.run_batch import run_step1_batch_universal

step1_config = {}

# userID selects user-specific Suite2p ops/configs; processed output stays under animalID/expID.
step1_config["userID"] = "adamranson"
step1_config["expIDs"] = [
    "2026-05-17_02_ESYB040",
]
step1_config["local_raw_repository_root"] = r"D:\data\Repository"
step1_config["local_processed_repository_root"] = r"F:\Local_Repository_Processed"
step1_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"
step1_config["suite2p_config_root"] = r"F:\s2p_ops"

# Use the Suite2p 1.1 environment for this compatibility branch.
step1_config["suite2p_env"] = "suite2p_1.1.0"

step1_config["suite2p_config"] = {
    "config": "test1.npy",
    "functional_chan": 1,
    "chan2_detection": "off",
}

step1_config["runs2p"] = True
step1_config["rundlc"] = False
step1_config["runfitpupil"] = False

run_step1_batch_universal(step1_config)
