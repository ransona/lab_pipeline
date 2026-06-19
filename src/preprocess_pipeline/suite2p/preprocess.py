import gc
import os
import pickle
from collections import defaultdict

import numpy as np
from scipy import signal
from scipy.io import loadmat
from tqdm import tqdm

from preprocess_pipeline.shared import paths


def save_plane_timing_outputs(plane_dir, frame_times, frame_start_times, output_times):
    np.save(os.path.join(plane_dir, "timeline_frame_times.npy"), np.asarray(frame_times))
    np.save(os.path.join(plane_dir, "timeline_frame_start_times.npy"), np.asarray(frame_start_times))
    np.save(os.path.join(plane_dir, "timeline_output_times.npy"), np.asarray(output_times))


def nested_dict():
    return defaultdict(nested_dict)


def to_regular_dict(value):
    if isinstance(value, defaultdict):
        return {key: to_regular_dict(subvalue) for key, subvalue in value.items()}
    return value


def discover_work_units(exp_dir_processed):
    """Return normalized Suite2p work units for standard or mesoscope topology."""
    meso_units = []
    for p_index in range(10):
        scanpath_root = os.path.join(exp_dir_processed, f"P{p_index}")
        if not os.path.isdir(scanpath_root):
            continue
        if p_index not in (1, 2):
            raise Exception(
                f"Universal pipeline currently supports only P1/P2 mesoscope scanpaths, found P{p_index}"
            )
        roi_names = sorted(
            roi_name
            for roi_name in os.listdir(scanpath_root)
            if os.path.isdir(os.path.join(scanpath_root, roi_name)) and roi_name.startswith("R")
        )
        if not roi_names:
            continue
        for roi_name in roi_names:
            roi_root = os.path.join(scanpath_root, roi_name)
            meso_units.append(
                {
                    "mode": "meso",
                    "root": roi_root,
                    "scanpath_name": f"P{p_index}",
                    "scanpath_label": p_index,
                    "roi_name": roi_name,
                    "roi_label": int(roi_name[1:]) if roi_name[1:].isdigit() else roi_name,
                }
            )

    if meso_units:
        return meso_units

    return [
        {
            "mode": "standard",
            "root": exp_dir_processed,
            "scanpath_name": None,
            "scanpath_label": None,
            "roi_name": None,
            "roi_label": None,
        }
    ]


def get_channel_suite2p_roots(work_unit_root):
    suite2p_roots = [os.path.join(work_unit_root, "suite2p")]
    ch2_root = os.path.join(work_unit_root, "ch2", "suite2p")
    if os.path.exists(ch2_root):
        suite2p_roots.append(ch2_root)
    return suite2p_roots


def get_frame_channel_name(work_unit):
    if work_unit["mode"] == "standard":
        return "MicroscopeFrames"
    if work_unit["scanpath_name"] == "P1":
        return "MicroscopeFrames"
    if work_unit["scanpath_name"] == "P2":
        return "MicroscopeFrames2"
    raise Exception(
        f"Unsupported mesoscope scan path for frame timing: {work_unit['scanpath_name']}"
    )


def build_metadata_storage(mode):
    if mode == "meso":
        return nested_dict()
    return {}


def store_spatial_metadata(container, work_unit, depth, value):
    if work_unit["mode"] == "meso":
        container[work_unit["scanpath_label"]][work_unit["roi_label"]][depth] = value
    else:
        container[depth] = value


def efficient_causal_sliding_percentile_2d(data, window, step=1, percentile=20):
    neurons, total_time = data.shape
    idx = np.arange(window - 1, total_time, step)
    start_idx = idx - window + 1
    valid = start_idx >= 0
    idx = idx[valid]
    start_idx = start_idx[valid]

    baseline = np.zeros_like(data)
    for neuron_idx in tqdm(range(neurons), desc="Computing baselines"):
        windows = np.array([data[neuron_idx, i : j + 1] for i, j in zip(start_idx, idx)])
        percentile_values = np.percentile(windows, percentile, axis=1)
        baseline[neuron_idx] = np.interp(np.arange(total_time), idx, percentile_values)

    return baseline


def resample_previous(values, sample_times, output_times):
    sample_times = np.asarray(sample_times)
    output_times = np.asarray(output_times)
    idx = np.searchsorted(sample_times, output_times, side="right") - 1
    idx = np.clip(idx, 0, len(sample_times) - 1)
    return values[:, idx]


def append_cell_metadata(store, channel_index, key, values):
    if channel_index not in store:
        store[channel_index] = [values]
    else:
        store[channel_index].append(values)


def run_preprocess_s2p_universal(userID, expID, neuropil_coeff_config=np.nan):
    (
        animalID,
        remote_repository_root,
        processed_root,
        exp_dir_processed,
        exp_dir_raw,
    ) = paths.find_paths(userID, expID)
    exp_dir_processed_recordings = os.path.join(exp_dir_processed, "recordings")

    try:
        with open(os.path.join(exp_dir_processed, "step2_config.pickle"), "rb") as file:
            step2_config = pickle.load(file)
    except Exception:
        step2_config = {}

    timeline = loadmat(paths.raw_file_path(userID, expID, expID + "_Timeline.mat", exp_dir_raw=exp_dir_raw))["timelineSession"]
    tl_ch_names = timeline["chNames"][0][0][0][0:]
    tl_daq_data = timeline["daqData"][0, 0]
    tl_time = timeline["time"][0][0]

    resample_freq = 30

    subtract_overall_frame = step2_config.get("settings", {}).get("subtract_overall_frame")
    if subtract_overall_frame is None:
        subtract_overall_frame = False

    if neuropil_coeff_config is not np.nan:
        neuropil_weight = neuropil_coeff_config
    else:
        neuropil_coeff_config = step2_config.get("settings", {}).get("neuropil_coeff")
        if neuropil_coeff_config is None:
            neuropil_weight = [0.7, 0.7]
        elif isinstance(neuropil_coeff_config, float):
            neuropil_weight = [neuropil_coeff_config, neuropil_coeff_config]
        elif isinstance(neuropil_coeff_config, (list, tuple)):
            if len(neuropil_coeff_config) == 1:
                neuropil_weight = [neuropil_coeff_config[0], neuropil_coeff_config[0]]
            else:
                neuropil_weight = list(neuropil_coeff_config[:2])
        else:
            raise TypeError("Unexpected type for neuropil_coeff_config. Expected float, list, or tuple.")

    work_units = discover_work_units(exp_dir_processed)
    mode = work_units[0]["mode"]

    alldF = {}
    all_baseline = {}
    allF = {}
    all_spikes = {}
    all_tokenised_dF_spikes = {}
    all_depths = {}
    all_original_suite2p_cell_ids = {}
    all_scanpaths = {}
    all_si_rois = {}
    all_roi_pix = {}
    all_roi_maps = {}
    all_fov = {}

    max_channel_count = max(len(get_channel_suite2p_roots(work_unit["root"])) for work_unit in work_units)
    for channel_index in range(max_channel_count):
        alldF[channel_index] = []
        all_baseline[channel_index] = []
        allF[channel_index] = []
        all_spikes[channel_index] = []
        all_tokenised_dF_spikes[channel_index] = []
        all_depths[channel_index] = []
        all_original_suite2p_cell_ids[channel_index] = []
        if mode == "meso":
            all_scanpaths[channel_index] = []
            all_si_rois[channel_index] = []
        all_roi_pix[channel_index] = build_metadata_storage(mode)
        all_roi_maps[channel_index] = build_metadata_storage(mode)
        all_fov[channel_index] = build_metadata_storage(mode)

    output_times_common = None
    accumulated_rois = {channel_index: 0 for channel_index in range(max_channel_count)}

    for work_unit in work_units:
        data_paths = get_channel_suite2p_roots(work_unit["root"])
        depth_count = len([name for name in os.listdir(data_paths[0]) if "plane" in name])

        neural_frames_idx = np.where(np.isin(tl_ch_names, get_frame_channel_name(work_unit)))[0][0]
        neural_frames_pulses = np.squeeze((tl_daq_data[:, neural_frames_idx] > 1).astype(int))

        frame_times = np.squeeze(tl_time)[np.where(np.diff(neural_frames_pulses) == 1)[0]]
        frame_start_times = frame_times.copy()
        time_diffs = np.append(np.diff(frame_times), np.diff(frame_times)[-1])
        frame_times = frame_times + (time_diffs / 2)

        frame_pulses_per_depth = len(frame_times) / depth_count
        frame_rate = 1 / np.median(np.diff(frame_times))
        frame_rate_per_plane = frame_rate / depth_count
        frame_duration = np.median(time_diffs)
        output_times = np.arange(frame_times[0] + 1, frame_times[-1] - 1, 1 / resample_freq)
        if output_times_common is None:
            output_times_common = output_times.copy()
        elif len(output_times) != len(output_times_common) or not np.allclose(
            output_times, output_times_common
        ):
            print(
                "Warning: work unit output_times differs from canonical experiment timebase; "
                "resampling onto output_times_common from first work unit."
            )

        for iCh in range(len(data_paths)):
            for iDepth in range(depth_count):
                print(f"Starting {work_unit['root']} Ch{iCh} Depth {iDepth}")

                plane_dir = os.path.join(data_paths[iCh], f"plane{iDepth}")
                Fall = np.load(os.path.join(plane_dir, "F.npy"))
                Fneu = np.load(os.path.join(plane_dir, "Fneu.npy"))
                spks = np.load(os.path.join(plane_dir, "spks.npy"))
                s2p_stat = np.load(os.path.join(plane_dir, "stat.npy"), allow_pickle=True)
                s2p_ops = np.load(os.path.join(plane_dir, "ops.npy"), allow_pickle=True).item()
                print("Frames = " + str(Fall.shape[1]))
                print("Time pulses = " + str(frame_pulses_per_depth))
                if abs(frame_pulses_per_depth - Fall.shape[1]) / max([frame_pulses_per_depth, Fall.shape[1]]) > 0.01:
                    pc_diff = round(
                        abs(frame_pulses_per_depth - Fall.shape[1]) / max([frame_pulses_per_depth, Fall.shape[1]]) * 100
                    )
                    raise Exception(
                        "There is a mismatch between between frames trigs and frames in tiff - "
                        + str(pc_diff)
                        + "% difference"
                    )

                cell_valid = np.load(os.path.join(plane_dir, "iscell.npy"))[:, 0]

                if Fneu.shape[0] == 0:
                    mean_frame_timecourse = np.zeros([1, Fall.shape[0]])
                else:
                    mean_frame_timecourse = np.median(Fneu, 0)
                    mean_frame_timecourse = mean_frame_timecourse - min(mean_frame_timecourse)

                zero_rois = ((np.max(Fall, axis=1) == 0) & (np.min(Fall, axis=1) == 0)).astype(int)
                if np.sum(zero_rois) > 0:
                    print("Warning: " + str(np.sum(zero_rois)) + " zero flat lined rois...")
                    cell_valid[np.where(zero_rois == 1)] = 0

                total_merges = 0
                for iCell in range(len(s2p_stat)):
                    if "ismerge" in s2p_stat[iCell] and s2p_stat[iCell]["inmerge"] == 1:
                        cell_valid[iCell] = 0
                        total_merges = total_merges + 1
                if total_merges > 0:
                    print(f"Merges found: {total_merges}")

                valid_cell_ids = np.where(cell_valid == 1)[0]
                xpix, ypix = [], []
                for iCell in range(len(valid_cell_ids)):
                    current_cell = valid_cell_ids[iCell]
                    xpix.append(s2p_stat[current_cell]["xpix"])
                    ypix.append(s2p_stat[current_cell]["ypix"])

                depth_frame_times = frame_times[iDepth : len(frame_times) : depth_count]
                depth_frame_start_times = frame_start_times[iDepth : len(frame_start_times) : depth_count]
                next_depth_frame_times = depth_frame_start_times + frame_duration
                min_frame_count = min(Fall.shape[1], len(depth_frame_times))
                if Fall.shape[1] < len(depth_frame_times):
                    print(
                        "Warning: less frames in tif than frame triggers, diff = "
                        + str(len(depth_frame_times) - Fall.shape[1])
                    )
                elif Fall.shape[1] > len(depth_frame_times):
                    print(
                        "Warning: less frame triggers than frames in tif, diff = "
                        + str(Fall.shape[1] - len(depth_frame_times))
                    )

                depth_frame_times = depth_frame_times[:min_frame_count]
                depth_frame_start_times = depth_frame_start_times[:min_frame_count]
                next_depth_frame_times = next_depth_frame_times[:min_frame_count]
                save_plane_timing_outputs(
                    plane_dir, depth_frame_times, depth_frame_start_times, output_times_common
                )

                if len(valid_cell_ids) == 0:
                    print("No valid cells after Suite2p filtering; storing empty outputs for this plane.")
                    roi_pix = []
                    roi_map = np.zeros(np.shape(s2p_ops["meanImg"]))
                    store_spatial_metadata(all_roi_pix[iCh], work_unit, iDepth, roi_pix)
                    store_spatial_metadata(all_roi_maps[iCh], work_unit, iDepth, roi_map)
                    store_spatial_metadata(all_fov[iCh], work_unit, iDepth, s2p_ops["meanImg"])
                    continue

                if sum(cell_valid) > 1:
                    Fneu_valid = np.squeeze(Fneu[np.where(cell_valid == 1), :])
                    F_valid = np.squeeze(Fall[np.where(cell_valid == 1), :])
                    Spks_valid = np.squeeze(spks[np.where(cell_valid == 1), :])
                else:
                    Fneu_valid = np.squeeze(Fneu[np.where(cell_valid == 1), :])
                    F_valid = np.squeeze(Fall[np.where(cell_valid == 1), :])
                    Spks_valid = np.squeeze(spks[np.where(cell_valid == 1), :])
                    Fneu_valid = Fneu_valid[np.newaxis, :]
                    F_valid = F_valid[np.newaxis, :]
                    Spks_valid = Spks_valid[np.newaxis, :]

                if subtract_overall_frame:
                    Fneu_valid = Fneu_valid - np.tile(mean_frame_timecourse, (Fneu_valid.shape[0], 1))
                    F_valid = F_valid - np.tile(mean_frame_timecourse, (F_valid.shape[0], 1))

                f_mins = np.min(F_valid, axis=1)
                f_mins_neuropil = np.min(Fneu_valid, axis=1)
                min_all_rois = np.min([np.min(f_mins), np.min(f_mins_neuropil)])
                if min_all_rois < 20:
                    offset_value = min_all_rois * -1 + 20
                    F_valid = F_valid + offset_value
                    Fneu_valid = Fneu_valid + offset_value
                    print("Offsetting all F and neuropil by", offset_value, "to ensure min > 20")

                print("Subtracting neuropil with weight", neuropil_weight[iCh])
                F_valid = F_valid - (Fneu_valid * neuropil_weight[iCh])
                print("Done neuropil subtraction.")

                f_mins = np.min(F_valid, axis=1)
                if np.min(f_mins) < 20:
                    print("Frame mean and neuropil subtraction give ROIs with F < 20")
                    print("Offsetting all F by", (np.min(f_mins) * -1) + 20)
                    F_valid = F_valid + (np.min(f_mins) * -1) + 20

                print("Creating ROI map...")
                roi_pix = []
                roi_map = np.zeros(np.shape(s2p_ops["meanImg"]))
                for iRoi in range(F_valid.shape[0]):
                    roi_pix.append(np.ravel_multi_index((ypix[iRoi], xpix[iRoi]), np.shape(s2p_ops["meanImg"])))
                    roi_map[ypix[iRoi], xpix[iRoi]] = iRoi + 1
                print("ROI map created.")

                print("Calculating dF/F baseline...")
                smoothing_window_size = round(1 * frame_rate_per_plane)
                baseline_window_size = round(30 * frame_rate_per_plane)
                kernel = np.ones((1, smoothing_window_size)) / smoothing_window_size
                smoothed = signal.convolve2d(F_valid, kernel, mode="same")
                smoothed[:, :smoothing_window_size] = np.tile(
                    smoothed[:, smoothing_window_size + 1].reshape(smoothed.shape[0], 1),
                    [1, smoothing_window_size],
                )
                smoothed[:, -smoothing_window_size:] = np.tile(
                    smoothed[:, -smoothing_window_size - 1].reshape(smoothed.shape[0], 1),
                    [1, smoothing_window_size],
                )
                smoothed[np.isnan(smoothed)] = np.max(smoothed) * 2
                percentile_window_step_size_secs = 10
                percentile_window_step_size_samples = round(percentile_window_step_size_secs * frame_rate_per_plane)
                baseline = efficient_causal_sliding_percentile_2d(
                    data=smoothed,
                    window=baseline_window_size,
                    step=percentile_window_step_size_samples,
                    percentile=10,
                )
                print("dF/F baseline calculated.")

                print("Calculating dF/F...")
                dF = (F_valid - baseline) / baseline
                dF_spikes = Spks_valid / baseline
                print("dF/F calculated.")
                dF = dF[:, :min_frame_count]
                dF_spikes = dF_spikes[:, :min_frame_count]
                F_valid = F_valid[:, :min_frame_count]
                baseline = baseline[:, :min_frame_count]

                print("Resampling to desired output frequency...")
                dF_resampled = resample_previous(dF, depth_frame_times, output_times_common)
                F_resampled = resample_previous(F_valid, depth_frame_times, output_times_common)
                Spks_resampled = resample_previous(dF_spikes, depth_frame_times, output_times_common)
                Baseline_resampled = resample_previous(
                    baseline, depth_frame_times, output_times_common
                )
                print("Resampling complete.")

                if len(dF_resampled.shape) == 1:
                    dF_resampled = dF_resampled[np.newaxis, :]
                    F_resampled = F_resampled[np.newaxis, :]
                    Spks_resampled = Spks_resampled[np.newaxis, :]
                    Baseline_resampled = Baseline_resampled[np.newaxis, :]

                print("Constructing tokenised neural activity matrix.")
                n_cells, n_timepoints = dF_spikes.shape
                frame_height = np.shape(s2p_ops["meanImg"])[0]
                y_coords = np.array([np.median(ypix[i]) for i in range(len(ypix))])
                fraction = y_coords / frame_height
                time_deltas = next_depth_frame_times - depth_frame_start_times
                sample_times = depth_frame_start_times[None, :] + fraction[:, None] * time_deltas[None, :]

                cell_ids = np.repeat(np.arange(n_cells), n_timepoints)
                cell_ids = cell_ids + accumulated_rois[iCh]
                accumulated_rois[iCh] = accumulated_rois[iCh] + n_cells
                sample_times_flat = sample_times.flatten()
                activity_flat_dF_spikes = dF_spikes.flatten()
                tokenised_dF_spikes = np.stack((cell_ids, sample_times_flat, activity_flat_dF_spikes), axis=1)
                print("Tokenised neural activity matrix constructed.")

                print("Accumulating data across work units...")
                if dF_resampled.shape[0] > 0:
                    append_cell_metadata(alldF, iCh, "dF", dF_resampled)
                    append_cell_metadata(allF, iCh, "F", F_resampled)
                    append_cell_metadata(all_baseline, iCh, "Baseline", Baseline_resampled)
                    append_cell_metadata(all_spikes, iCh, "Spikes", Spks_resampled)
                    append_cell_metadata(all_depths, iCh, "Depths", np.tile(iDepth, (np.sum(cell_valid[:]).astype(int), 1)))
                    append_cell_metadata(
                        all_original_suite2p_cell_ids, iCh, "OriginalSuite2pCellIDs", valid_cell_ids.reshape(-1, 1)
                    )
                    append_cell_metadata(all_tokenised_dF_spikes, iCh, "tokenised", tokenised_dF_spikes)
                    if mode == "meso":
                        append_cell_metadata(
                            all_scanpaths,
                            iCh,
                            "Scanpaths",
                            np.tile(work_unit["scanpath_label"], (np.sum(cell_valid[:]).astype(int), 1)),
                        )
                        append_cell_metadata(
                            all_si_rois,
                            iCh,
                            "SIRois",
                            np.tile(work_unit["roi_label"], (np.sum(cell_valid[:]).astype(int), 1)),
                        )
                    del dF_resampled, F_resampled, Baseline_resampled, Spks_resampled
                    del tokenised_dF_spikes
                    del dF, dF_spikes, F_valid, Spks_valid, baseline
                    gc.collect()

                print("Accumulation complete.")
                store_spatial_metadata(all_roi_pix[iCh], work_unit, iDepth, roi_pix)
                store_spatial_metadata(all_roi_maps[iCh], work_unit, iDepth, roi_map)
                store_spatial_metadata(all_fov[iCh], work_unit, iDepth, s2p_ops["meanImg"])

    print("Concatenating final output...")
    output_len = len(output_times_common) if output_times_common is not None else 0
    for iCh in range(max_channel_count):
        if alldF[iCh]:
            alldF[iCh] = np.concatenate(alldF[iCh], axis=0)
            allF[iCh] = np.concatenate(allF[iCh], axis=0)
            all_baseline[iCh] = np.concatenate(all_baseline[iCh], axis=0)
            all_spikes[iCh] = np.concatenate(all_spikes[iCh], axis=0)
            all_depths[iCh] = np.concatenate(all_depths[iCh], axis=0)
            all_original_suite2p_cell_ids[iCh] = np.concatenate(all_original_suite2p_cell_ids[iCh], axis=0)
            all_tokenised_dF_spikes[iCh] = np.concatenate(all_tokenised_dF_spikes[iCh], axis=0)
            if mode == "meso":
                all_scanpaths[iCh] = np.concatenate(all_scanpaths[iCh], axis=0)
                all_si_rois[iCh] = np.concatenate(all_si_rois[iCh], axis=0)
        else:
            alldF[iCh] = np.zeros((0, output_len), dtype=np.float32)
            allF[iCh] = np.zeros((0, output_len), dtype=np.float32)
            all_baseline[iCh] = np.zeros((0, output_len), dtype=np.float32)
            all_spikes[iCh] = np.zeros((0, output_len), dtype=np.float32)
            all_depths[iCh] = np.zeros((0, 1), dtype=np.int32)
            all_original_suite2p_cell_ids[iCh] = np.zeros((0, 1), dtype=np.int32)
            all_tokenised_dF_spikes[iCh] = np.zeros((0, 3), dtype=np.float32)
            if mode == "meso":
                all_scanpaths[iCh] = np.zeros((0, 1), dtype=np.int32)
                all_si_rois[iCh] = np.zeros((0, 1), dtype=np.int32)

    print("Saving 2-photon data...")
    if not os.path.exists(exp_dir_processed_recordings):
        os.makedirs(exp_dir_processed_recordings, exist_ok=True)

    for iCh in range(len(alldF)):
        ca_data = {}
        ca_data_tokenised = {}
        ca_data["dF"] = alldF[iCh].astype(np.float32)
        ca_data["F"] = allF[iCh].astype(np.int16)
        ca_data["Spikes"] = all_spikes[iCh].astype(np.float32)
        ca_data["Baseline"] = all_baseline[iCh].astype(np.int16)

        all_tokenised_dF_spikes[iCh] = all_tokenised_dF_spikes[iCh][
            np.lexsort(
                (
                    all_tokenised_dF_spikes[iCh][:, 0],
                    np.round(all_tokenised_dF_spikes[iCh][:, 1], 9),
                )
            )
        ]
        ca_data_tokenised["all_tokenised_dF_spikes"] = all_tokenised_dF_spikes[iCh].astype(np.float32)

        ca_data["Depths"] = all_depths[iCh]
        ca_data["OriginalSuite2pCellIDs"] = all_original_suite2p_cell_ids[iCh]
        ca_data["AllRoiPix"] = to_regular_dict(all_roi_pix[iCh]) if mode == "meso" else all_roi_pix[iCh]
        ca_data["AllRoiMaps"] = to_regular_dict(all_roi_maps[iCh]) if mode == "meso" else all_roi_maps[iCh]
        ca_data["AllFOV"] = to_regular_dict(all_fov[iCh]) if mode == "meso" else all_fov[iCh]
        if mode == "meso":
            ca_data["Scanpaths"] = all_scanpaths[iCh]
            ca_data["SIRois"] = all_si_rois[iCh]
        ca_data["t"] = output_times_common

        output_filename = "s2p_ch" + str(iCh) + ".pickle"
        with open(os.path.join(exp_dir_processed_recordings, output_filename), "wb") as pickle_out:
            pickle.dump(ca_data, pickle_out)

        output_filename = "s2p_tokenised_ch" + str(iCh) + ".pickle"
        with open(os.path.join(exp_dir_processed_recordings, output_filename), "wb") as pickle_out:
            pickle.dump(ca_data_tokenised, pickle_out)

    print("2-photon preprocessing done")


def main():
    userID = "adamranson"
    expID = "2025-03-05_02_ESMT204"
    run_preprocess_s2p_universal(userID, expID)


if __name__ == "__main__":
    main()
