from pathlib import Path
import getpass
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step1.run_batch import run_step1_batch_universal

step1_config = {}

# Set userID to the local OS username that owns the local repository tree.
step1_config["userID"] = getpass.getuser()
step1_config["expIDs"] = [
    "2025-10-30_10_ESYB025",
]

step1_config["local_raw_repository_root"] = r"D:\data\Repository"
step1_config["local_processed_repository_root"] = r"F:\Local_Repository_Processed"
step1_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"
step1_config["suite2p_config_root"] = r"F:\s2p_ops"

# Use the Suite2p 1.1 environment for this compatibility branch.
step1_config["suite2p_env"] = "suite2p_1.1.0"

# Use one Suite2p config for every detected mesoscope P*/R* work unit.
step1_config["suite2p_config"] = {
    "default": {"config": "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy", "functional_chan": 1},
}

step1_config["runs2p"] = True
step1_config["rundlc"] = False
step1_config["runfitpupil"] = False

run_step1_batch_universal(step1_config)
