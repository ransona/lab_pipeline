from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step1.run_batch import run_step1_batch_universal

step1_config = {}

# Local examples are pinned to the lab default user.
step1_config["userID"] = "adamranson"
step1_config["expIDs"] = [
    "2026-06-11_02_ESYB190",
]

step1_config["local_raw_repository_root"] = r"F:\Local_Repository"
step1_config["local_processed_repository_root"] = r"F:\Local_Repository_Processed"
step1_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"
step1_config["suite2p_config_root"] = r"F:\s2p_ops"

# Use the Suite2p 1.1 environment for this compatibility branch.
step1_config["suite2p_env"] = "suite2p_1.1.0"

# Use one Suite2p config for every detected mesoscope P*/R* work unit.
step1_config["suite2p_config"] = {
    "default": {"config": "s2p_1_test.npy", "functional_chan": 1, "chan2_detection": "off"},
}

step1_config["runs2p"] = True
step1_config["rundlc"] = False
step1_config["runfitpupil"] = False

run_step1_batch_universal(step1_config)
