
# function to take habituation recording and make a summary
# includes:
# - video motion energy vs time
# - binned pupil distribution
# - move experiment to habituation folder

import sys
import cv2
import matplotlib.pyplot as plt
import numpy as np
import time
import os
import pickle
import shutil
import stat
from preprocess_pipeline.shared import paths


def count_tree_items(target_path):
    n_dirs = 0
    n_files = 0
    total_bytes = 0
    for _, dirs, files in os.walk(target_path):
        n_dirs += len(dirs)
        n_files += len(files)
        for file_name in files:
            file_path = os.path.join(_, file_name)
            try:
                total_bytes += os.path.getsize(file_path)
            except OSError:
                pass
    return n_dirs, n_files, total_bytes


def merge_tree_contents(source_path, destination_path):
    """Copy source contents into destination without restamping existing dirs."""
    for root, dirs, files in os.walk(source_path):
        relative_root = os.path.relpath(root, source_path)
        destination_root = (
            destination_path
            if relative_root == "."
            else os.path.join(destination_path, relative_root)
        )
        os.makedirs(destination_root, exist_ok=True)

        for dir_name in dirs:
            os.makedirs(os.path.join(destination_root, dir_name), exist_ok=True)

        for file_name in files:
            src_file = os.path.join(root, file_name)
            dst_file = os.path.join(destination_root, file_name)
            if (
                os.path.exists(dst_file)
                and os.path.getsize(src_file) == os.path.getsize(dst_file)
            ):
                print(f'Skipping unchanged habituation file: {dst_file}')
                continue
            print(f'Copying habituation file: {src_file} -> {dst_file}')
            shutil.copyfile(src_file, dst_file)


def apply_data_permissions_recursive(target_path):
    """Set group ownership to 'users' and grant group read/write recursively."""
    try:
        import grp
    except ImportError:
        return

    users_gid = grp.getgrnam("users").gr_gid
    skipped = []

    def _apply_permissions(path):
        current_mode = stat.S_IMODE(os.stat(path).st_mode)
        group_rw = stat.S_IRGRP | stat.S_IWGRP
        try:
            if os.path.isdir(path):
                # Directories need execute bit for group traversal/access.
                os.chmod(path, current_mode | group_rw | stat.S_IXGRP)
            else:
                os.chmod(path, current_mode | group_rw)
        except PermissionError as exc:
            skipped.append((path, f'chmod: {exc}'))

        try:
            os.chown(path, -1, users_gid)
        except PermissionError as exc:
            skipped.append((path, f'chown: {exc}'))

    _apply_permissions(target_path)
    for root, dirs, files in os.walk(target_path):
        for dir_name in dirs:
            _apply_permissions(os.path.join(root, dir_name))
        for file_name in files:
            _apply_permissions(os.path.join(root, file_name))

    if skipped:
        print(f'Habituation permission warnings: skipped {len(skipped)} operations')
        for path, message in skipped[:20]:
            print(f'  {message}: {path}')
        if len(skipped) > 20:
            print(f'  ... {len(skipped) - 20} more skipped permission operations')


def preprocess_habituate_run(userID, expID):
    print('** Starting preprocess_habituate_run...')
    animalID, remote_repository_root, \
    processed_root, exp_dir_processed, \
        exp_dir_raw = paths.find_paths(userID, expID)
    exp_dir_processed_recordings = os.path.join(processed_root, animalID, expID,'recordings')


    # Move processed experiment to /data/common/habituation/<animalID>/
    habituation_root = os.path.join('/data', 'common', 'habituation')
    habituation_animal_dir = os.path.join(habituation_root, animalID)
    os.makedirs(habituation_animal_dir, exist_ok=True)

    exp_dir_name = os.path.basename(os.path.normpath(exp_dir_processed))
    exp_dir_processed_destination = os.path.join(habituation_animal_dir, exp_dir_name)

    print(f'Habituation source: {exp_dir_processed}')
    print(f'Habituation destination: {exp_dir_processed_destination}')

    if os.path.exists(exp_dir_processed):
        src_dirs, src_files, src_bytes = count_tree_items(exp_dir_processed)
        print(
            f'Habituation source exists with {src_files} files, '
            f'{src_dirs} directories, {src_bytes} bytes'
        )
        if os.path.exists(exp_dir_processed_destination):
            dst_dirs, dst_files, dst_bytes = count_tree_items(exp_dir_processed_destination)
            print(
                f'Habituation destination already exists with {dst_files} files, '
                f'{dst_dirs} directories, {dst_bytes} bytes'
            )
            print('Merging source into existing habituation destination...')
            merge_tree_contents(exp_dir_processed, exp_dir_processed_destination)
            shutil.rmtree(exp_dir_processed)
        else:
            print('Moving processed experiment into habituation destination...')
            shutil.move(exp_dir_processed, habituation_animal_dir)
        exp_dir_processed = exp_dir_processed_destination
    elif os.path.exists(exp_dir_processed_destination):
        dst_dirs, dst_files, dst_bytes = count_tree_items(exp_dir_processed_destination)
        print(
            f'Habituation source is already absent; using existing destination with '
            f'{dst_files} files, {dst_dirs} directories, {dst_bytes} bytes'
        )
        exp_dir_processed = exp_dir_processed_destination
    else:
        raise FileNotFoundError(
            f"Processed experiment directory not found: {exp_dir_processed}"
        )

    # Match permissions and ownership to /data recursively
    print('Applying habituation permissions...')
    apply_data_permissions_recursive(exp_dir_processed)
    final_dirs, final_files, final_bytes = count_tree_items(exp_dir_processed)
    print(
        f'** Habituation processing complete: {final_files} files, '
        f'{final_dirs} directories, {final_bytes} bytes'
    )



# for debugging:
def main():
        # debug mode
        print('Parameters received via debug mode')
        # # experiment lists
        allExpIDs = ['2026-01-19_01_ESRC026']
        userID = 'adamranson'   
        
        for expID in allExpIDs:
            preprocess_habituate_run(userID, expID)    

if __name__ == "__main__":
    main()
