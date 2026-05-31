# these scripts are to run commands that need to be run in specific conda environments
# they should be run from the command line
from conceivable import thread_limit
import sys
import suite2p
from suite2p import io as suite2p_io
from suite2p.run_s2p import run_plane
from suite2p.registration import register as suite2p_register
from preprocess_pipeline.shared import paths
import numpy as np
import os
import re
from glob import glob
import shutil
import pickle
import tifffile


DETECTION_FILES = [
    "stat.npy",
    "F.npy",
    "Fneu.npy",
    "F_chan2.npy",
    "Fneu_chan2.npy",
    "iscell.npy",
    "redcell.npy",
    "spks.npy",
]

CH2_EXTRA_FILES = [
    "F_chan2.npy",
    "Fneu_chan2.npy",
    "redcell.npy",
]


def is_meso_tif_path(first_tif_path):
    """Return True when the TIFF lives under a P*/R* mesoscope layout."""
    tif_path = os.path.abspath(first_tif_path)
    roi_root = os.path.dirname(tif_path)
    scanpath_root = os.path.dirname(roi_root)
    return (
        os.path.basename(roi_root).startswith("R")
        and os.path.basename(scanpath_root).startswith("P")
    )


def count_meso_rois_for_tif(first_tif_path):
    """Count ROI folders in the parent mesoscope scanpath for a given ROI TIFF."""
    tif_path = os.path.abspath(first_tif_path)
    roi_root = os.path.dirname(tif_path)
    scanpath_root = os.path.dirname(roi_root)
    rois = [
        entry
        for entry in sorted(os.listdir(scanpath_root))
        if entry.startswith("R") and os.path.isdir(os.path.join(scanpath_root, entry))
    ]
    return max(1, len(rois))


def infer_standard_scanimage_metadata(first_tif_path):
    """Infer plane count and per-plane fs from ScanImage metadata embedded in standard TIFFs."""
    with tifffile.TiffFile(first_tif_path) as tif:
        si_meta = getattr(tif, "scanimage_metadata", None)
        frame_data = si_meta.get("FrameData") if isinstance(si_meta, dict) else None
        if isinstance(frame_data, dict):
            nplanes = None
            for key in [
                "SI.hStackManager.numFramesPerVolume",
                "SI.hStackManager.actualNumSlices",
                "SI.hStackManager.numSlices",
            ]:
                value = frame_data.get(key)
                try:
                    candidate = int(value)
                except Exception:
                    continue
                if candidate > 0:
                    nplanes = candidate
                    break

            if nplanes is not None:
                scan_frame_rate = frame_data.get("SI.hRoiManager.scanFrameRate")
                fs = None
                try:
                    if scan_frame_rate is not None:
                        fs = float(scan_frame_rate) / float(nplanes)
                except Exception:
                    fs = None
                return nplanes, fs, scan_frame_rate

    with open(first_tif_path, "rb") as file:
        description = file.read(400000).decode("latin1", errors="ignore")

    nplanes = None
    for key in [
        "SI.hStackManager.numFramesPerVolume",
        "SI.hStackManager.actualNumSlices",
        "SI.hStackManager.numSlices",
    ]:
        match = re.search(rf"{re.escape(key)}\s*=\s*([0-9]+)", description)
        if match:
            candidate = int(match.group(1))
            if candidate > 0:
                nplanes = candidate
                break

    if nplanes is not None:
        fs = None
        match = re.search(rf"{re.escape('SI.hRoiManager.scanFrameRate')}\s*=\s*([0-9.]+)", description)
        if match:
            try:
                fs = float(match.group(1)) / float(nplanes)
            except Exception:
                fs = None
        return nplanes, fs, float(match.group(1)) if match else None

    raise ValueError(f"Could not infer nplanes from standard TIFF metadata: {first_tif_path}")


def infer_meso_scanimage_metadata(first_tif_path):
    """Infer plane count and per-plane/per-ROI fs from mesoscope SI_meta sidecar data."""
    tif_path = os.path.abspath(first_tif_path)
    roi_root = os.path.dirname(tif_path)
    scanpath_root = os.path.dirname(roi_root)
    si_meta_path = os.path.join(scanpath_root, "SI_meta.pickle")

    if not os.path.exists(si_meta_path):
        raise FileNotFoundError(f"Could not find SI_meta.pickle for {first_tif_path}")

    with open(si_meta_path, "rb") as f:
        si_meta = pickle.load(f)

    meta1 = si_meta.get("Meta1")
    if isinstance(meta1, (list, tuple)) and meta1:
        header = meta1[0]
    elif isinstance(meta1, dict):
        header = meta1
    else:
        raise ValueError(f"Unexpected Meta1 format in {si_meta_path}")

    nplanes = None
    for key in [
        "SI.hStackManager.numFramesPerVolume",
        "SI.hStackManager.actualNumSlices",
        "SI.hStackManager.numSlices",
    ]:
        value = header.get(key)
        try:
            candidate = int(value)
        except Exception:
            continue
        if candidate > 0:
            nplanes = candidate
            break

    if nplanes is None:
        raise ValueError(f"Could not infer nplanes from SI_meta.pickle: {si_meta_path}")

    fs = None
    scan_frame_rate = header.get("SI.hRoiManager.scanFrameRate")
    nrois = count_meso_rois_for_tif(first_tif_path)
    try:
        if scan_frame_rate is not None:
            fs = float(scan_frame_rate) / float(nplanes) / float(nrois)
    except Exception:
        fs = None
    return nplanes, fs, scan_frame_rate, nrois

def infer_scanimage_sampling(first_tif_path):
    """Dispatch plane-count and fs inference by raw-data topology."""
    if is_meso_tif_path(first_tif_path):
        nplanes, fs, scan_frame_rate, nrois = infer_meso_scanimage_metadata(first_tif_path)
        details = {
            "mode": "meso",
            "source": "SI_meta.pickle",
            "scan_frame_rate": scan_frame_rate,
            "nrois": nrois,
        }
        return nplanes, fs, details
    nplanes, fs, scan_frame_rate = infer_standard_scanimage_metadata(first_tif_path)
    details = {
        "mode": "standard",
        "source": first_tif_path,
        "scan_frame_rate": scan_frame_rate,
    }
    return nplanes, fs, details


def resolve_first_tif_path(data_path):
    """Resolve a raw TIFF file from either a TIFF path or an experiment directory."""
    if os.path.isfile(data_path):
        return data_path

    if not os.path.isdir(data_path):
        raise FileNotFoundError(f"TIFF source path does not exist: {data_path}")

    tif_candidates = sorted(glob(os.path.join(data_path, "*.tif")))
    tif_candidates.extend(sorted(glob(os.path.join(data_path, "*.tiff"))))
    if not tif_candidates:
        raise FileNotFoundError(f"No TIFF files found in: {data_path}")

    return tif_candidates[0]


def load_ops_with_inferred_nplanes(config_path, all_tif_paths):
    """Load Suite2p ops and optionally populate nplanes/fs from raw ScanImage metadata."""
    ops = np.load(config_path, allow_pickle=True).item()
    if ops.get("nplanes", 1) == 0:
        first_tif_path = resolve_first_tif_path(all_tif_paths[0])
        ops["nplanes"], inferred_fs, details = infer_scanimage_sampling(first_tif_path)
        print(f"Inferred nplanes={ops['nplanes']} from {details['source']}")
        if inferred_fs is not None:
            ops["fs"] = float(inferred_fs)
            if details["mode"] == "meso":
                print(
                    "Inferred fs="
                    f"{ops['fs']} as scanFrameRate({details['scan_frame_rate']})"
                    f" / nplanes({ops['nplanes']}) / nrois({details['nrois']})"
                )
            else:
                print(
                    "Inferred fs="
                    f"{ops['fs']} as scanFrameRate({details['scan_frame_rate']})"
                    f" / nplanes({ops['nplanes']})"
                )
    return ops


def resolve_nplanes(config_path, all_tif_paths):
    """Resolve the effective Suite2p nplanes value for this run."""
    return int(load_ops_with_inferred_nplanes(config_path, all_tif_paths)["nplanes"])


def fix_binary_permissions(save_root):
    """Ensure Suite2p binary files remain group-writable."""
    for dirpath, _, filenames in os.walk(save_root):
        for filename in filenames:
            if filename in {"data.bin", "data_chan2.bin"}:
                path = os.path.join(dirpath, filename)
                mode = os.stat(path).st_mode & 0o777
                os.chmod(path, mode | 0o020)


def clear_detection_outputs(save_root):
    """Remove extraction outputs while keeping canonical binaries in place."""
    suite2p_root = os.path.join(save_root, "suite2p")
    if not os.path.isdir(suite2p_root):
        return

    combined_dir = os.path.join(suite2p_root, "combined")
    if os.path.isdir(combined_dir):
        for root, dirs, files in os.walk(combined_dir, topdown=False):
            for filename in files:
                os.remove(os.path.join(root, filename))
            for dirname in dirs:
                os.rmdir(os.path.join(root, dirname))
        os.rmdir(combined_dir)

    for plane_name in os.listdir(suite2p_root):
        if not plane_name.startswith("plane"):
            continue
        plane_dir = os.path.join(suite2p_root, plane_name)
        for filename in DETECTION_FILES:
            path = os.path.join(plane_dir, filename)
            if os.path.exists(path):
                os.remove(path)


def replace_file(src, dst):
    """Replace dst with a copy of src."""
    if os.path.lexists(dst):
        os.remove(dst)
    shutil.copy2(src, dst)


def remove_tree_if_exists(path):
    """Remove a directory tree when present."""
    if os.path.isdir(path):
        shutil.rmtree(path)


def move_red_channel_binary(red_reg_file, plane_save_dir):
    """Move the red-channel binary into the ch2 output tree."""
    local_reg_file = os.path.join(plane_save_dir, "data.bin")
    if os.path.lexists(local_reg_file):
        os.remove(local_reg_file)
    shutil.move(red_reg_file, local_reg_file)
    return local_reg_file


def get_plane_dirs(save_root):
    suite2p_root = os.path.join(save_root, "suite2p")
    return sorted(
        os.path.join(suite2p_root, dirname)
        for dirname in os.listdir(suite2p_root)
        if dirname.startswith("plane") and os.path.isdir(os.path.join(suite2p_root, dirname))
    )


def update_combined_ops(save_root, nplanes):
    """Persist shared metadata into the combined Suite2p ops file if present."""
    combined_ops_path = os.path.join(save_root, "suite2p", "combined", "ops.npy")
    if not os.path.exists(combined_ops_path):
        return

    combined_ops = np.load(combined_ops_path, allow_pickle=True).item()
    combined_ops["nplanes"] = int(nplanes)
    if combined_ops.get("nchannels") == 1:
        for key in ["reg_file_chan2", "raw_file_chan2", "meanImg_chan2", "meanImg_chan2_corrected"]:
            if key in combined_ops:
                del combined_ops[key]
    np.save(combined_ops_path, combined_ops)


def copy_ops_for_extraction(registration_ops, extraction_ops):
    """Preserve registration-derived metadata while applying extraction settings."""
    ops = registration_ops.copy()

    # Suite2p "config" files are often saved full ops dicts from prior runs rather
    # than minimal clean configs. Runtime-derived fields from those saved ops can
    # silently conflict with the freshly registered binary we are about to reopen
    # for extraction-only runs. In particular, stale nframes/badframes/reg_file
    # values can produce shape mismatches inside Suite2p ROI detection.
    protected_runtime_keys = {
        "data_path",
        "save_path0",
        "fast_disk",
        "save_folder",
        "subfolders",
        "nframes",
        "badframes",
        "reg_file",
        "reg_file_chan2",
        "raw_file",
        "raw_file_chan2",
        "ops_path",
        "save_path",
        "date_proc",
    }

    for key, value in extraction_ops.items():
        if key not in protected_runtime_keys:
            ops[key] = value

    return ops


def write_empty_detection_outputs(plane_save_dir, plane_ops):
    """Write GUI-loadable placeholder Suite2p outputs for planes where no ROIs were detected."""
    nframes = int(plane_ops.get("nframes", 0))
    ypix = np.array([0], dtype=np.int32)
    xpix = np.array([0], dtype=np.int32)
    med = np.array([0.0, 0.0], dtype=np.float32)
    dummy_stat = np.array(
        [
            {
                "ypix": ypix,
                "xpix": xpix,
                "lam": np.array([0.0], dtype=np.float32),
                "med": med,
                "npix": 1,
                "radius": 0.0,
                "aspect_ratio": 1.0,
                "compact": 0.0,
                "footprint": 0.0,
                "skew": 0.0,
                "std": 0.0,
                "overlap": np.array([False]),
            }
        ],
        dtype=object,
    )
    np.save(os.path.join(plane_save_dir, "stat.npy"), dummy_stat)
    np.save(os.path.join(plane_save_dir, "F.npy"), np.zeros((1, nframes), dtype=np.float32))
    np.save(os.path.join(plane_save_dir, "Fneu.npy"), np.zeros((1, nframes), dtype=np.float32))
    np.save(os.path.join(plane_save_dir, "iscell.npy"), np.array([[0.0, 0.0]], dtype=np.float32))
    np.save(os.path.join(plane_save_dir, "spks.npy"), np.zeros((1, nframes), dtype=np.float32))
    np.save(plane_ops["ops_path"], plane_ops)


def run_shared_registration(all_tif_paths, output_path, registration_config_path):
    """Register once on ch1 and write canonical binaries for both channels."""
    # The shared-registration path always forces a fresh registration pass.
    # If a prior partial two-channel run left stale per-plane ops/binaries behind,
    # Suite2p will try to reuse them and can fail before it rebuilds chan2 paths.
    remove_tree_if_exists(os.path.join(output_path, "suite2p"))
    remove_tree_if_exists(os.path.join(output_path, "ch2"))

    ops = load_ops_with_inferred_nplanes(registration_config_path, all_tif_paths)
    ops["save_mat"] = False
    ops["functional_chan"] = 1
    ops["roidetect"] = False
    ops["do_registration"] = 2

    db = {
        "data_path": all_tif_paths,
        "save_path0": output_path,
    }
    suite2p.run_s2p(ops=ops, db=db)
    fix_binary_permissions(output_path)


def run_extraction_stage(canonical_root, save_root, extraction_config_path, nplanes):
    """Reuse canonical binaries and rerun detection/deconvolution with a per-channel config."""
    clear_detection_outputs(save_root)

    canonical_plane_dirs = get_plane_dirs(canonical_root)
    extraction_config = np.load(extraction_config_path, allow_pickle=True).item()

    for canonical_plane_dir in canonical_plane_dirs:
        plane_name = os.path.basename(canonical_plane_dir)
        registration_ops = np.load(os.path.join(canonical_plane_dir, "ops.npy"), allow_pickle=True).item()

        plane_save_dir = os.path.join(save_root, "suite2p", plane_name)
        os.makedirs(plane_save_dir, exist_ok=True)

        reg_file = os.path.join(canonical_plane_dir, "data.bin")
        reg_file_chan2 = os.path.join(canonical_plane_dir, "data_chan2.bin")
        output_reg_file = reg_file

        if save_root != canonical_root:
            if os.path.exists(reg_file_chan2):
                output_reg_file = move_red_channel_binary(reg_file_chan2, plane_save_dir)
            else:
                output_reg_file = os.path.join(plane_save_dir, "data.bin")
                replace_file(reg_file, output_reg_file)

        plane_ops = copy_ops_for_extraction(registration_ops, extraction_config)
        plane_ops["save_mat"] = False
        plane_ops["do_registration"] = 0
        plane_ops["save_path0"] = save_root
        plane_ops["save_path"] = plane_save_dir
        plane_ops["ops_path"] = os.path.join(plane_save_dir, "ops.npy")
        plane_ops["move_bin"] = False
        plane_ops["delete_bin"] = False
        plane_ops["nchannels"] = 1
        plane_ops["functional_chan"] = 1
        plane_ops["nplanes"] = int(nplanes)
        plane_ops["reg_file"] = output_reg_file if save_root != canonical_root else reg_file
        if save_root != canonical_root and "meanImg_chan2" in registration_ops:
            plane_ops["meanImg"] = registration_ops["meanImg_chan2"].astype(np.float32)
            image_ops = plane_ops.copy()
            plane_ops["meanImgE"] = suite2p_register.compute_enhanced_mean_image(
                plane_ops["meanImg"], image_ops
            ).astype(np.float32)
        for key in ["reg_file_chan2", "raw_file_chan2", "meanImg_chan2", "raw_file"]:
            if key in plane_ops:
                del plane_ops[key]

        try:
            plane_ops = run_plane(plane_ops)
        except ValueError as exc:
            if "no ROIs were found" not in str(exc):
                raise
            print(f"No ROIs detected for {plane_save_dir}; writing empty placeholder outputs.")
            write_empty_detection_outputs(plane_save_dir, plane_ops)
            continue

        plane_ops["nchannels"] = 1
        plane_ops["functional_chan"] = 1
        plane_ops["nplanes"] = int(nplanes)
        plane_ops["reg_file"] = output_reg_file if save_root != canonical_root else reg_file
        if save_root != canonical_root and "meanImg_chan2" in registration_ops:
            plane_ops["meanImg"] = registration_ops["meanImg_chan2"].astype(np.float32)
            image_ops = plane_ops.copy()
            plane_ops["meanImgE"] = suite2p_register.compute_enhanced_mean_image(
                plane_ops["meanImg"], image_ops
            ).astype(np.float32)
        for key in ["reg_file_chan2", "raw_file_chan2", "meanImg_chan2", "raw_file"]:
            if key in plane_ops:
                del plane_ops[key]

        for filename in CH2_EXTRA_FILES:
            extra_path = os.path.join(plane_save_dir, filename)
            if os.path.exists(extra_path):
                os.remove(extra_path)
        np.save(plane_ops["ops_path"], plane_ops)

    if len(canonical_plane_dirs) > 1 and extraction_config.get("combined", True) and extraction_config.get("roidetect", True):
        suite2p_io.combined(os.path.join(save_root, "suite2p"), save=True)
        update_combined_ops(save_root, nplanes)

    fix_binary_permissions(save_root)


def run_single_config_suite2p(all_tif_paths, output_path, config_path):
    """Single-config launcher path, including the legacy functional_chan==3 special case."""
    ops = load_ops_with_inferred_nplanes(config_path, all_tif_paths)
    ops["save_mat"] = False

    if ops["functional_chan"] == 3:
        db = {
            "data_path": all_tif_paths,
            "save_path0": output_path,
        }
        ops["functional_chan"] = 1
        suite2p.run_s2p(ops=ops, db=db)
        fix_binary_permissions(output_path)

        db = {
            "data_path": all_tif_paths,
            "save_path0": os.path.join(output_path, "ch2"),
        }
        ops["functional_chan"] = 2
        suite2p.run_s2p(ops=ops, db=db)
        fix_binary_permissions(os.path.join(output_path, "ch2"))
        return

    db = {
        "data_path": all_tif_paths,
        "save_path0": output_path,
    }
    suite2p.run_s2p(ops=ops, db=db)
    fix_binary_permissions(output_path)


def finalize_dual_channel_binary_layout(canonical_root, ch2_root, nplanes):
    """Keep only green binaries in root and only red binaries in the ch2 tree."""
    for canonical_plane_dir in get_plane_dirs(canonical_root):
        plane_name = os.path.basename(canonical_plane_dir)
        ch2_plane_dir = os.path.join(ch2_root, "suite2p", plane_name)

        root_green_bin = os.path.join(canonical_plane_dir, "data.bin")
        root_red_bin = os.path.join(canonical_plane_dir, "data_chan2.bin")
        ch2_red_bin = os.path.join(ch2_plane_dir, "data.bin")
        ch2_red_bin_legacy = os.path.join(ch2_plane_dir, "data_chan2.bin")

        if os.path.exists(ch2_red_bin_legacy):
            os.remove(ch2_red_bin_legacy)

        if os.path.exists(root_red_bin):
            if not os.path.exists(ch2_red_bin):
                os.makedirs(ch2_plane_dir, exist_ok=True)
                shutil.move(root_red_bin, ch2_red_bin)
            else:
                os.remove(root_red_bin)

        root_ops_path = os.path.join(canonical_plane_dir, "ops.npy")
        if os.path.exists(root_ops_path):
            root_ops = np.load(root_ops_path, allow_pickle=True).item()
            root_ops["reg_file"] = root_green_bin
            root_ops["nplanes"] = int(nplanes)
            for key in ["reg_file_chan2", "raw_file_chan2", "meanImg_chan2", "meanImg_chan2_corrected"]:
                if key in root_ops:
                    del root_ops[key]
            np.save(root_ops_path, root_ops)

        ch2_ops_path = os.path.join(ch2_plane_dir, "ops.npy")
        if os.path.exists(ch2_ops_path):
            ch2_ops = np.load(ch2_ops_path, allow_pickle=True).item()
            if os.path.exists(ch2_red_bin):
                ch2_ops["reg_file"] = ch2_red_bin
            ch2_ops["nchannels"] = 1
            ch2_ops["functional_chan"] = 1
            ch2_ops["nplanes"] = int(nplanes)
            for key in [
                "reg_file_chan2",
                "raw_file_chan2",
                "meanImg_chan2",
                "meanImg_chan2_corrected",
            ]:
                if key in ch2_ops:
                    del ch2_ops[key]
            np.save(ch2_ops_path, ch2_ops)

    update_combined_ops(canonical_root, nplanes)
    update_combined_ops(ch2_root, nplanes)


def resolve_output_path(userID, expID, output_path):
    if output_path is not None:
        return output_path
    all_exp_ids = expID.split(",")
    _, _, _, exp_dir_processed, _ = paths.find_paths(userID, all_exp_ids[0])
    return exp_dir_processed


def s2p_launcher_run(userID, expID, tif_path, output_path, config_path):
    all_tif_paths = tif_path.split(",")
    print("tif_path = " + tif_path)
    print("ExpID = " + expID)
    print("output_path = " + output_path)
    config_paths = config_path.split(",")

    if len(config_paths) == 2:
        nplanes = resolve_nplanes(config_paths[0], all_tif_paths)
        run_shared_registration(all_tif_paths, output_path, config_paths[0])
        ch2_root = os.path.join(output_path, "ch2")
        run_extraction_stage(output_path, ch2_root, config_paths[1], nplanes)
        run_extraction_stage(output_path, output_path, config_paths[0], nplanes)
        finalize_dual_channel_binary_layout(output_path, ch2_root, nplanes)
        return

    run_single_config_suite2p(all_tif_paths, output_path, config_paths[0])


def main():
    print("S2P Launcher Universal Run...")
    try:
        userID = sys.argv[1]
        expID = sys.argv[2]
        tif_path = sys.argv[3]
        if len(sys.argv) >= 6:
            output_path = sys.argv[4]
            config_path = sys.argv[5]
        else:
            output_path = None
            config_path = sys.argv[4]
    except Exception:
        expID = "2026-05-11_03_ESRC033,2026-05-11_99_ESRC033"
        userID = "adamranson"
        tif_path = ",".join([
            "/home/adamranson/data/temp/2026-05-11_03_ESRC033",
            "/home/adamranson/data/temp/2026-05-11_99_ESRC033",
        ])
        output_path = "/home/adamranson/data/Repository/ESRC033/2026-05-11_03_ESRC033"
        config_path = ",".join([
            os.path.join("/data/common/configs/s2p_configs", userID, "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy"),
            os.path.join("/data/common/configs/s2p_configs", userID, "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy"),
        ])

    output_path = resolve_output_path(userID, expID, output_path)
    s2p_launcher_run(userID, expID, tif_path, output_path, config_path)


if __name__ == "__main__":
    main()
