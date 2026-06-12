# step two takes checked suite2p and DLC output, and other experiment data 
# and gets it all ready for further analysis with:
# 1) finding when stims come on etc in tl time
# 2) finding ca imaging frame times in tl time
# 3) getting ephys data ready to use
# 4) getting DLC data ready to use
# 5) cutting traces from ca, dlc, and ephys into trials

import os
import sys

from preprocess_pipeline.shared import paths
from preprocess_pipeline.behavior import (
    bonvision,
    preprocess_cam,
    preprocess_cut,
    preprocess_ephys,
)
from preprocess_pipeline.pupil import timestamp as preprocess_pupil_timestamp
from preprocess_pipeline.suite2p import preprocess as preprocess_s2p

def run_preprocess_step2(userID, expID, pre_secs, post_secs, run_bonvision, run_s2p_timestamp, run_ephys, run_dlc_timestamp, run_cuttraces): 
    animalID, remote_repository_root, \
        processed_root, exp_dir_processed, \
            exp_dir_raw = paths.find_paths(userID, expID)

    # make folder to store recordings after processing if needed
    exp_dir_processed_recordings = os.path.join(exp_dir_processed,'recordings')
    if not os.path.exists(exp_dir_processed_recordings):
        os.makedirs(exp_dir_processed_recordings, exist_ok = True)

    if run_bonvision:
        ###########################################################
        # Process bv data
        ###########################################################
        # process bonvision related data, this includes relating bon vision time to TL time and wheel data
        print('** Starting bonvision section...')
        bonvision.run_preprocess_bonvision(userID, expID)
        

    if run_s2p_timestamp:
        ###########################################################
        # Process S2P data
        ###########################################################
        print('** Starting S2P section...')
        preprocess_s2p.run_preprocess_s2p_universal(userID, expID)

    if run_ephys:
        ###########################################################
        # Process ephys data
        ###########################################################
        print('** Starting ephys section...')
        preprocess_ephys.run_preprocess_ephys(userID, expID)

    if run_dlc_timestamp:
        ###########################################################
        # Process DLC data (timestamping)
        ###########################################################
        print('** Starting dlc timestamp section...')
        preprocess_cam.preprocess_cam_run(userID, expID)
        preprocess_pupil_timestamp.preprocess_pupil_timestamp_run(userID, expID)

    if run_cuttraces:
        ####################################################
        ### cut up ephys, eye, and ca traces into trials ###
        ####################################################
        print('** Starting trail cutting section...')
        preprocess_cut.run_preprocess_cut(userID, expID, pre_secs, post_secs)


def main():
    if len(sys.argv) == 10:
        run_preprocess_step2(
            sys.argv[1],
            sys.argv[2],
            float(sys.argv[3]),
            float(sys.argv[4]),
            sys.argv[5].lower() == 'true',
            sys.argv[6].lower() == 'true',
            sys.argv[7].lower() == 'true',
            sys.argv[8].lower() == 'true',
            sys.argv[9].lower() == 'true',
        )
        return

    userID = 'adamranson'
    expID = '2025-04-10_26_TEST'
    run_preprocess_step2(userID, expID, 5, 5, True, True, True, True, True)


if __name__ == "__main__":
    main()
        
