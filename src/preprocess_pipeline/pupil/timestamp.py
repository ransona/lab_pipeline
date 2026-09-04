# take dlc pipil output and fits circle to pupil etc

import numpy as np
import os
import pickle
from preprocess_pipeline.shared import paths
from preprocess_pipeline.pupil import calibration

def preprocess_pupil_timestamp_run(userID, expID):
    print('** Starting preprocess_pupil_timestamp_run...')
    animalID, remote_repository_root, \
    processed_root, exp_dir_processed, \
        exp_dir_raw = paths.find_paths(userID, expID)
    exp_dir_processed_recordings = os.path.join(exp_dir_processed,'recordings')
    print('** Starting ' + expID)
    eye_outputs = [
        ('left', 'dlcEyeLeft.pickle', 'dlcEyeLeft_resampled.pickle'),
        ('right', 'dlcEyeRight.pickle', 'dlcEyeRight_resampled.pickle'),
    ]
    logged_frame_times_path = os.path.join(exp_dir_processed_recordings, 'eye_frame_times.npy')
    if not os.path.isfile(logged_frame_times_path):
        print('Skipping pupil timestamp processing: eye-camera frame timestamps are unavailable.')
        return False

    available_outputs = [
        output for output in eye_outputs
        if os.path.isfile(os.path.join(exp_dir_processed_recordings, output[1]))
    ]
    if not available_outputs:
        print(
            'Skipping pupil timestamp processing: no DLC pupil output was found '
            '(expected dlcEyeLeft.pickle and/or dlcEyeRight.pickle).'
        )
        return False

    # A failed/missing tracking pass for one eye should not discard usable
    # tracking from the other eye.
    for eye_name, input_filename, output_filename in eye_outputs:
        input_path = os.path.join(exp_dir_processed_recordings, input_filename)
        if not os.path.isfile(input_path):
            print(f'Skipping {eye_name}-eye pupil timestamp processing: {input_filename} was not found.')
            continue
        # load eyeDat which contains pupil position info derived from circles etc fit to dlc output
        with open(input_path, 'rb') as input_file:
            eyeDat = pickle.load(input_file)
        # store detected eye details with timeline timestamps
        # load video timestamps
        loggedFrameTimes = np.load(logged_frame_times_path)
        # resample to 10Hz constant rate
        newTimeVector = np.arange(round(loggedFrameTimes[0]), round(loggedFrameTimes[-1]), 0.1)
        frameVector = np.arange(0,len(eyeDat['x']))
        eyeDat2 = {}
        eyeDat2['t'] = newTimeVector
        eyeDat2['x'] = np.interp(newTimeVector, loggedFrameTimes, eyeDat['x'])
        eyeDat2['y'] = np.interp(newTimeVector, loggedFrameTimes, eyeDat['y'])
        eyeDat2['radius'] = np.interp(newTimeVector, loggedFrameTimes, eyeDat['radius'])
        eyeDat2['velocity'] = np.interp(newTimeVector, loggedFrameTimes, eyeDat['velocity'])
        eyeDat2['qc'] = np.interp(newTimeVector, loggedFrameTimes, eyeDat['qc'])
        eyeDat2['frame'] = np.round(np.interp(newTimeVector, loggedFrameTimes, frameVector))
        with open(os.path.join(exp_dir_processed_recordings, output_filename), "wb") as pickle_out:
            pickle.dump(eyeDat2, pickle_out)
        
    # check if there is a pix->degrees calibration file for the animal and if there is use it to convert
    # pupil xy position etc to degrees
    animal_processed_root = os.path.dirname(exp_dir_processed)
    if os.path.exists(os.path.join(animal_processed_root,'meta','eye_pix_angle_map.pickle')):
        # calibration exists so apply it
        print('Eye position calibration file found... applying calibration')
        calibration.apply_pupil_calib(userID,[expID]) 
    else:
        print('Warning: no eye position calibration file found')
    print()
    print('** Done without errors')
    return True

# for debugging:
def main():
    # userID = 'pmateosaparicio'
    # expIDs = [
    #     '2025-07-04_04_ESPM154',    # stim
    #     '2025-07-07_05_ESPM154',    # stim
    #     '2025-07-02_03_ESPM135',    # stim
    #     '2025-07-08_04_ESPM152',    # stim
    #     '2025-07-11_02_ESPM154',    # stim
    #     '2025-07-04_06_ESPM154',    # sleep
    #     '2025-07-07_06_ESPM154',    # sleep
    #     '2025-07-02_05_ESPM135',    # sleep
    #     '2025-07-08_05_ESPM152',    # sleep
    #     '2025-07-11_03_ESPM154']    # sleep

    # for expID in expIDs:
    #     preprocess_pupil_timestamp_run(userID, expID) 

    # # experiment lists
    allExpIDs = ['2025-11-28_02_ESRC026']
    userID = 'rubencorreia'

    # allExpIDs_sleep = [
    #     '2025-07-04_06_ESPM154',
    #     '2025-07-07_06_ESPM154',
    #     '2025-07-11_03_ESPM154',    

    for expID in allExpIDs:
        preprocess_pupil_timestamp_run(userID, expID)   


if __name__ == "__main__":
    main()
