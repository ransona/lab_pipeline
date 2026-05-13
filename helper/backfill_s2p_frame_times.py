import argparse
import os

import numpy as np
from scipy.io import loadmat

import organise_paths


def save_plane_timing_outputs(plane_dir, frame_times, frame_start_times, output_times):
    np.save(os.path.join(plane_dir, 'timeline_frame_times.npy'), np.asarray(frame_times))
    np.save(os.path.join(plane_dir, 'timeline_frame_start_times.npy'), np.asarray(frame_start_times))
    np.save(os.path.join(plane_dir, 'timeline_output_times.npy'), np.asarray(output_times))


def run_backfill_s2p_frame_times(userID, expID, resampleFreq=30):
    animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw = organise_paths.find_paths(userID, expID)

    timeline = loadmat(os.path.join(exp_dir_raw, expID + '_Timeline.mat'))
    timeline = timeline['timelineSession']
    tl_chNames = timeline['chNames'][0][0][0][0:]
    tl_daqData = timeline['daqData'][0, 0]
    tl_time = timeline['time'][0][0]

    if os.path.exists(os.path.join(exp_dir_processed, 'ch2')):
        dataPath = [os.path.join(exp_dir_processed, 'suite2p'),
                    os.path.join(exp_dir_processed, 'ch2', 'suite2p')]
    else:
        dataPath = [os.path.join(exp_dir_processed, 'suite2p')]

    depthCount = len([d for d in os.listdir(dataPath[0]) if "plane" in d])

    neuralFramesIdx = np.where(np.isin(tl_chNames, 'MicroscopeFrames'))[0][0]
    neuralFramesPulses = np.squeeze((tl_daqData[:, neuralFramesIdx] > 1).astype(int))

    frameTimes = np.squeeze(tl_time)[np.where(np.diff(neuralFramesPulses) == 1)[0]]
    frame_start_times = frameTimes.copy()
    time_diffs = np.append(np.diff(frameTimes), np.diff(frameTimes)[-1])
    frameTimes = frameTimes + (time_diffs / 2)

    framePulsesPerDepth = len(frameTimes) / depthCount
    outputTimes = np.arange(frameTimes[0] + 1, frameTimes[-1] - 1, 1 / resampleFreq)

    for iCh in range(len(dataPath)):
        for iDepth in range(depthCount):
            plane_dir = os.path.join(dataPath[iCh], 'plane' + str(iDepth))
            fall = np.load(os.path.join(plane_dir, 'F.npy'))
            if abs(framePulsesPerDepth - fall.shape[1]) / max([framePulsesPerDepth, fall.shape[1]]) > 0.01:
                pcDiff = round(abs(framePulsesPerDepth - fall.shape[1]) / max([framePulsesPerDepth, fall.shape[1]]) * 100)
                raise Exception('There is a mismatch between between frames trigs and frames in tiff - ' + str(pcDiff) + '% difference')

            depthFrameTimes = frameTimes[iDepth:len(frameTimes):depthCount]
            depth_frame_start_times = frame_start_times[iDepth:len(frame_start_times):depthCount]
            min_frame_count = min(fall.shape[1], len(depthFrameTimes))

            depthFrameTimes = depthFrameTimes[:min_frame_count]
            depth_frame_start_times = depth_frame_start_times[:min_frame_count]

            save_plane_timing_outputs(plane_dir, depthFrameTimes, depth_frame_start_times, outputTimes)


def main():
    parser = argparse.ArgumentParser(description='Backfill Suite2p frame timing files for standard experiments.')
    parser.add_argument('--userID', required=True)
    parser.add_argument('--expID', required=True)
    parser.add_argument('--resample-freq', type=float, default=30)
    args = parser.parse_args()
    run_backfill_s2p_frame_times(args.userID, args.expID, resampleFreq=args.resample_freq)


if __name__ == '__main__':
    main()
