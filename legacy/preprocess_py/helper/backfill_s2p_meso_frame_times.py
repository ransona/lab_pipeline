import argparse
import os

import numpy as np
from scipy.io import loadmat

import organise_paths


def save_plane_timing_outputs(plane_dir, frame_times, frame_start_times, output_times):
    np.save(os.path.join(plane_dir, 'timeline_frame_times.npy'), np.asarray(frame_times))
    np.save(os.path.join(plane_dir, 'timeline_frame_start_times.npy'), np.asarray(frame_start_times))
    np.save(os.path.join(plane_dir, 'timeline_output_times.npy'), np.asarray(output_times))


def run_backfill_s2p_meso_frame_times(userID, expID, resampleFreq=30, debug_mode=False):
    animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw = organise_paths.find_paths(userID, expID)

    if debug_mode:
        exp_dir_raw = '/home/adamranson/data/tif_meso/local_repository/ESMT204/2025-03-05_02_ESMT204'
        exp_dir_processed = '/home/adamranson/data/tif_meso/processed_repository/ESMT204/2025-03-05_02_ESMT204'

    timeline = loadmat(os.path.join(exp_dir_raw, expID + '_Timeline.mat'))
    timeline = timeline['timelineSession']
    tl_chNames = timeline['chNames'][0][0][0][0:]
    tl_daqData = timeline['daqData'][0, 0]
    tl_time = timeline['time'][0][0]

    scanpath_names = []
    for i in range(10):
        path = os.path.join(exp_dir_processed, 'P' + str(i))
        if os.path.exists(path):
            scanpath_names.append(path)

    for scanpath_path in scanpath_names:
        scanpath_name = os.path.basename(scanpath_path)
        roi_folders = sorted([f for f in os.listdir(scanpath_path) if os.path.isdir(os.path.join(scanpath_path, f))])

        if scanpath_name == 'P1':
            neuralFramesIdx = np.where(np.isin(tl_chNames, 'MicroscopeFrames'))[0][0]
        elif scanpath_name == 'P2':
            neuralFramesIdx = np.where(np.isin(tl_chNames, 'MicroscopeFrames2'))[0][0]
        else:
            raise Exception('Error: more than 2 scan paths - please check')

        neuralFramesPulses = np.squeeze((tl_daqData[:, neuralFramesIdx] > 1).astype(int))
        frameTimes = np.squeeze(tl_time)[np.where(np.diff(neuralFramesPulses) == 1)[0]]

        for roi_folder in roi_folders:
            roi_path = os.path.join(scanpath_path, roi_folder)
            if os.path.exists(os.path.join(roi_path, 'ch2')):
                dataPath = [os.path.join(roi_path, 'suite2p'),
                            os.path.join(roi_path, 'ch2', 'suite2p')]
            else:
                dataPath = [os.path.join(roi_path, 'suite2p')]

            depthCount = len([d for d in os.listdir(dataPath[0]) if "plane" in d])
            framePulsesPerDepth = len(frameTimes) / depthCount
            outputTimes = np.arange(frameTimes[0] + 1, frameTimes[-1] - 1, 1 / resampleFreq)

            for iCh in range(len(dataPath)):
                for iDepth in range(depthCount):
                    plane_dir = os.path.join(dataPath[iCh], 'plane' + str(iDepth))
                    if os.path.exists(os.path.join(plane_dir, 'F_big.npy')):
                        fall = np.load(os.path.join(plane_dir, 'F_big.npy'))
                    else:
                        fall = np.load(os.path.join(plane_dir, 'F.npy'))

                    if abs(framePulsesPerDepth - fall.shape[1]) / max([framePulsesPerDepth, fall.shape[1]]) > 0.015:
                        pcDiff = round(abs(framePulsesPerDepth - fall.shape[1]) / max([framePulsesPerDepth, fall.shape[1]]) * 100)
                        raise Exception('There is a mismatch between between frames trigs and frames in tiff - ' + str(pcDiff) + '% difference')

                    depthFrameTimes = frameTimes[iDepth:len(frameTimes):depthCount]
                    min_frame_count = min(fall.shape[1], len(depthFrameTimes))
                    depthFrameTimes = depthFrameTimes[:min_frame_count]

                    save_plane_timing_outputs(plane_dir, depthFrameTimes, depthFrameTimes, outputTimes)


def main():
    parser = argparse.ArgumentParser(description='Backfill Suite2p frame timing files for mesoscope experiments.')
    parser.add_argument('--userID', required=True)
    parser.add_argument('--expID', required=True)
    parser.add_argument('--resample-freq', type=float, default=30)
    parser.add_argument('--debug-mode', action='store_true')
    args = parser.parse_args()
    run_backfill_s2p_meso_frame_times(args.userID, args.expID, resampleFreq=args.resample_freq, debug_mode=args.debug_mode)


if __name__ == '__main__':
    main()
