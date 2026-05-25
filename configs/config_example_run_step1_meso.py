step1_config = {}

step1_config["userID"] = "adamranson"
step1_config["expIDs"] = [
    "2026-04-10_09_TEST",
]

# For mesoscope data you can provide one default config for every P*/R* work unit.
step1_config["suite2p_config"] = {
    "default": "ch_1_depth_1.npy",
}

step1_config["runs2p"] = True
step1_config["rundlc"] = True
step1_config["runfitpupil"] = True
