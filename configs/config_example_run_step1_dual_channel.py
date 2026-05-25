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

# Optional fields:
# step1_config["runhabituate"] = False
# step1_config["jump_queue"] = False
# step1_config["run_on"] = "server"
# step1_config["suite2p_env"] = "suite2p"
