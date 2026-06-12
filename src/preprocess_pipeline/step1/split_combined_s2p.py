import glob
import os
import shutil
import sys

import numpy as np

from preprocess_pipeline.shared import paths


SPINES_GUI_ARTIFACT_PATTERNS = [
    "*conversion*.npy",
    "extraction_*.txt",
    "*mode*.npy",
]


def ensure_numpy_core_pickle_compat():
    """Allow NumPy 1.x environments to read object arrays saved by NumPy 2.x."""
    if "numpy._core" in sys.modules:
        return
    try:
        import numpy.core as numpy_core

        sys.modules.setdefault("numpy._core", numpy_core)
        for module_name in ("multiarray", "numeric", "fromnumeric", "shape_base", "_methods"):
            try:
                module = __import__(f"numpy.core.{module_name}", fromlist=["*"])
            except Exception:
                continue
            sys.modules.setdefault(f"numpy._core.{module_name}", module)
    except Exception:
        return


def load_npy(path, **kwargs):
    ensure_numpy_core_pickle_compat()
    return np.load(path, **kwargs)


def split_combined_suite2p():
    userID = "adamranson"
    expID = "2024-07-12_01_ESMT170"  # <--- put the first experiment of the sequence here
    split_combined_suite2p_for_experiment(userID, expID)


def split_combined_suite2p_for_experiment(userID, expID):
    (
        animalID,
        remote_repository_root,
        processed_root,
        exp_dir_processed,
        exp_dir_raw,
    ) = paths.find_paths(userID, expID)

    if not os.path.exists(exp_dir_processed):
        raise FileNotFoundError(f"Processed folder does not exist: {exp_dir_processed}")

    split_roots = discover_split_roots(exp_dir_processed)
    if len(split_roots) == 0:
        raise FileNotFoundError(f"No Suite2p roots found under {exp_dir_processed}")

    for split_root in split_roots:
        split_combined_root(userID, split_root)


def discover_split_roots(exp_dir_processed):
    """Auto-detect standard vs mesoscope layouts.

    Mesoscope mode is detected by the presence of a P* folder with an R* folder inside it.
    Returns a list of root directories that directly contain suite2p/ and optionally ch2/.
    """
    meso_roots = []
    for p_dir in sorted(glob.glob(os.path.join(exp_dir_processed, "P*"))):
        if not os.path.isdir(p_dir):
            continue
        roi_dirs = sorted(
            roi_dir
            for roi_dir in glob.glob(os.path.join(p_dir, "R*"))
            if os.path.isdir(roi_dir)
        )
        if roi_dirs:
            meso_roots.extend(roi_dirs)

    if meso_roots:
        return meso_roots

    return [exp_dir_processed]


def split_combined_root(userID, split_root):
    combined_bins_to_delete = []
    for channel_root in discover_channel_roots(split_root):
        combined_bins_to_delete.extend(split_combined_channel(userID, split_root, channel_root))
    delete_combined_bins_after_success(combined_bins_to_delete)


def discover_channel_roots(split_root):
    channel_roots = [split_root]
    ch2_root = os.path.join(split_root, "ch2")
    if os.path.isdir(ch2_root):
        channel_roots.append(ch2_root)
    return channel_roots


def split_combined_channel(userID, split_root, channel_root):
    suite2p_path = os.path.join(channel_root, "suite2p")
    suite2p_combined_path = os.path.join(channel_root, "suite2p_combined")

    if not os.path.exists(suite2p_combined_path):
        if not os.path.exists(suite2p_path):
            raise FileNotFoundError(f"Missing suite2p folder: {suite2p_path}")
        os.rename(suite2p_path, suite2p_combined_path)

    plane_dirs = sorted(glob.glob(os.path.join(suite2p_combined_path, "plane*")))
    if len(plane_dirs) == 0:
        raise FileNotFoundError(f"No plane folders found in {suite2p_combined_path}")

    plane0_ops = load_plane_metadata(plane_dirs[0])
    layout_mode = infer_layout_mode_from_split_root(split_root)
    source_data_paths = get_source_data_paths(plane0_ops, plane_dirs[0])
    exp_ids = [extract_exp_id_from_data_path(path, layout_mode) for path in source_data_paths]
    animal_ids = [exp_id[14:] for exp_id in exp_ids]
    if len(set(animal_ids)) > 1:
        raise Exception("Combined multiple animals not permitted")

    is_ch2 = os.path.basename(channel_root) == "ch2"
    split_suffix = split_root[len(base_processed_root(split_root)) :].lstrip(os.sep)
    combined_bins_to_delete = []

    for plane_dir in plane_dirs:
        plane_name = os.path.basename(plane_dir)
        print(f"Plane {plane_name}")

        plane_ops = load_plane_metadata(plane_dir)
        plane_db = load_optional_plane_dict(plane_dir, "db.npy")
        plane_settings = load_optional_plane_dict(plane_dir, "settings.npy")
        frames_per_folder = get_frames_per_folder(plane_ops, plane_dir, len(exp_ids))
        F = load_npy(os.path.join(plane_dir, "F.npy"))
        Fneu = load_npy(os.path.join(plane_dir, "Fneu.npy"))
        spks = load_npy(os.path.join(plane_dir, "spks.npy"))
        iscell = load_npy(os.path.join(plane_dir, "iscell.npy"))
        stat = load_npy(os.path.join(plane_dir, "stat.npy"), allow_pickle=True)

        for iExp, exp_id in enumerate(exp_ids):
            frames_in_exp = int(frames_per_folder[iExp])
            exp_start_frame = int(np.sum(frames_per_folder[:iExp]))
            exp_end_frame = exp_start_frame + frames_in_exp

            F_exp = F[:, exp_start_frame:exp_end_frame]
            Fneu_exp = Fneu[:, exp_start_frame:exp_end_frame]
            spks_exp = spks[:, exp_start_frame:exp_end_frame]

            (
                animalID2,
                remote_repository_root2,
                processed_root2,
                exp_dir_processed2,
                exp_dir_raw2,
            ) = paths.find_paths(userID, exp_id)
            dest_split_root = map_destination_root(
                exp_dir_processed2=exp_dir_processed2,
                split_suffix=split_suffix,
            )
            dest_channel_root = get_dest_channel_root(dest_split_root, is_ch2)
            dest_plane_dir = os.path.join(dest_channel_root, "suite2p", plane_name)
            os.makedirs(dest_plane_dir, exist_ok=True)

            print("Cropping and saving cell traces...")
            np.save(os.path.join(dest_plane_dir, "F.npy"), F_exp)
            np.save(os.path.join(dest_plane_dir, "Fneu.npy"), Fneu_exp)
            np.save(os.path.join(dest_plane_dir, "spks.npy"), spks_exp)
            np.save(os.path.join(dest_plane_dir, "iscell.npy"), iscell)
            np.save(os.path.join(dest_plane_dir, "stat.npy"), stat)

            print("Cropping and saving binary file (registered frames)...")
            source_bin = os.path.join(plane_dir, "data.bin")
            dest_bin = os.path.join(dest_plane_dir, "data.bin")
            split_s2p_vid(
                path_to_source_bin=source_bin,
                path_to_dest_bin=dest_bin,
                Ly=int(plane_ops["Ly"]),
                Lx=int(plane_ops["Lx"]),
                start_frame=exp_start_frame,
                frames_to_copy=frames_in_exp,
            )
            validate_split_bin_size(
                path_to_dest_bin=dest_bin,
                Ly=int(plane_ops["Ly"]),
                Lx=int(plane_ops["Lx"]),
                frames_to_copy=frames_in_exp,
            )

            split_ops = rewrite_ops_for_split(
                plane_ops=plane_ops,
                exp_dir_raw=exp_dir_raw2,
                dest_channel_root=dest_channel_root,
                dest_plane_dir=dest_plane_dir,
                frames_in_exp=frames_in_exp,
            )
            np.save(os.path.join(dest_plane_dir, "ops.npy"), split_ops)
            if plane_db:
                split_db = rewrite_ops_for_split(
                    plane_ops=plane_db,
                    exp_dir_raw=exp_dir_raw2,
                    dest_channel_root=dest_channel_root,
                    dest_plane_dir=dest_plane_dir,
                    frames_in_exp=frames_in_exp,
                )
                split_db["db_path"] = os.path.join(dest_plane_dir, "db.npy")
                split_db["settings_path"] = os.path.join(dest_plane_dir, "settings.npy")
                np.save(split_db["db_path"], split_db)
            if plane_settings:
                np.save(os.path.join(dest_plane_dir, "settings.npy"), plane_settings)

        combined_bins_to_delete.append(os.path.join(plane_dir, "data.bin"))

    for exp_id in exp_ids:
        (
            animalID2,
            remote_repository_root2,
            processed_root2,
            exp_dir_processed2,
            exp_dir_raw2,
        ) = paths.find_paths(userID, exp_id)
        dest_split_root = map_destination_root(
            exp_dir_processed2=exp_dir_processed2,
            split_suffix=split_suffix,
        )
        dest_channel_root = get_dest_channel_root(dest_split_root, is_ch2)
        copy_spines_gui_artifacts(suite2p_combined_path, dest_channel_root)
        set_permissions(os.path.join(dest_channel_root, "suite2p"))

    return combined_bins_to_delete


def infer_layout_mode_from_split_root(split_root):
    rel_parts = os.path.relpath(split_root, base_processed_root(split_root)).split(os.sep)
    if len(rel_parts) >= 2 and rel_parts[0].startswith("P") and rel_parts[1].startswith("R"):
        return "meso"
    return "standard"


def base_processed_root(split_root):
    parts = os.path.normpath(split_root).split(os.sep)
    if len(parts) >= 2 and parts[-2].startswith("P") and parts[-1].startswith("R"):
        return os.sep.join(parts[:-2]) or os.sep
    return split_root


def extract_exp_id_from_data_path(data_path, layout_mode):
    data_path = os.fspath(data_path)
    if layout_mode == "meso":
        return os.path.basename(os.path.dirname(os.path.dirname(data_path)))
    return os.path.basename(data_path)


def map_destination_root(exp_dir_processed2, split_suffix):
    if split_suffix:
        return os.path.join(exp_dir_processed2, split_suffix)
    return exp_dir_processed2


def get_dest_channel_root(dest_split_root, is_ch2):
    if is_ch2:
        return os.path.join(dest_split_root, "ch2")
    return dest_split_root


def copy_spines_gui_artifacts(suite2p_combined_path, dest_channel_root):
    source_dir = os.path.join(suite2p_combined_path, "SpinesGUI")
    if not os.path.isdir(source_dir):
        return

    dest_dir = os.path.join(dest_channel_root, "suite2p", "SpinesGUI")
    os.makedirs(dest_dir, exist_ok=True)

    copied = 0
    for pattern in SPINES_GUI_ARTIFACT_PATTERNS:
        for source_path in sorted(glob.glob(os.path.join(source_dir, pattern))):
            if not os.path.isfile(source_path):
                continue
            shutil.copy2(source_path, os.path.join(dest_dir, os.path.basename(source_path)))
            copied += 1

    if copied:
        print(f"Copied {copied} SpinesGUI artifact(s) to {dest_dir}")


def load_optional_plane_dict(plane_dir, filename):
    path = os.path.join(plane_dir, filename)
    if not os.path.exists(path):
        return {}
    value = load_npy(path, allow_pickle=True).item()
    if not isinstance(value, dict):
        raise TypeError(f"Expected {path} to contain a dict, got {type(value).__name__}")
    return value


def load_plane_metadata(plane_dir):
    ops = load_optional_plane_dict(plane_dir, "ops.npy")
    if not ops:
        raise FileNotFoundError(f"Missing ops.npy in {plane_dir}")
    db = load_optional_plane_dict(plane_dir, "db.npy")
    merged = dict(db)
    merged.update(ops)
    return merged


def get_source_data_paths(plane_metadata, plane_dir):
    data_paths = plane_metadata.get("data_path")
    if data_paths is None:
        raise KeyError(f"Missing data_path in Suite2p metadata for {plane_dir}")
    if isinstance(data_paths, (str, os.PathLike)):
        data_paths = [data_paths]
    return [os.fspath(data_path) for data_path in data_paths]


def get_frames_per_folder(plane_metadata, plane_dir, expected_count):
    frames_per_folder = plane_metadata.get("frames_per_folder")
    if frames_per_folder is None or len(frames_per_folder) == 0:
        frames_per_folder = plane_metadata.get("frames_per_file")
    if frames_per_folder is None or len(frames_per_folder) == 0:
        if expected_count == 1 and plane_metadata.get("nframes") is not None:
            frames_per_folder = [int(plane_metadata["nframes"])]
        else:
            raise KeyError(f"Missing frames_per_folder in Suite2p metadata for {plane_dir}")
    frames_per_folder = np.asarray(frames_per_folder, dtype=np.int64)
    if len(frames_per_folder) != expected_count:
        raise ValueError(
            f"Suite2p metadata mismatch for {plane_dir}: data_path has {expected_count} "
            f"source experiment(s), frames_per_folder has {len(frames_per_folder)} value(s)"
        )
    return frames_per_folder


def rewrite_ops_for_split(plane_ops, exp_dir_raw, dest_channel_root, dest_plane_dir, frames_in_exp):
    split_ops = plane_ops.copy()
    split_ops["data_path"] = [exp_dir_raw]
    split_ops["save_path0"] = dest_channel_root
    split_ops["save_path"] = dest_plane_dir
    split_ops["ops_path"] = os.path.join(dest_plane_dir, "ops.npy")
    split_ops["reg_file"] = os.path.join(dest_plane_dir, "data.bin")
    split_ops["nframes"] = int(frames_in_exp)
    split_ops["frames_per_folder"] = np.array([int(frames_in_exp)], dtype=np.int32)
    split_ops["frames_per_file"] = np.array([int(frames_in_exp)], dtype=np.int32)

    for key in [
        "reg_file_chan2",
        "reg_file_raw",
        "reg_file_raw_chan2",
        "raw_file",
        "raw_file_chan2",
    ]:
        if key in split_ops:
            del split_ops[key]

    return split_ops


def set_permissions(path):
    try:
        import grp

        group_id = grp.getgrnam("users").gr_gid
        mode = 0o770
        for root, dirs, files in os.walk(path):
            for dirname in dirs:
                dir_path = os.path.join(root, dirname)
                os.chown(dir_path, -1, group_id)
                os.chmod(dir_path, mode)
            for filename in files:
                file_path = os.path.join(root, filename)
                os.chown(file_path, -1, group_id)
                os.chmod(file_path, mode)
    except Exception:
        print("Problem setting file permissions to user in step 1 batch")


def split_s2p_vid(path_to_source_bin, path_to_dest_bin, Ly, Lx, start_frame, frames_to_copy):
    block_size = 1000
    bytes_per_frame = Ly * Lx * 2

    with open(path_to_source_bin, "rb") as fid, open(path_to_dest_bin, "wb") as fid2:
        fid.seek(int(bytes_per_frame * start_frame))

        frames_written = 0
        while frames_written < frames_to_copy:
            frames_to_read = min(block_size, frames_to_copy - frames_written)
            print(
                f"Frame {start_frame + frames_written}-{start_frame + frames_written + frames_to_read - 1}"
            )
            read_data = np.fromfile(fid, dtype=np.int16, count=Ly * Lx * frames_to_read)
            expected_values = Ly * Lx * frames_to_read
            if read_data.size != expected_values:
                raise IOError(
                    f"Could not read requested split frames from {path_to_source_bin}: "
                    f"expected {expected_values} int16 values, got {read_data.size}"
                )
            read_data.tofile(fid2)
            frames_written += frames_to_read


def validate_split_bin_size(path_to_dest_bin, Ly, Lx, frames_to_copy):
    expected_bytes = int(Ly) * int(Lx) * int(frames_to_copy) * np.dtype(np.int16).itemsize
    actual_bytes = os.path.getsize(path_to_dest_bin)
    if actual_bytes != expected_bytes:
        raise IOError(
            f"Split binary size mismatch for {path_to_dest_bin}: "
            f"expected {expected_bytes} bytes, got {actual_bytes}"
        )


def delete_combined_bins_after_success(bin_paths):
    deleted = 0
    bytes_deleted = 0
    for bin_path in bin_paths:
        if not os.path.isfile(bin_path):
            continue
        file_size = os.path.getsize(bin_path)
        os.remove(bin_path)
        deleted += 1
        bytes_deleted += file_size
        print(f"Deleted original combined binary: {bin_path}")
    if deleted:
        print(f"Deleted {deleted} combined binary file(s), freeing {bytes_deleted} bytes.")


def main():
    split_combined_suite2p()


if __name__ == "__main__":
    main()
