# these scripts are to run commands that need to be run in specific conda environments
# they should be run from the command line
# from conceivable import thread_limit
import sys
import suite2p
import organise_paths
import numpy as np
import os
import shutil


def fix_binary_permissions(save_root):
    """Ensure moved Suite2p binary files remain group-writable."""
    for dirpath, _, filenames in os.walk(save_root):
        for filename in filenames:
            if filename in {"data.bin", "data_chan2.bin"}:
                path = os.path.join(dirpath, filename)
                mode = os.stat(path).st_mode & 0o777
                os.chmod(path, mode | 0o020)

def apply_stage_overrides(ops, stage):
    """Force rigid-only or final non-rigid settings from one base config."""
    if stage == 'rigid':
        ops['nonrigid'] = False
        ops['roidetect'] = False
    elif stage == 'final':
        ops['nonrigid'] = True
        ops['roidetect'] = True
    elif stage != 'default':
        raise ValueError(f'Unknown stage: {stage}')
    return ops


def s2p_launcher_run(userID,expID,tif_path,config_path,save_path,stage='default'):
    # determine if several experiments are being run together or not:

    # # remove any existing data
    # search_str = 'string_to_search'
    # for foldername in os.listdir(exp_dir_processed):
    #     if search_str in foldername and os.path.isdir(os.path.join(exp_dir_processed, foldername)):
    #         os.rmdir(os.path.join(exp_dir_processed, foldername))
    # split tif path: if there is only one path it still outputs this as a list
    allTifPaths = tif_path.split(',')
    print('tif_path = ' + tif_path)
    allExpIDs = expID.split(',')
    print('ExpID = ' + expID)
    animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw = organise_paths.find_paths(userID, allExpIDs[0])       
    fast_disk_root = '/data/fast/s2p'
    if os.path.exists(fast_disk_root):
        shutil.rmtree(fast_disk_root)
    os.makedirs(fast_disk_root)
    # load the saved config
    ops = np.load(config_path,allow_pickle=True)
    ops = ops.item()
    ops = apply_stage_overrides(ops, stage)
    ops['save_mat'] = False
    ops['reg_tif'] = False
    ops['reg_tif_chan2'] = False
    if ops['functional_chan']==3:
        # then we are running on 2 functional channels (this is a hack to encode this info)
        db = {
            'data_path': allTifPaths,
            'save_path0': save_path,
            'fast_disk': fast_disk_root,
            }
        ops['functional_chan']=1
        suite2p.run_s2p(ops=ops, db=db)
        fix_binary_permissions(save_path)
        # run red ch
        # can be improved to avoid registering twice and making two copies of data!
        db = {
            'data_path': allTifPaths,
            'save_path0': os.path.join(save_path,'ch2'),
            'fast_disk': fast_disk_root,
            }
        ops['functional_chan']=2
        suite2p.run_s2p(ops=ops, db=db)
        fix_binary_permissions(os.path.join(save_path, 'ch2'))
    else:
        # then we are running on 1 functional channel (this is a hack to encode this info)
        # run green ch
        db = {
            'data_path': allTifPaths,
            'save_path0': os.path.join(save_path),
            'fast_disk': fast_disk_root,
            }
        suite2p.run_s2p(ops=ops, db=db)
        fix_binary_permissions(save_path)
            

# for debugging:
def main():
    print('S2P Launcher (denoiser) Run...')
    try:
        # has been run from sys command line after conda activate
        userID = sys.argv[1]
        expID = sys.argv[2]
        tif_path = sys.argv[3]
        config_path = sys.argv[4]
        final_save_path = sys.argv[5]
        try:
            stage = sys.argv[6]
        except IndexError:
            stage = 'default'
    except:
        # debug mode
        expID = '2023-02-28_13_ESMT116'
        userID = 'adamranson'
        animalID, remote_repository_root, \
            processed_root, exp_dir_processed, \
                exp_dir_raw = organise_paths.find_paths(userID, expID)
        tif_path = '/data/Remote_Repository/ESMT116/2023-02-28_13_ESMT116,/data/Remote_Repository/ESMT116/2023-02-28_14_ESMT116'
        config_path = os.path.join('/home',userID,'data/configs/s2p_configs','ch_1_depth_1.npy')

    s2p_launcher_run(userID,expID,tif_path,config_path,final_save_path,stage)

if __name__ == "__main__":
    main()
