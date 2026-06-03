# these scripts are to run commands that need to be run in specific conda environments
# they should be run from the command line
try:
    from conceivable import thread_limit
except ImportError:
    thread_limit = None
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import suite2p
from suite2p import io as suite2p_io
from suite2p.run_s2p import run_plane
from suite2p.registration import register as suite2p_register
from preprocess_pipeline.shared import paths
from preprocess_pipeline.srdtrans.launcher import encode_config_arg as encode_srdtrans_config_arg, decode_config_arg as decode_srdtrans_config_arg
import numpy as np
import os
import re
from glob import glob
import shutil
import pickle
import tifffile


REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / "apps"
DEFAULT_COMBINED_REGISTRATION_TMP_ROOT = Path("/data/fast/lab_pipeline")


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
        "frames_per_folder",
        "frames_per_file",
        "badframes",
        "reg_file",
        "reg_file_chan2",
        "raw_file",
        "raw_file_chan2",
        "ops_path",
        "save_path",
        "date_proc",
        "refImg",
        "meanImg",
        "meanImgE",
        "meanImg_chan2",
        "meanImg_chan2_corrected",
        "max_proj",
        "Vcorr",
        "yoff",
        "xoff",
        "corrXY",
        "yoff1",
        "xoff1",
        "corrXY1",
        "zpos_registration",
        "cmax_registration",
        "badframes",
        "yrange",
        "xrange",
        "rmin",
        "rmax",
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
    """Run the initial rigid registration pass and write canonical binaries."""
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
    ops["nonrigid"] = False

    db = {
        "data_path": all_tif_paths,
        "save_path0": output_path,
    }
    suite2p.run_s2p(ops=ops, db=db)
    fix_binary_permissions(output_path)


def make_combined_registration_binary(ch1_file, ch2_file, combined_file, nframes, Ly, Lx, batch_size):
    """Create a temporary int16 binary containing the average of ch1 and ch2."""
    if os.path.exists(combined_file):
        os.remove(combined_file)
    with suite2p_io.BinaryFile(Ly=Ly, Lx=Lx, filename=ch1_file, n_frames=nframes) as ch1, \
            suite2p_io.BinaryFile(Ly=Ly, Lx=Lx, filename=ch2_file, n_frames=nframes) as ch2, \
            suite2p_io.BinaryFile(Ly=Ly, Lx=Lx, filename=combined_file, n_frames=nframes) as combined:
        for start in range(0, nframes, batch_size):
            stop = min(start + batch_size, nframes)
            frames = (
                ch1[start:stop].astype(np.int32) + ch2[start:stop].astype(np.int32)
            ) / 2.0
            combined[start:stop] = np.rint(frames).astype(np.int16)


def make_combined_registration_tmp_dir(output_path, plane_name, fallback_dir):
    tmp_root = Path(
        os.environ.get(
            "LAB_PIPELINE_COMBINED_REGISTRATION_TMPDIR",
            str(DEFAULT_COMBINED_REGISTRATION_TMP_ROOT),
        )
    )
    try:
        tmp_root.mkdir(parents=True, exist_ok=True)
        if not os.access(tmp_root, os.W_OK):
            raise PermissionError(f"not writable: {tmp_root}")
        prefix = f"{Path(output_path).name}_{plane_name}_"
        return tempfile.mkdtemp(prefix=prefix, dir=str(tmp_root)), True
    except OSError as exc:
        print(
            f"Combined-channel registration scratch unavailable at {tmp_root} "
            f"({exc}); using {fallback_dir}"
        )
        return fallback_dir, False


def register_binary_with_offsets(binary_file, yoff, xoff, yoff1, xoff1, ops):
    with suite2p_io.BinaryFile(
        Ly=int(ops["Ly"]),
        Lx=int(ops["Lx"]),
        filename=binary_file,
        n_frames=int(ops["nframes"]),
    ) as binary:
        return suite2p_register.shift_frames_and_write(
            binary,
            yoff=yoff,
            xoff=xoff,
            yoff1=yoff1,
            xoff1=xoff1,
            ops=ops,
        )


def run_shared_summed_channel_registration(all_tif_paths, output_path, registration_config_path):
    """Register two-channel data using average(ch1, ch2), then apply offsets to both channels."""
    remove_tree_if_exists(os.path.join(output_path, "suite2p"))
    remove_tree_if_exists(os.path.join(output_path, "ch2"))

    ops = load_ops_with_inferred_nplanes(registration_config_path, all_tif_paths)
    if int(ops.get("nchannels", 1)) < 2:
        raise ValueError("Summed-channel registration requires a two-channel Suite2p config.")

    print("** Running combined-channel shared registration")
    conversion_ops = ops.copy()
    conversion_ops["save_mat"] = False
    conversion_ops["roidetect"] = False
    conversion_ops["do_registration"] = 0
    conversion_ops["delete_bin"] = False
    conversion_ops["move_bin"] = False
    conversion_ops["keep_movie_raw"] = False

    db = {
        "data_path": all_tif_paths,
        "save_path0": output_path,
    }
    suite2p.run_s2p(ops=conversion_ops, db=db)

    for plane_dir in get_plane_dirs(output_path):
        plane_name = os.path.basename(plane_dir)
        print(f">>>>>>>>>>>>>>>>>>>>> COMBINED-CHANNEL REGISTRATION {plane_name} <<<<<<<<<<<<<<<<<<<<<<")
        plane_ops_path = os.path.join(plane_dir, "ops.npy")
        plane_ops = np.load(plane_ops_path, allow_pickle=True).item()
        ch1_file = plane_ops["reg_file"]
        ch2_file = plane_ops.get("reg_file_chan2", os.path.join(plane_dir, "data_chan2.bin"))
        if not os.path.exists(ch2_file):
            raise FileNotFoundError(f"Missing channel 2 binary for summed registration: {ch2_file}")

        reg_ops = plane_ops.copy()
        reg_ops["save_mat"] = False
        reg_ops["do_registration"] = 2
        reg_ops["nonrigid"] = False
        reg_ops["functional_chan"] = 1
        reg_ops["align_by_chan"] = 1
        reg_ops["delete_bin"] = False
        reg_ops["move_bin"] = False
        reg_ops["save_path"] = plane_dir
        reg_ops["ops_path"] = plane_ops_path
        reg_ops["reg_file"] = ch1_file
        reg_ops["reg_file_chan2"] = ch2_file

        nframes = int(reg_ops["nframes"])
        Ly = int(reg_ops["Ly"])
        Lx = int(reg_ops["Lx"])
        batch_size = int(reg_ops.get("batch_size", 500))
        scratch_dir, scratch_is_temp = make_combined_registration_tmp_dir(
            output_path, plane_name, plane_dir
        )
        combined_file = os.path.join(scratch_dir, "data_combined_registration.bin")
        try:
            print(f"Creating averaged two-channel registration binary: {combined_file}")
            make_combined_registration_binary(ch1_file, ch2_file, combined_file, nframes, Ly, Lx, batch_size)

            with suite2p_io.BinaryFile(Ly=Ly, Lx=Lx, filename=combined_file, n_frames=nframes) as combined_binary:
                registration_outputs = suite2p_register.registration_wrapper(
                    combined_binary,
                    ops=reg_ops,
                )

            reg_ops = suite2p_register.save_registration_outputs_to_ops(registration_outputs, reg_ops)
            yoff, xoff, _corrXY = reg_ops["yoff"], reg_ops["xoff"], reg_ops["corrXY"]
            yoff1 = reg_ops.get("yoff1")
            xoff1 = reg_ops.get("xoff1")

            print("Applying combined-channel registration offsets to channel 1")
            mean_img_ch1 = register_binary_with_offsets(ch1_file, yoff, xoff, yoff1, xoff1, reg_ops)
            print("Applying combined-channel registration offsets to channel 2")
            mean_img_ch2 = register_binary_with_offsets(ch2_file, yoff, xoff, yoff1, xoff1, reg_ops)

            reg_ops["meanImg"] = mean_img_ch1.astype(np.float32)
            reg_ops["meanImg_chan2"] = mean_img_ch2.astype(np.float32)
            reg_ops["meanImgE"] = suite2p_register.compute_enhanced_mean_image(
                reg_ops["meanImg"], reg_ops.copy()
            ).astype(np.float32)
            reg_ops["register_with_summed_channel"] = True
            reg_ops["registration_channel_combination"] = "average"
            reg_ops["combined_registration_tmp_root"] = str(Path(scratch_dir).parent)
            np.save(plane_ops_path, reg_ops)
        finally:
            if scratch_is_temp:
                shutil.rmtree(scratch_dir, ignore_errors=True)
            elif os.path.exists(combined_file):
                os.remove(combined_file)

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


def _selected_binary_for_plane(canonical_plane_dir, source_channel, plane_save_dir=None):
    reg_file = os.path.join(canonical_plane_dir, "data.bin")
    reg_file_chan2 = os.path.join(canonical_plane_dir, "data_chan2.bin")

    if source_channel == "ch1":
        return reg_file

    if source_channel != "ch2":
        raise ValueError(f"Unknown source channel: {source_channel}")

    if plane_save_dir is None:
        return reg_file_chan2

    if os.path.exists(reg_file_chan2):
        return move_red_channel_binary(reg_file_chan2, plane_save_dir)

    fallback = os.path.join(plane_save_dir, "data.bin")
    replace_file(reg_file, fallback)
    return fallback


def _run_srdtrans_on_binary(plane_dir, input_filename, srdtrans_config):
    launcher = APP_ROOT / "srdtrans_launcher.py"
    cmd = [
        "/opt/scripts/conda-run.sh",
        str(srdtrans_config.get("env", "srdtrans")),
        "python",
        str(launcher),
        plane_dir,
        input_filename,
        encode_srdtrans_config_arg(srdtrans_config),
    ]
    print(f"** Running SRDTrans on {os.path.join(plane_dir, input_filename)}")
    subprocess.run(cmd, check=True)


def apply_srdtrans_to_registered_planes(canonical_root, srdtrans_config, available_channels):
    channels = srdtrans_config.get("channels")
    if not channels:
        channels = ["ch1"] if "ch1" in available_channels else list(available_channels)
    unknown_channels = set(channels) - set(available_channels)
    if unknown_channels:
        raise ValueError(
            f"SRDTrans channels {sorted(unknown_channels)} are not available for this work unit"
        )

    for canonical_plane_dir in get_plane_dirs(canonical_root):
        for channel in channels:
            if channel == "ch1":
                _run_srdtrans_on_binary(canonical_plane_dir, "data.bin", srdtrans_config)
            elif channel == "ch2" and os.path.exists(
                os.path.join(canonical_plane_dir, "data_chan2.bin")
            ):
                _run_srdtrans_on_binary(canonical_plane_dir, "data_chan2.bin", srdtrans_config)


def run_final_summed_channel_registration(canonical_root, final_config_path):
    """Run the post-denoise registration using average(ch1, ch2) and apply it to both channels."""
    final_config = np.load(final_config_path, allow_pickle=True).item()

    for canonical_plane_dir in get_plane_dirs(canonical_root):
        plane_name = os.path.basename(canonical_plane_dir)
        print(f">>>>>>>>>>>>>>>>>>>>> FINAL COMBINED-CHANNEL REGISTRATION {plane_name} <<<<<<<<<<<<<<<<<<<<<<")
        plane_ops_path = os.path.join(canonical_plane_dir, "ops.npy")
        registration_ops = np.load(plane_ops_path, allow_pickle=True).item()

        ch1_file = os.path.join(canonical_plane_dir, "data.bin")
        ch2_file = os.path.join(canonical_plane_dir, "data_chan2.bin")
        if not os.path.exists(ch1_file):
            raise FileNotFoundError(f"Missing channel 1 binary for final summed registration: {ch1_file}")
        if not os.path.exists(ch2_file):
            raise FileNotFoundError(f"Missing channel 2 binary for final summed registration: {ch2_file}")

        reg_ops = copy_ops_for_extraction(registration_ops, final_config)
        reg_ops["save_mat"] = False
        reg_ops["do_registration"] = 2
        reg_ops["functional_chan"] = 1
        reg_ops["align_by_chan"] = 1
        reg_ops["nchannels"] = 1
        reg_ops["delete_bin"] = False
        reg_ops["move_bin"] = False
        reg_ops["save_path"] = canonical_plane_dir
        reg_ops["ops_path"] = plane_ops_path
        reg_ops["reg_file"] = ch1_file
        reg_ops["reg_file_chan2"] = ch2_file

        nframes = int(reg_ops["nframes"])
        Ly = int(reg_ops["Ly"])
        Lx = int(reg_ops["Lx"])
        batch_size = int(reg_ops.get("batch_size", 500))
        scratch_dir, scratch_is_temp = make_combined_registration_tmp_dir(
            canonical_root, plane_name, canonical_plane_dir
        )
        combined_file = os.path.join(scratch_dir, "data_final_combined_registration.bin")
        try:
            print(f"Creating averaged two-channel final registration binary: {combined_file}")
            make_combined_registration_binary(ch1_file, ch2_file, combined_file, nframes, Ly, Lx, batch_size)

            with suite2p_io.BinaryFile(Ly=Ly, Lx=Lx, filename=combined_file, n_frames=nframes) as combined_binary:
                registration_outputs = suite2p_register.registration_wrapper(
                    combined_binary,
                    ops=reg_ops,
                )

            reg_ops = suite2p_register.save_registration_outputs_to_ops(registration_outputs, reg_ops)
            yoff, xoff = reg_ops["yoff"], reg_ops["xoff"]
            yoff1 = reg_ops.get("yoff1")
            xoff1 = reg_ops.get("xoff1")

            print("Applying final combined-channel registration offsets to channel 1")
            mean_img_ch1 = register_binary_with_offsets(ch1_file, yoff, xoff, yoff1, xoff1, reg_ops)
            print("Applying final combined-channel registration offsets to channel 2")
            mean_img_ch2 = register_binary_with_offsets(ch2_file, yoff, xoff, yoff1, xoff1, reg_ops)

            reg_ops["meanImg"] = mean_img_ch1.astype(np.float32)
            reg_ops["meanImg_chan2"] = mean_img_ch2.astype(np.float32)
            reg_ops["meanImgE"] = suite2p_register.compute_enhanced_mean_image(
                reg_ops["meanImg"], reg_ops.copy()
            ).astype(np.float32)
            reg_ops["register_with_summed_channel"] = True
            reg_ops["final_register_with_summed_channel"] = True
            reg_ops["registration_channel_combination"] = "average"
            reg_ops["combined_registration_tmp_root"] = str(Path(scratch_dir).parent)
            np.save(plane_ops_path, reg_ops)
        finally:
            if scratch_is_temp:
                shutil.rmtree(scratch_dir, ignore_errors=True)
            elif os.path.exists(combined_file):
                os.remove(combined_file)

    fix_binary_permissions(canonical_root)


def run_final_suite2p_stage(canonical_root, save_root, final_config_path, nplanes, source_channel):
    """Run the final Suite2p pass on already rigid-registered binaries."""
    clear_detection_outputs(save_root)

    canonical_plane_dirs = get_plane_dirs(canonical_root)
    final_config = np.load(final_config_path, allow_pickle=True).item()

    for canonical_plane_dir in canonical_plane_dirs:
        plane_name = os.path.basename(canonical_plane_dir)
        registration_ops = np.load(os.path.join(canonical_plane_dir, "ops.npy"), allow_pickle=True).item()

        plane_save_dir = os.path.join(save_root, "suite2p", plane_name)
        os.makedirs(plane_save_dir, exist_ok=True)

        output_reg_file = _selected_binary_for_plane(
            canonical_plane_dir,
            source_channel,
            plane_save_dir if save_root != canonical_root else None,
        )

        plane_ops = copy_ops_for_extraction(registration_ops, final_config)
        plane_ops["save_mat"] = False
        plane_ops["save_path0"] = save_root
        plane_ops["save_path"] = plane_save_dir
        plane_ops["ops_path"] = os.path.join(plane_save_dir, "ops.npy")
        plane_ops["move_bin"] = False
        plane_ops["delete_bin"] = False
        plane_ops["nchannels"] = 1
        plane_ops["functional_chan"] = 1
        plane_ops["align_by_chan"] = 1
        plane_ops["nplanes"] = int(nplanes)
        plane_ops["reg_file"] = output_reg_file
        plane_ops["do_registration"] = 2
        if source_channel == "ch2" and "meanImg_chan2" in registration_ops:
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
        plane_ops["align_by_chan"] = 1
        plane_ops["nplanes"] = int(nplanes)
        plane_ops["reg_file"] = output_reg_file
        if source_channel == "ch2" and "meanImg_chan2" in registration_ops:
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

    if len(canonical_plane_dirs) > 1 and final_config.get("combined", True) and final_config.get("roidetect", True):
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


def run_srdtrans_suite2p(
    all_tif_paths,
    output_path,
    config_paths,
    srdtrans_config,
    register_with_summed_channel=False,
):
    primary_ops = load_ops_with_inferred_nplanes(config_paths[0], all_tif_paths)
    nplanes = int(primary_ops["nplanes"])
    available_channels = ["ch1"]

    effective_config_paths = list(config_paths)
    if int(primary_ops.get("nchannels", 1)) > 1:
        available_channels.append("ch2")
        if len(effective_config_paths) == 1:
            effective_config_paths = [effective_config_paths[0], effective_config_paths[0]]

    if register_with_summed_channel:
        run_shared_summed_channel_registration(all_tif_paths, output_path, effective_config_paths[0])
    else:
        run_shared_registration(all_tif_paths, output_path, effective_config_paths[0])
    apply_srdtrans_to_registered_planes(output_path, srdtrans_config, available_channels)

    if "ch2" in available_channels:
        ch2_root = os.path.join(output_path, "ch2")
        if register_with_summed_channel:
            run_final_summed_channel_registration(output_path, effective_config_paths[0])
            run_extraction_stage(output_path, ch2_root, effective_config_paths[1], nplanes)
            run_extraction_stage(output_path, output_path, effective_config_paths[0], nplanes)
        else:
            run_final_suite2p_stage(output_path, ch2_root, effective_config_paths[1], nplanes, "ch2")
            run_final_suite2p_stage(output_path, output_path, effective_config_paths[0], nplanes, "ch1")
        finalize_dual_channel_binary_layout(output_path, ch2_root, nplanes)
        return

    run_final_suite2p_stage(output_path, output_path, effective_config_paths[0], nplanes, "ch1")


def resolve_output_path(userID, expID, output_path):
    if output_path is not None:
        return output_path
    all_exp_ids = expID.split(",")
    _, _, _, exp_dir_processed, _ = paths.find_paths(userID, all_exp_ids[0])
    return exp_dir_processed


def s2p_launcher_run(
    userID,
    expID,
    tif_path,
    output_path,
    config_path,
    srdtrans_config=None,
    register_with_summed_channel=False,
):
    all_tif_paths = tif_path.split(",")
    print("tif_path = " + tif_path)
    print("ExpID = " + expID)
    print("output_path = " + output_path)
    config_paths = config_path.split(",")

    if srdtrans_config:
        run_srdtrans_suite2p(
            all_tif_paths,
            output_path,
            config_paths,
            srdtrans_config,
            register_with_summed_channel=register_with_summed_channel,
        )
        return

    if len(config_paths) == 2:
        nplanes = resolve_nplanes(config_paths[0], all_tif_paths)
        if register_with_summed_channel:
            run_shared_summed_channel_registration(all_tif_paths, output_path, config_paths[0])
        else:
            run_shared_registration(all_tif_paths, output_path, config_paths[0])
        ch2_root = os.path.join(output_path, "ch2")
        run_extraction_stage(output_path, ch2_root, config_paths[1], nplanes)
        run_extraction_stage(output_path, output_path, config_paths[0], nplanes)
        finalize_dual_channel_binary_layout(output_path, ch2_root, nplanes)
        return

    if register_with_summed_channel:
        nplanes = resolve_nplanes(config_paths[0], all_tif_paths)
        run_shared_summed_channel_registration(all_tif_paths, output_path, config_paths[0])
        run_extraction_stage(output_path, output_path, config_paths[0], nplanes)
        return

    run_single_config_suite2p(all_tif_paths, output_path, config_paths[0])


def main():
    print("** S2P Launcher Universal Run...")
    try:
        userID = sys.argv[1]
        expID = sys.argv[2]
        tif_path = sys.argv[3]
        srdtrans_config = None
        if len(sys.argv) >= 6:
            output_path = sys.argv[4]
            config_path = sys.argv[5]
            register_with_summed_channel = False
            for extra_arg in sys.argv[6:]:
                if extra_arg == "--register-with-summed-channel":
                    register_with_summed_channel = True
                else:
                    srdtrans_config = decode_srdtrans_config_arg(extra_arg)
        else:
            output_path = None
            config_path = sys.argv[4]
            register_with_summed_channel = False
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
        srdtrans_config = None
        register_with_summed_channel = False

    output_path = resolve_output_path(userID, expID, output_path)
    s2p_launcher_run(
        userID,
        expID,
        tif_path,
        output_path,
        config_path,
        srdtrans_config=srdtrans_config,
        register_with_summed_channel=register_with_summed_channel,
    )


if __name__ == "__main__":
    main()
