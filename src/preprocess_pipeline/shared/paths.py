import os
from contextlib import contextmanager


LOCAL_REPOSITORY_ROOT_ENV = "LAB_PIPELINE_LOCAL_REPOSITORY_ROOT"


def get_local_repository_root(local_repository_root=None):
    if local_repository_root:
        return os.path.abspath(str(local_repository_root))
    env_value = os.environ.get(LOCAL_REPOSITORY_ROOT_ENV)
    if env_value:
        return os.path.abspath(env_value)
    return None


@contextmanager
def local_repository_context(local_repository_root=None):
    root = get_local_repository_root(local_repository_root)
    previous = os.environ.get(LOCAL_REPOSITORY_ROOT_ENV)
    try:
        if root:
            os.environ[LOCAL_REPOSITORY_ROOT_ENV] = root
        yield root
    finally:
        if previous is None:
            os.environ.pop(LOCAL_REPOSITORY_ROOT_ENV, None)
        else:
            os.environ[LOCAL_REPOSITORY_ROOT_ENV] = previous


def find_paths(userID, expID, local_repository_root=None):
    animalID = expID[14:]
    local_root = get_local_repository_root(local_repository_root)
    if local_root:
        remote_repository_root = local_root
        processed_root = local_root
        exp_dir_processed = os.path.join(processed_root, animalID, expID)
        exp_dir_raw = exp_dir_processed
        return animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw
    # Keep this root constant for all users.
    remote_repository_root = os.path.join('/data/Remote_Repository')
    if str(userID).lower() == 'habit':
        # Habituation data lives under a shared path per animal.
        processed_root = os.path.join('/data/common/habituation')
        exp_dir_processed = os.path.join(processed_root, animalID, expID)
        exp_dir_raw = exp_dir_processed
    else:
        # path to root of processed data
        processed_root = os.path.join('/home/',userID,'data/Repository')
        # complete path to processed experiment data
        exp_dir_processed = os.path.join(processed_root, animalID, expID)
        # complete path to raw experiment data (usually hosted on gdrive)
        exp_dir_raw = os.path.join(remote_repository_root, animalID, expID)
    return animalID, remote_repository_root, processed_root, exp_dir_processed,exp_dir_raw
