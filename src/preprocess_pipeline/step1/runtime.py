import os
import pickle
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from preprocess_pipeline.shared import paths
from preprocess_pipeline.step1 import habituate


DEFAULT_QUEUE_PATH = '/data/common/queues/step1'
DEBUG_QUEUE_PATH = '/data/common/queues/debug'
QUEUE_PATHS = [
    DEFAULT_QUEUE_PATH,
    DEBUG_QUEUE_PATH,
    '/data/common/local_pipelines/ar-lab-si2/queues/step1',
    '/data/common/local_pipelines/AdamDellXPS15/queues/step1',
]
CONFIG_ROOT = '/data/common/configs/s2p_configs'
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / 'apps'


def _find_job_file(job_id, queue_paths=None):
    if queue_paths is None:
        queue_paths = QUEUE_PATHS
    for queue_path in queue_paths:
        job_path = os.path.join(queue_path, job_id)
        if os.path.exists(job_path):
            return job_path
    raise FileNotFoundError(f'Could not locate queued job file for {job_id}')


def _load_queued_command(job_id, queue_paths=None):
    job_path = _find_job_file(job_id, queue_paths=queue_paths)
    with open(job_path, 'rb') as f:
        return pickle.load(f)


def _log_path_for_job(job_id, queue_path=DEFAULT_QUEUE_PATH):
    log_root = os.path.join(queue_path, 'logs')
    os.makedirs(log_root, exist_ok=True)
    if job_id.endswith('.pickle'):
        log_name = job_id[:-7] + '.txt'
    else:
        log_name = job_id + '.txt'
    return os.path.join(log_root, log_name)


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
    _, _, _, exp_dir_processed, exp_dir_raw = paths.find_paths(user_id, exp_id)
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
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    ) as proc:
        for line in proc.stdout:
            print(line, end='')
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
    launcher = str(APP_ROOT / 's2p_launcher.py')
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


def _run_suite2p_plan(job_id, user_id, exp_id, queued_command, queue_path=DEFAULT_QUEUE_PATH):
    exp_ids = _all_exp_ids(exp_id)
    log_path = _log_path_for_job(job_id, queue_path=queue_path)

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


def _run_dlc(job_id, user_id, exp_id, topology, queue_path=DEFAULT_QUEUE_PATH):
    env_name = 'DLC_05_02_2026'
    launcher = str(APP_ROOT / 'dlc_launcher.py')
    cmd = ['/opt/scripts/conda-run.sh', env_name, 'python', launcher, user_id, exp_id]
    _stream_subprocess(cmd, _log_path_for_job(job_id, queue_path=queue_path))


def _run_fit_pupil(job_id, user_id, exp_id, queue_path=DEFAULT_QUEUE_PATH):
    launcher = str(APP_ROOT / 'preprocess_pupil.py')
    cmd = ['conda', 'run', '--no-capture-output', '--name', 'sci', 'python', launcher, user_id, exp_id]
    _stream_subprocess(cmd, _log_path_for_job(job_id, queue_path=queue_path))


def run_preprocess_step1_job(job_id, queued_command=None, queue_path=DEFAULT_QUEUE_PATH):
    if queued_command is None:
        queued_command = _load_queued_command(job_id, queue_paths=[queue_path])

    exp_id = queued_command['expID']
    exp_id_arg = ','.join(exp_id) if isinstance(exp_id, list) else exp_id
    config = queued_command['config']

    run_preprocess_step1_universal(
        job_id,
        queued_command['userID'],
        exp_id_arg,
        config['runs2p'],
        config['rundlc'],
        config['runfitpupil'],
        queued_command=queued_command,
        queue_path=queue_path,
    )


def run_preprocess_step1_universal(
    jobID,
    userID,
    expID,
    runs2p,
    rundlc,
    runfitpupil,
    queued_command=None,
    queue_path=DEFAULT_QUEUE_PATH,
):
    print('Starting job: ' + jobID)
    print('--------------------------------------------------')

    if queued_command is None:
        queued_command = _load_queued_command(jobID, queue_paths=[queue_path])
    exp_ids = _all_exp_ids(expID)
    first_exp_raw, first_exp_processed = _find_exp_paths(userID, exp_ids[0])
    os.makedirs(first_exp_processed, exist_ok=True)

    topology = queued_command['config'].get('topology')
    if topology is None:
        topology = _discover_topology(first_exp_raw)

    if runs2p:
        _run_suite2p_plan(jobID, userID, expID, queued_command, queue_path=queue_path)

    if rundlc:
        print('Running DLC launcher...')
        _run_dlc(jobID, userID, expID, topology, queue_path=queue_path)

    if runfitpupil:
        print('Running pupil fit launcher...')
        _run_fit_pupil(jobID, userID, expID, queue_path=queue_path)

    if queued_command['config'].get('runhabituate', False):
        print('Running habituation setup processing...')
        habituate.preprocess_habituate_run(userID, expID)


def main():
    if len(sys.argv) != 7:
        raise SystemExit(
            "Usage: python -m preprocess_pipeline.step1.runtime "
            "<job_id> <user_id> <exp_id> <runs2p> <rundlc> <runfitpupil>"
        )

    job_id, user_id, exp_id = sys.argv[1], sys.argv[2], sys.argv[3]
    runs2p = sys.argv[4].lower() == 'true'
    rundlc = sys.argv[5].lower() == 'true'
    runfitpupil = sys.argv[6].lower() == 'true'
    run_preprocess_step1_universal(job_id, user_id, exp_id, runs2p, rundlc, runfitpupil)


if __name__ == "__main__":
    main()
