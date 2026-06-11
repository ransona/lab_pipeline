from datetime import datetime
import getpass
import json
import os
import pickle
import runpy
import sys

from preprocess_pipeline.shared import matrix_notify, paths
from preprocess_pipeline.step1 import runtime


CONFIG_ROOT = '/data/common/configs/s2p_configs'
LOCAL_CONFIG_ROOT_ENV = 'LAB_PIPELINE_S2P_CONFIG_ROOT'
WINDOWS_LOCAL_CONFIG_ROOT = r'F:\s2p_ops'
DEFAULT_QUEUE_PATH = '/data/common/queues/step1'
DEBUG_QUEUE_PATH = '/data/common/queues/debug'
VALID_CHAN2_DETECTION_MODES = {'off', 'intensity', 'cellpose'}
QUEUE_PATHS_BY_HOST = {
    'server': DEFAULT_QUEUE_PATH,
    'ar-lab-si2': '/data/common/local_pipelines/ar-lab-si2/queues/step1',
    'AdamDellXPS15': '/data/common/local_pipelines/AdamDellXPS15/queues/step1',
}


def _normalize_config_entry(config_entry, default_functional_chan=None):
    if isinstance(config_entry, str):
        return {
            'config': config_entry,
            'functional_chan': int(default_functional_chan or 1),
            'chan2_detection': 'off',
        }
    if isinstance(config_entry, dict):
        config_name = (
            config_entry.get('config')
            or config_entry.get('path')
            or config_entry.get('name')
        )
        if not isinstance(config_name, str) or not config_name:
            raise ValueError('suite2p config entries must include a config filename')
        functional_chan = config_entry.get('functional_chan', default_functional_chan or 1)
        chan2_detection = config_entry.get('chan2_detection', 'off')
        chan2_detection = str(chan2_detection).lower()
        if chan2_detection not in VALID_CHAN2_DETECTION_MODES:
            raise ValueError(
                "chan2_detection must be one of: "
                + ", ".join(sorted(VALID_CHAN2_DETECTION_MODES))
            )
        return {
            'config': config_name,
            'functional_chan': int(functional_chan),
            'chan2_detection': chan2_detection,
        }
    raise TypeError('suite2p config entries must be strings or dicts')


def _normalize_single_config_value(config_value):
    if isinstance(config_value, str):
        return [_normalize_config_entry(config_value, 1)]
    if isinstance(config_value, dict) and any(
        key in config_value for key in ('config', 'path', 'name', 'functional_chan', 'chan2_detection')
    ):
        return [_normalize_config_entry(config_value, 1)]
    if isinstance(config_value, (list, tuple)):
        config_list = list(config_value)
        if len(config_list) not in (1, 2):
            raise ValueError(
                'suite2p config values must be a string or contain 1 or 2 config filenames'
            )
        return [
            _normalize_config_entry(item, index + 1)
            for index, item in enumerate(config_list)
        ]
    raise TypeError(
        'suite2p_config must be a string, a 1/2-item list, or a mapping of work units'
    )


def _is_meso_root(exp_dir_raw):
    for entry in sorted(os.listdir(exp_dir_raw)):
        scanpath_root = os.path.join(exp_dir_raw, entry)
        if not entry.startswith('P') or not os.path.isdir(scanpath_root):
            continue
        for roi_entry in sorted(os.listdir(scanpath_root)):
            roi_root = os.path.join(scanpath_root, roi_entry)
            if roi_entry.startswith('R') and os.path.isdir(roi_root):
                return True
    return False


def _discover_work_unit_ids(exp_dir_raw):
    if not _is_meso_root(exp_dir_raw):
        return 'standard', ['root']

    work_unit_ids = []
    for scanpath in sorted(os.listdir(exp_dir_raw)):
        scanpath_root = os.path.join(exp_dir_raw, scanpath)
        if not scanpath.startswith('P') or not os.path.isdir(scanpath_root):
            continue
        if scanpath not in {'P1', 'P2'}:
            raise ValueError(
                f'Universal pipeline currently supports only P1/P2 mesoscope scanpaths, found {scanpath}'
            )
        for roi in sorted(os.listdir(scanpath_root)):
            roi_root = os.path.join(scanpath_root, roi)
            if roi.startswith('R') and os.path.isdir(roi_root):
                work_unit_ids.append(os.path.join(scanpath, roi))
    if not work_unit_ids:
        raise ValueError(f'No mesoscope ROI folders found in {exp_dir_raw}')
    return 'meso', work_unit_ids


def _validate_combined_work_units(user_id, exp_id_group, expected_topology, expected_work_unit_ids):
    for exp_id in exp_id_group[1:]:
        _, _, _, _, exp_dir_raw = paths.find_paths(user_id, exp_id)
        topology, work_unit_ids = _discover_work_unit_ids(exp_dir_raw)
        if topology != expected_topology:
            raise ValueError(
                f'Combined experiment {exp_id} has topology {topology}, expected {expected_topology}'
            )
        if work_unit_ids != expected_work_unit_ids:
            raise ValueError(
                'Combined experiments do not share the same mesoscope work units. '
                f'Expected {expected_work_unit_ids}, got {work_unit_ids} for {exp_id}'
            )


def _normalize_suite2p_plan(suite2p_config, work_unit_ids):
    if isinstance(suite2p_config, (str, list, tuple)) or (
        isinstance(suite2p_config, dict)
        and any(key in suite2p_config for key in ('config', 'path', 'name', 'functional_chan', 'chan2_detection'))
    ):
        default_configs = _normalize_single_config_value(suite2p_config)
        return [
            {'work_unit': work_unit_id, 'suite2p_configs': [dict(item) for item in default_configs]}
            for work_unit_id in work_unit_ids
        ]

    if not isinstance(suite2p_config, dict):
        raise TypeError(
            'suite2p_config must be a string, a 1/2-item list, or a dict mapping work units'
        )

    if 'default' in suite2p_config or 'overrides' in suite2p_config:
        default_value = suite2p_config.get('default')
        overrides = suite2p_config.get('overrides', {})
        if default_value is None and not overrides:
            raise ValueError('suite2p_config mapping must provide default and/or overrides')
    else:
        default_value = None
        overrides = suite2p_config

    if not isinstance(overrides, dict):
        raise TypeError('suite2p_config overrides must be a dict keyed by work unit')

    unknown_work_units = set(overrides.keys()) - set(work_unit_ids)
    if unknown_work_units:
        raise ValueError(
            'suite2p_config overrides refer to unknown work units: '
            + ', '.join(sorted(unknown_work_units))
        )

    plan = []
    default_configs = (
        _normalize_single_config_value(default_value) if default_value is not None else None
    )
    for work_unit_id in work_unit_ids:
        if work_unit_id in overrides:
            configs = _normalize_single_config_value(overrides[work_unit_id])
        elif default_configs is not None:
            configs = [dict(item) for item in default_configs]
        else:
            raise ValueError(f'No suite2p config provided for work unit {work_unit_id}')
        plan.append({'work_unit': work_unit_id, 'suite2p_configs': configs})
    return plan


def _suite2p_config_root(step1_config=None, local_mode=False):
    if step1_config and step1_config.get('suite2p_config_root'):
        return step1_config['suite2p_config_root']
    env_root = os.environ.get(LOCAL_CONFIG_ROOT_ENV)
    if env_root:
        return env_root
    if local_mode and os.name == 'nt':
        return WINDOWS_LOCAL_CONFIG_ROOT
    return CONFIG_ROOT


def _validate_plan_configs(user_id, suite2p_plan, runs2p, config_root=CONFIG_ROOT):
    if not runs2p:
        return
    for plan_item in suite2p_plan:
        for config_entry in plan_item['suite2p_configs']:
            config_name = config_entry['config'] if isinstance(config_entry, dict) else config_entry
            config_path = os.path.join(config_root, user_id, config_name)
            if not os.path.exists(config_path):
                raise FileNotFoundError(
                    'The suite2p config file does not exist: ' + config_path
                )


def _queue_path_for_host(run_on):
    if run_on not in QUEUE_PATHS_BY_HOST:
        raise ValueError(f'Unknown run_on target: {run_on}')
    return QUEUE_PATHS_BY_HOST[run_on]


def _resolve_queue_path(run_on, queue_name):
    if queue_name == 'debug':
        return DEBUG_QUEUE_PATH
    if queue_name not in (None, 'step1'):
        raise ValueError(f'Unknown queue target: {queue_name}')
    return _queue_path_for_host(run_on)


def _build_command(command_filename, user_id, exp_id, runs2p, rundlc, runfitpupil):
    return (
        'preprocess_pipeline.step1.runtime.run_preprocess_step1_universal('
        f'"{command_filename}","{user_id}","{exp_id}",'
        f'{runs2p},{rundlc},{runfitpupil})'
    )


def _queue_single_job(
    command_filename,
    queue_path,
    user_id,
    exp_id,
    command,
    config,
):
    queued_command = {
        'job_type': 'step1_universal',
        'command': command,
        'userID': user_id,
        'expID': exp_id,
        'config': config,
    }
    os.makedirs(queue_path, exist_ok=True)
    with open(os.path.join(queue_path, command_filename), 'wb') as f:
        pickle.dump(queued_command, f)
    return queued_command


def _notify_queue_position(user_id, exp_label, queue_path):
    files = [file for file in os.listdir(queue_path) if file.endswith('.pickle')]
    try:
        matrix_notify.main(user_id, 'Added ' + exp_label + ' to queue in position ' + str(len(files)))
    except Exception:
        print('Error sending matrix message')


def _command_filename(now, user_id, exp_id, jump_queue):
    if jump_queue:
        prefix = now.strftime('00_00_00_00_00_00')
    else:
        prefix = now.strftime('%Y_%m_%d_%H_%M_%S')
    return f'{prefix}_{user_id}_{exp_id}.pickle'


def run_step1_batch_universal(step1_config):
    user_id = step1_config['userID']
    exp_ids = step1_config['expIDs']
    suite2p_config = step1_config['suite2p_config']
    runs2p = step1_config['runs2p']
    rundlc = step1_config['rundlc']
    runfitpupil = step1_config['runfitpupil']
    runsrdtrans = step1_config.get('runsrdtrans', False)
    srdtrans_config = step1_config.get('srdtrans')
    runhabituate = step1_config.get('runhabituate', False)
    settings = step1_config.get('settings', False)
    jump_queue = step1_config.get('jump_queue', False)
    run_on = step1_config.get('run_on', 'server')
    queue_name = step1_config.get('queue', 'step1')
    local_repository_root = step1_config.get('local_repository_root')
    local_raw_repository_root = step1_config.get('local_raw_repository_root')
    local_processed_repository_root = step1_config.get('local_processed_repository_root')
    local_nas_repository_root = step1_config.get('local_nas_repository_root')
    local_mode = bool(
        local_repository_root
        or local_raw_repository_root
        or local_processed_repository_root
        or local_nas_repository_root
    )
    suite2p_config_root = _suite2p_config_root(step1_config, local_mode=local_mode)

    username = getpass.getuser()
    local_output_mode = bool(local_repository_root or local_processed_repository_root)
    if not local_output_mode and user_id != 'machine-pipeline-access' and username != user_id:
        raise ValueError(
            'You are not permitted to execute a job on the pipeline which will write to '
            'another users data folder'
        )

    if runsrdtrans and not runs2p:
        raise ValueError('runsrdtrans requires runs2p=True')
    if runsrdtrans and not isinstance(srdtrans_config, dict):
        raise ValueError('runsrdtrans requires step1_config["srdtrans"] to be a dict')

    with paths.local_repository_context(
        local_repository_root=local_repository_root,
        local_raw_repository_root=local_raw_repository_root,
        local_processed_repository_root=local_processed_repository_root,
        local_nas_repository_root=local_nas_repository_root,
    ):
        first_exp = exp_ids[0][0] if isinstance(exp_ids[0], list) else exp_ids[0]
        _, _, _, _, first_exp_raw = paths.find_paths(user_id, first_exp)
        topology, work_unit_ids = _discover_work_unit_ids(first_exp_raw)
        suite2p_plan = _normalize_suite2p_plan(suite2p_config, work_unit_ids)
        _validate_plan_configs(user_id, suite2p_plan, runs2p, config_root=suite2p_config_root)

        common_config = {
            'runhabituate': runhabituate,
            'settings': settings,
            'run_on': run_on,
            'queue': queue_name,
            'topology': topology,
            'suite2p_plan': suite2p_plan,
            'suite2p_config': suite2p_config,
            'suite2p_config_root': suite2p_config_root,
            'runsrdtrans': runsrdtrans,
            **({'srdtrans': json.loads(json.dumps(srdtrans_config))} if runsrdtrans else {}),
            **(
                {'suite2p_env': step1_config['suite2p_env']}
                if 'suite2p_env' in step1_config
                else {}
            ),
            **(
                {'register_with_summed_channel': True}
                if step1_config.get('register_with_summed_channel', False)
                else {}
            ),
            **(
                {'local_repository_root': local_repository_root}
                if local_repository_root
                else {}
            ),
            **(
                {'local_raw_repository_root': local_raw_repository_root}
                if local_raw_repository_root
                else {}
            ),
            **(
                {'local_processed_repository_root': local_processed_repository_root}
                if local_processed_repository_root
                else {}
            ),
            **(
                {'local_nas_repository_root': local_nas_repository_root}
                if local_nas_repository_root
                else {}
            ),
        }

        if local_mode:
            log_root_base = local_processed_repository_root or local_repository_root or local_raw_repository_root
            local_log_root = os.path.join(log_root_base, "_pipeline_jobs")
            os.makedirs(local_log_root, exist_ok=True)
            for exp_id in exp_ids:
                if isinstance(exp_id, str):
                    print('** Running local expID:' + exp_id)
                    now = datetime.now()
                    command_filename = _command_filename(now, user_id, exp_id, False)
                    runtime.run_preprocess_step1_universal(
                        command_filename,
                        user_id,
                        exp_id,
                        runs2p,
                        rundlc,
                        runfitpupil,
                        queued_command={
                            'job_type': 'step1_universal',
                            'command': '',
                            'userID': user_id,
                            'expID': exp_id,
                            'config': {
                                **common_config,
                                'runs2p': runs2p,
                                'rundlc': rundlc,
                                'runfitpupil': runfitpupil,
                            },
                        },
                        queue_path=local_log_root,
                    )
                    continue

                print(
                    'Running local combined experiment with base expID: ' + exp_id[0]
                )
                _validate_combined_work_units(user_id, exp_id, topology, work_unit_ids)
                all_exp_ids = ','.join(exp_id)
                now = datetime.now()
                command_filename = _command_filename(now, user_id, exp_id[0], False)
                runtime.run_preprocess_step1_universal(
                    command_filename,
                    user_id,
                    all_exp_ids,
                    runs2p,
                    False,
                    False,
                    queued_command={
                        'job_type': 'step1_universal',
                        'command': '',
                        'userID': user_id,
                        'expID': exp_id,
                        'config': {
                            **common_config,
                            'runs2p': runs2p,
                            'rundlc': False,
                            'runfitpupil': False,
                            'runhabituate': False,
                        },
                    },
                    queue_path=local_log_root,
                )
                for exp_id_sub in exp_id:
                    now = datetime.now()
                    command_filename = _command_filename(now, user_id, exp_id_sub, False)
                    runtime.run_preprocess_step1_universal(
                        command_filename,
                        user_id,
                        exp_id_sub,
                        False,
                        rundlc,
                        runfitpupil,
                        queued_command={
                            'job_type': 'step1_universal',
                            'command': '',
                            'userID': user_id,
                            'expID': exp_id_sub,
                            'config': {
                                **common_config,
                                'runs2p': False,
                                'rundlc': rundlc,
                                'runfitpupil': runfitpupil,
                            },
                        },
                        queue_path=local_log_root,
                    )
            return

        queue_path = _resolve_queue_path(run_on, queue_name)

        for exp_id in exp_ids:
            if isinstance(exp_id, str):
                print('Adding expID:' + exp_id + ' to the queue')
                now = datetime.now()
                command_filename = _command_filename(now, user_id, exp_id, jump_queue)
                command = _build_command(
                    command_filename, user_id, exp_id, runs2p, rundlc, runfitpupil
                )
                queued_command = _queue_single_job(
                    command_filename,
                    queue_path,
                    user_id,
                    exp_id,
                    command,
                    {
                        **common_config,
                        'runs2p': runs2p,
                        'rundlc': rundlc,
                        'runfitpupil': runfitpupil,
                    },
                )
                _notify_queue_position(queued_command['userID'], queued_command['expID'], queue_path)
                continue

            print(
                'You are combining experiments into a single suite2p run - if this is not '
                'intentional check your expID list'
            )
            print(
                'Adding expID:' + exp_id[0]
                + " to the queue as the base experiment of a 'combined experiment' suite2p run"
            )
            _validate_combined_work_units(user_id, exp_id, topology, work_unit_ids)
            all_exp_ids = ','.join(exp_id)
            now = datetime.now()
            command_filename = _command_filename(now, user_id, exp_id[0], jump_queue)
            command = _build_command(command_filename, user_id, all_exp_ids, runs2p, False, False)
            queued_command = _queue_single_job(
                command_filename,
                queue_path,
                user_id,
                exp_id,
                command,
                {
                    **common_config,
                    'runs2p': runs2p,
                    'rundlc': False,
                    'runfitpupil': False,
                    'runhabituate': False,
                },
            )
            _notify_queue_position(queued_command['userID'], queued_command['expID'][0], queue_path)

            for exp_id_sub in exp_id:
                print(
                    'Adding expID:' + exp_id_sub
                    + ' to the queue for non-combined processing of non-suite2p experiment data'
                )
                now = datetime.now()
                command_filename = _command_filename(now, user_id, exp_id_sub, jump_queue)
                command = _build_command(
                    command_filename, user_id, exp_id_sub, False, rundlc, runfitpupil
                )
                queued_command = _queue_single_job(
                    command_filename,
                    queue_path,
                    user_id,
                    exp_id_sub,
                    command,
                    {
                        **common_config,
                        'runs2p': False,
                        'rundlc': rundlc,
                        'runfitpupil': runfitpupil,
                    },
                )
                _notify_queue_position(
                    queued_command['userID'], queued_command['expID'], queue_path
                )


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m preprocess_pipeline.step1.run_batch <config.py>")

    config_globals = runpy.run_path(sys.argv[1])
    if 'step1_config' not in config_globals:
        raise KeyError(f"Config file did not define step1_config: {sys.argv[1]}")
    run_step1_batch_universal(config_globals['step1_config'])


if __name__ == "__main__":
    main()
