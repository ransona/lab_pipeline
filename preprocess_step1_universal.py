import os
import pickle
import subprocess
import sys
from datetime import datetime

import organise_paths
import preprocess_habituate


DEFAULT_QUEUE_PATH = '/data/common/queues/step1'
QUEUE_PATHS = [
    DEFAULT_QUEUE_PATH,
    '/data/common/local_pipelines/ar-lab-si2/queues/step1',
    '/data/common/local_pipelines/AdamDellXPS15/queues/step1',
]
LOG_ROOT = os.path.join(DEFAULT_QUEUE_PATH, 'logs')
CONFIG_ROOT = '/data/common/configs/s2p_configs'
SCRIPT_ROOT = '/home/adamranson/code/preprocess_py'


def _find_job_file(job_id):
    for queue_path in QUEUE_PATHS:
        job_path = os.path.join(queue_path, job_id)
        if os.path.exists(job_path):
            return job_path
    raise FileNotFoundError(f'Could not locate queued job file for {job_id}')


def _load_queued_command(job_id):
    job_path = _find_job_file(job_id)
    with open(job_path, 'rb') as f:
        return pickle.load(f)


def _log_path_for_job(job_id):
    os.makedirs(LOG_ROOT, exist_ok=True)
    if job_id.endswith('.pickle'):
        log_name = job_id[:-7] + '.txt'
    else:
        log_name = job_id + '.txt'
    return os.path.join(LOG_ROOT, log_name)


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


def _discover_topology(exp_dir_raw):
    return 'meso' if _is_meso_root(exp_dir_raw) else 'standard'


def _find_exp_paths(user_id, exp_id):
    _, _, _, exp_dir_processed, exp_dir_raw = organise_paths.find_paths(user_id, exp_id)
    return exp_dir_raw, exp_dir_processed


def _all_exp_ids(exp_id):
    return exp_id.split(',') if ',' in exp_id else [exp_id]


def _work_unit_mode(work_unit_id):
    return 'standard' if work_unit_id == 'root' else 'meso'


def _resolve_work_unit_paths(user_id, exp_ids, work_unit_id):
    raw_paths = []
    output_path = None
    for index, current_exp_id in enumerate(exp_ids):
        exp_dir_raw, exp_dir_processed = _find_exp_paths(user_id, current_exp_id)
        if work_unit_id == 'root':
            raw_path = exp_dir_raw
            current_output_path = exp_dir_processed
        else:
            raw_path = os.path.join(exp_dir_raw, work_unit_id)
            current_output_path = os.path.join(exp_dir_processed, work_unit_id)
        if not os.path.exists(raw_path):
            raise FileNotFoundError(
                f'Work unit {work_unit_id} does not exist for experiment {current_exp_id}: {raw_path}'
            )
        raw_paths.append(raw_path)
        if index == 0:
            output_path = current_output_path
    return raw_paths, output_path


def _suite2p_config_path(user_id, config_names):
    return ','.join(os.path.join(CONFIG_ROOT, user_id, config_name) for config_name in config_names)


def _stream_subprocess(cmd, log_path):
    all_output = ''
    with subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    ) as proc:
        for line in proc.stdout:
            print(line, end='')
            all_output += line
            sys.stdout.flush()
            with open(log_path, 'a') as file:
                file.write(line)

        for line in proc.stderr:
            print('Error: ' + line, end='')
            all_output += line
            sys.stdout.flush()
            with open(log_path, 'a') as file:
                file.write(line)

        proc.wait()
        if proc.returncode != 0:
            with open(log_path, 'w') as file:
                file.write(all_output)
            raise Exception('An error occurred during subprocess execution')


def _suite2p_cmd_for_work_unit(
    user_id,
    exp_id,
    tif_path,
    output_path,
    config_names,
    queued_command,
    work_unit_id,
):
    suite2p_env = queued_command['config'].get('suite2p_env', 'suite2p')
    run_s2p_as_user = 'suite2p_env' in queued_command['config']
    launcher = os.path.join(SCRIPT_ROOT, 's2p_launcher_universal.py')
    launcher_args = [
        user_id,
        exp_id,
        tif_path,
        output_path,
        _suite2p_config_path(user_id, config_names),
    ]

    if run_s2p_as_user:
        return [
            'sudo',
            '-u',
            user_id,
            '/opt/scripts/conda-run.sh',
            suite2p_env,
            'python',
            '-u',
            launcher,
            *launcher_args,
        ]
    return ['/opt/scripts/conda-run.sh', suite2p_env, 'python', '-u', launcher, *launcher_args]


def _run_suite2p_plan(job_id, user_id, exp_id, queued_command):
    exp_ids = _all_exp_ids(exp_id)
    log_path = _log_path_for_job(job_id)

    for plan_item in queued_command['config']['suite2p_plan']:
        work_unit_id = plan_item['work_unit']
        config_names = plan_item['suite2p_configs']
        raw_paths, output_path = _resolve_work_unit_paths(user_id, exp_ids, work_unit_id)
        tif_path = ','.join(raw_paths)
        os.makedirs(output_path, exist_ok=True)

        cmd = _suite2p_cmd_for_work_unit(
            user_id,
            exp_id,
            tif_path,
            output_path,
            config_names,
            queued_command,
            work_unit_id,
        )

        print('Starting S2P launcher for work unit ' + work_unit_id + '...')
        now = datetime.now()
        print(now.strftime('%Y-%m-%d %H:%M:%S'))
        _stream_subprocess(cmd, log_path)


def _run_dlc(job_id, user_id, exp_id, topology):
    launcher_name = 'dlc_launcher_meso.py' if topology == 'meso' else 'dlc_launcher.py'
    env_name = 'DLC2' if topology == 'meso' else 'DLC_05_02_2026'
    launcher = os.path.join(SCRIPT_ROOT, launcher_name)
    cmd = ['/opt/scripts/conda-run.sh', env_name, 'python', launcher, user_id, exp_id]
    _stream_subprocess(cmd, _log_path_for_job(job_id))


def _run_fit_pupil(job_id, user_id, exp_id):
    launcher = os.path.join(SCRIPT_ROOT, 'preprocess_pupil.py')
    cmd = ['conda', 'run', '--no-capture-output', '--name', 'sci', 'python', launcher, user_id, exp_id]
    _stream_subprocess(cmd, _log_path_for_job(job_id))


def run_preprocess_step1_universal(jobID, userID, expID, runs2p, rundlc, runfitpupil):
    print('Starting job: ' + jobID)
    print('--------------------------------------------------')

    queued_command = _load_queued_command(jobID)
    exp_ids = _all_exp_ids(expID)
    first_exp_raw, first_exp_processed = _find_exp_paths(userID, exp_ids[0])
    os.makedirs(first_exp_processed, exist_ok=True)

    topology = queued_command['config'].get('topology')
    if topology is None:
        topology = _discover_topology(first_exp_raw)

    if runs2p:
        _run_suite2p_plan(jobID, userID, expID, queued_command)

    if rundlc:
        print('Running DLC launcher...')
        _run_dlc(jobID, userID, expID, topology)

    if runfitpupil:
        print('Running pupil fit launcher...')
        _run_fit_pupil(jobID, userID, expID)

    if queued_command['config'].get('runhabituate', False):
        print('Running habituation setup processing...')
        preprocess_habituate.preprocess_habituate_run(userID, expID)
