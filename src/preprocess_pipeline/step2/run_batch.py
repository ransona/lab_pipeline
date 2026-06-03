import grp
import os
import pickle
import runpy
import sys

from preprocess_pipeline.shared import paths
from preprocess_pipeline.step2 import runtime

def run_step2_batch(step2_config):
    userID = step2_config['userID']
    expIDs = step2_config['expIDs']
    local_repository_root = step2_config.get('local_repository_root')
    local_raw_repository_root = step2_config.get('local_raw_repository_root')
    local_processed_repository_root = step2_config.get('local_processed_repository_root')
    local_nas_repository_root = step2_config.get('local_nas_repository_root')
    local_mode = bool(
        local_repository_root
        or local_raw_repository_root
        or local_processed_repository_root
        or local_nas_repository_root
    )

    # options
    pre_secs = step2_config['pre_secs']
    post_secs = step2_config['post_secs']
    run_bonvision = step2_config['run_bonvision']
    run_s2p_timestamp = step2_config['run_s2p_timestamp']
    run_ephys = step2_config['run_ephys']
    run_dlc_timestamp = step2_config['run_dlc_timestamp']
    run_cuttraces = step2_config['run_cuttraces']

    with paths.local_repository_context(
        local_repository_root=local_repository_root,
        local_raw_repository_root=local_raw_repository_root,
        local_processed_repository_root=local_processed_repository_root,
        local_nas_repository_root=local_nas_repository_root,
    ):
        for expID in expIDs:
            print('** Starting expID...' + expID)
            # save step2 ops to exp dir
            animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw = paths.find_paths(userID, expID)
            with open(os.path.join(exp_dir_processed,'step2_config.pickle'), 'wb') as f: pickle.dump(step2_config, f)  
            # final ops are presecs, post secs and whether to process: 1.bonvision, 2.s2p_timestamp, 3.ephys, 4.dlc_timestamp, 5.cutraces
            runtime.run_preprocess_step2(
                userID,expID, pre_secs, post_secs, run_bonvision, run_s2p_timestamp,
                run_ephys, run_dlc_timestamp, run_cuttraces
            )
            
            if local_mode or os.name == 'nt':
                continue

            # set permissions all files generated to user; improve this later
            animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw = paths.find_paths(userID, expID)
            path = exp_dir_processed
            group_id = grp.getgrnam('users').gr_gid
            mode = 0o770
            # set root exp dir
            try:
                os.chown(path, -1, group_id)
                os.chmod(path, mode)
            except:
                x=0

            for root, dirs, files in os.walk(path):
                for d in dirs:
                    try:
                        dir_path = os.path.join(root, d)
                        os.chown(dir_path, -1, group_id)
                        os.chmod(dir_path, mode)
                    except:
                        x=0
                for f in files:
                    try:
                        file_path = os.path.join(root, f)
                        os.chown(file_path, -1, group_id)
                        os.chmod(file_path, mode)
                    except:
                        x=0


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m preprocess_pipeline.step2.run_batch <config.py>")
    config_globals = runpy.run_path(sys.argv[1])
    if 'step2_config' not in config_globals:
        raise KeyError(f"Config file did not define step2_config: {sys.argv[1]}")
    run_step2_batch(config_globals['step2_config'])


if __name__ == "__main__":
    main()
