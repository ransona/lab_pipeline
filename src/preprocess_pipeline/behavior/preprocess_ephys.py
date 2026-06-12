import os
import numpy as np
from scipy.io import loadmat
from preprocess_pipeline.shared import paths

def run_preprocess_ephys(userID, expID):
    print('Starting run_preprocess_ephys...')
    animalID, remote_repository_root, \
    processed_root, exp_dir_processed, \
        exp_dir_raw = paths.find_paths(userID, expID)
    exp_dir_processed_recordings = os.path.join(exp_dir_processed,'recordings')
    os.makedirs(exp_dir_processed_recordings, exist_ok=True)

    # load the stimulus parameter file produced by matlab by the bGUI
    # this includes stim parameters and stimulus order
    try:
        stim_params = loadmat(paths.raw_file_path(userID, expID, expID + '_stim.mat', exp_dir_raw=exp_dir_raw))
    except:
        raise Exception('Stimulus parameter file not found - this experiment was probably from pre-Dec 2021.')
    # load timeline
    Timeline = loadmat(paths.raw_file_path(userID, expID, expID + '_Timeline.mat', exp_dir_raw=exp_dir_raw))
    Timeline = Timeline['timelineSession']
    # get timeline file in a usable format after importing to python
    tl_chNames = Timeline['chNames'][0][0][0][0:]
    tl_daqData = Timeline['daqData'][0,0]
    tl_time    = Timeline['time'][0][0]

    ePhys1Idx = np.where(np.isin(tl_chNames, 'EPhys1'))
    ePhys2Idx = np.where(np.isin(tl_chNames, 'EPhys2'))
    ePhys1Data = np.squeeze(tl_daqData[:, ePhys1Idx])[np.newaxis,:]
    ePhys2Data = np.squeeze(tl_daqData[:, ePhys2Idx])[np.newaxis,:]
    ephys_combined = np.concatenate((tl_time,ePhys1Data,ePhys2Data),axis=0)
    np.save(os.path.join(exp_dir_processed_recordings,'ephys.npy'),ephys_combined)
    print('Done without errors')


def main():
    userID = 'adamranson'
    expID = '2025-04-10_26_TEST'
    run_preprocess_ephys(userID, expID)


if __name__ == "__main__":
    main()
