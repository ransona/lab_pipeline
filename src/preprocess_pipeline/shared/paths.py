import os
from contextlib import contextmanager


LOCAL_REPOSITORY_ROOT_ENV = "LAB_PIPELINE_LOCAL_REPOSITORY_ROOT"
LOCAL_RAW_REPOSITORY_ROOT_ENV = "LAB_PIPELINE_LOCAL_RAW_REPOSITORY_ROOT"
LOCAL_PROCESSED_REPOSITORY_ROOT_ENV = "LAB_PIPELINE_LOCAL_PROCESSED_REPOSITORY_ROOT"
LOCAL_NAS_REPOSITORY_ROOT_ENV = "LAB_PIPELINE_LOCAL_NAS_REPOSITORY_ROOT"


def get_local_repository_root(local_repository_root=None):
    if local_repository_root:
        return os.path.abspath(str(local_repository_root))
    env_value = os.environ.get(LOCAL_REPOSITORY_ROOT_ENV)
    if env_value:
        return os.path.abspath(env_value)
    return None


def get_local_path_roots(
    local_repository_root=None,
    local_raw_repository_root=None,
    local_processed_repository_root=None,
    local_nas_repository_root=None,
):
    legacy_root = get_local_repository_root(local_repository_root)
    raw_root = (
        os.path.abspath(str(local_raw_repository_root))
        if local_raw_repository_root
        else os.environ.get(LOCAL_RAW_REPOSITORY_ROOT_ENV)
    )
    processed_root = (
        os.path.abspath(str(local_processed_repository_root))
        if local_processed_repository_root
        else os.environ.get(LOCAL_PROCESSED_REPOSITORY_ROOT_ENV)
    )
    nas_root = (
        os.path.abspath(str(local_nas_repository_root))
        if local_nas_repository_root
        else os.environ.get(LOCAL_NAS_REPOSITORY_ROOT_ENV)
    )

    if raw_root:
        raw_root = os.path.abspath(raw_root)
    if processed_root:
        processed_root = os.path.abspath(processed_root)
    if nas_root:
        nas_root = os.path.abspath(nas_root)

    if legacy_root and not raw_root:
        raw_root = legacy_root
    if legacy_root and not processed_root:
        processed_root = legacy_root

    return raw_root, processed_root, nas_root


@contextmanager
def local_repository_context(
    local_repository_root=None,
    local_raw_repository_root=None,
    local_processed_repository_root=None,
    local_nas_repository_root=None,
):
    root = get_local_repository_root(local_repository_root)
    raw_root, processed_root, nas_root = get_local_path_roots(
        local_repository_root=local_repository_root,
        local_raw_repository_root=local_raw_repository_root,
        local_processed_repository_root=local_processed_repository_root,
        local_nas_repository_root=local_nas_repository_root,
    )
    previous_values = {
        LOCAL_REPOSITORY_ROOT_ENV: os.environ.get(LOCAL_REPOSITORY_ROOT_ENV),
        LOCAL_RAW_REPOSITORY_ROOT_ENV: os.environ.get(LOCAL_RAW_REPOSITORY_ROOT_ENV),
        LOCAL_PROCESSED_REPOSITORY_ROOT_ENV: os.environ.get(LOCAL_PROCESSED_REPOSITORY_ROOT_ENV),
        LOCAL_NAS_REPOSITORY_ROOT_ENV: os.environ.get(LOCAL_NAS_REPOSITORY_ROOT_ENV),
    }
    try:
        if root:
            os.environ[LOCAL_REPOSITORY_ROOT_ENV] = root
        if raw_root:
            os.environ[LOCAL_RAW_REPOSITORY_ROOT_ENV] = raw_root
        if processed_root:
            os.environ[LOCAL_PROCESSED_REPOSITORY_ROOT_ENV] = processed_root
        if nas_root:
            os.environ[LOCAL_NAS_REPOSITORY_ROOT_ENV] = nas_root
        yield {
            "legacy_root": root,
            "raw_root": raw_root,
            "processed_root": processed_root,
            "nas_root": nas_root,
        }
    finally:
        for env_name, previous in previous_values.items():
            if previous is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = previous


def find_paths(
    userID,
    expID,
    local_repository_root=None,
    local_raw_repository_root=None,
    local_processed_repository_root=None,
    local_nas_repository_root=None,
):
    animalID = expID[14:]
    raw_root, local_processed_root, nas_root = get_local_path_roots(
        local_repository_root=local_repository_root,
        local_raw_repository_root=local_raw_repository_root,
        local_processed_repository_root=local_processed_repository_root,
        local_nas_repository_root=local_nas_repository_root,
    )
    if raw_root or local_processed_root:
        remote_repository_root = nas_root or raw_root or local_processed_root
        processed_root = local_processed_root or raw_root
        exp_dir_processed = os.path.join(processed_root, animalID, expID)
        raw_candidate = os.path.join(raw_root, animalID, expID) if raw_root else None
        nas_candidate = os.path.join(nas_root, animalID, expID) if nas_root else None
        if raw_candidate and os.path.exists(raw_candidate):
            exp_dir_raw = raw_candidate
        elif nas_candidate:
            exp_dir_raw = nas_candidate
        elif raw_candidate:
            exp_dir_raw = raw_candidate
        else:
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


def raw_file_path(userID, expID, *parts, exp_dir_raw=None):
    if exp_dir_raw is None:
        _, _, _, _, exp_dir_raw = find_paths(userID, expID)
    local_path = os.path.join(exp_dir_raw, *parts)
    if os.path.exists(local_path):
        return local_path

    _, _, nas_root = get_local_path_roots()
    if nas_root:
        animalID = expID[14:]
        nas_path = os.path.join(nas_root, animalID, expID, *parts)
        if os.path.exists(nas_path):
            return nas_path
    return local_path
