import os
import pickle
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from preprocess_pipeline.shared import paths
from preprocess_pipeline.srdtrans.launcher import encode_config_arg as encode_srdtrans_config_arg
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
LOCAL_CONFIG_ROOT_ENV = 'LAB_PIPELINE_S2P_CONFIG_ROOT'
WINDOWS_LOCAL_CONFIG_ROOT = r'F:\s2p_ops'
REPO_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPO_ROOT / 'apps'


def _is_local_mode_config(config):
    return bool(
        config.get('local_repository_root')
        or config.get('local_raw_repository_root')
        or config.get('local_processed_repository_root')
        or config.get('local_nas_repository_root')
    )


def _conda_executable():
    conda_exe = os.environ.get('CONDA_EXE')
    if conda_exe and os.path.exists(conda_exe):
        return conda_exe

    candidates = []
    try:
        candidates.append(Path(sys.executable).parents[2] / 'Scripts' / 'conda.exe')
    except IndexError:
        pass
    candidates.append(Path.home() / 'miniconda3' / 'Scripts' / 'conda.exe')
    candidates.append(Path.home() / 'anaconda3' / 'Scripts' / 'conda.exe')

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return 'conda'


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


def _raw_log_path_for_job(job_id, queue_path=DEFAULT_QUEUE_PATH):
    log_path = _log_path_for_job(job_id, queue_path=queue_path)
    if log_path.endswith('.txt'):
        return log_path[:-4] + '.raw.txt'
    return log_path + '.raw'


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


def _write_pipeline_config_for_experiments(user_id, exp_ids, queued_command):
    for current_exp_id in exp_ids:
        _, exp_dir_processed = _find_exp_paths(user_id, current_exp_id)
        os.makedirs(exp_dir_processed, exist_ok=True)
        config_path = os.path.join(exp_dir_processed, 'pipeline_config.pickle')
        with open(config_path, 'wb') as f:
            pickle.dump(queued_command, f)


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


def _suite2p_config_root(queued_command=None):
    if queued_command:
        config_root = queued_command.get('config', {}).get('suite2p_config_root')
        if config_root:
            return config_root
        local_config = queued_command.get('config', {})
        if _is_local_mode_config(local_config) and os.name == 'nt':
            return WINDOWS_LOCAL_CONFIG_ROOT
    env_root = os.environ.get(LOCAL_CONFIG_ROOT_ENV)
    if env_root:
        return env_root
    return CONFIG_ROOT


def _suite2p_config_name(config_entry):
    if isinstance(config_entry, dict):
        return config_entry['config']
    return config_entry


def _suite2p_functional_chan(config_entry, default_value=1):
    if isinstance(config_entry, dict):
        return int(config_entry.get('functional_chan', default_value))
    return int(default_value)


def _suite2p_chan2_detection(config_entry):
    if isinstance(config_entry, dict):
        return str(config_entry.get('chan2_detection', 'off')).lower()
    return 'off'


def _suite2p_config_path(user_id, config_names, queued_command=None):
    config_root = _suite2p_config_root(queued_command)
    return ','.join(
        os.path.join(config_root, user_id, _suite2p_config_name(config_entry))
        for config_entry in config_names
    )


def _should_emit_progress_line(line, progress_state):
    stripped = line.strip()
    message = re.sub(
        r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} \[(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)\]\s+',
        '',
        stripped,
    )
    if message:
        stripped = message
    lowered = stripped.lower()

    if not stripped:
        return True

    if stripped in {'warn(', 'warnings.warn('}:
        return False

    if any(
        token in lowered
        for token in ('traceback', 'error', 'warning', 'failed', 'exception', 'done without errors')
    ):
        return True

    suite2p_binary = re.match(r'^(\d+) frames of binary, time ', stripped)
    if suite2p_binary:
        frame_count = int(suite2p_binary.group(1))
        if frame_count - progress_state['last_binary_frame'] >= 20000:
            progress_state['last_binary_frame'] = frame_count
            return True
        return False

    suite2p_registered = re.match(r'^(?:Second channel, )?Registered (\d+)/(\d+) in ', stripped)
    if suite2p_registered:
        frame_count = int(suite2p_registered.group(1))
        if frame_count - progress_state['last_registered_frame'] >= 20000:
            progress_state['last_registered_frame'] = frame_count
            return True
        return False

    dlc_progress = re.match(r'^(\d+)/(\d+) - ([0-9.]+)% complete Frame rate = ', stripped)
    if dlc_progress:
        percent = int(float(dlc_progress.group(3)))
        milestone = (percent // 25) * 25
        if milestone >= 25 and milestone not in progress_state['dlc_percent_milestones']:
            progress_state['dlc_percent_milestones'].add(milestone)
            return True
        return False

    dlc_tqdm = re.match(r'^(\d+)%\|.*\|\s*(\d+)/(\d+)\s*\[', stripped)
    if dlc_tqdm:
        percent = int(dlc_tqdm.group(1))
        milestone = (percent // 25) * 25
        if milestone >= 25 and milestone not in progress_state['dlc_percent_milestones']:
            progress_state['dlc_percent_milestones'].add(milestone)
            return True
        return False

    if re.match(r'^(25|50|75|100)% complete$', stripped):
        return True

    suite2p_tqdm = re.match(r'^(\d+)%\|.*\|\s*(\d+)/(\d+)\s*\[', stripped)
    if suite2p_tqdm:
        percent = int(suite2p_tqdm.group(1))
        current = int(suite2p_tqdm.group(2))
        total = int(suite2p_tqdm.group(3))
        key = (total, (percent // 25) * 25)
        if current == total or (key[1] >= 25 and key not in progress_state['suite2p_tqdm_milestones']):
            progress_state['suite2p_tqdm_milestones'].add(key)
            return True
        return False

    return True


def _stream_subprocess(cmd, log_path, raw_log_path):
    progress_state = {
        'last_binary_frame': 0,
        'last_registered_frame': 0,
        'dlc_percent_milestones': set(),
        'suite2p_tqdm_milestones': set(),
    }
    with subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    ) as proc:
        for line in proc.stdout:
            with open(raw_log_path, 'a') as raw_file:
                raw_file.write(line)

            if _should_emit_progress_line(line, progress_state):
                print(line, end='')
                sys.stdout.flush()
                with open(log_path, 'a') as file:
                    file.write(line)

        proc.wait()
        if proc.returncode != 0:
            with open(log_path, 'a') as file:
                file.write(f'[subprocess exited with code {proc.returncode}]\n')
            raise Exception('An error occurred during subprocess execution')


def _stream_subprocess_for_job(cmd, job_id, queue_path):
    log_path = _log_path_for_job(job_id, queue_path=queue_path)
    raw_log_path = _raw_log_path_for_job(job_id, queue_path=queue_path)
    os.makedirs(os.path.dirname(raw_log_path), exist_ok=True)
    for path in (log_path, raw_log_path):
        if not os.path.exists(path):
            with open(path, 'a'):
                pass
    _stream_subprocess(cmd, log_path, raw_log_path)


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
        _suite2p_config_path(user_id, config_names, queued_command=queued_command),
    ]
    functional_chans = [
        _suite2p_functional_chan(config_entry, index + 1)
        for index, config_entry in enumerate(config_names)
    ]
    launcher_args.append('--functional-chans=' + ','.join(str(chan) for chan in functional_chans))
    chan2_detection = [
        _suite2p_chan2_detection(config_entry)
        for config_entry in config_names
    ]
    launcher_args.append('--chan2-detection=' + ','.join(chan2_detection))
    if queued_command["config"].get("runsrdtrans", False):
        launcher_args.append(encode_srdtrans_config_arg(queued_command["config"]["srdtrans"]))
    if queued_command["config"].get("register_with_summed_channel", False):
        launcher_args.append("--register-with-summed-channel")

    if _is_local_mode_config(queued_command['config']) and os.name == 'nt':
        return [
            _conda_executable(),
            'run',
            '--no-capture-output',
            '--name',
            suite2p_env,
            'python',
            '-u',
            launcher,
            *launcher_args,
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

        print('** Starting S2P launcher for work unit ' + work_unit_id + '...')
        now = datetime.now()
        print(now.strftime('%Y-%m-%d %H:%M:%S'))
        _stream_subprocess_for_job(cmd, job_id, queue_path)


def _run_dlc(job_id, user_id, exp_id, topology, queue_path=DEFAULT_QUEUE_PATH):
    env_name = 'DLC_05_02_2026'
    launcher = str(APP_ROOT / 'dlc_launcher.py')
    cmd = ['/opt/scripts/conda-run.sh', env_name, 'python', launcher, user_id, exp_id]
    _stream_subprocess_for_job(cmd, job_id, queue_path)


def _run_fit_pupil(job_id, user_id, exp_id, queue_path=DEFAULT_QUEUE_PATH):
    launcher = str(APP_ROOT / 'preprocess_pupil.py')
    cmd = ['conda', 'run', '--no-capture-output', '--name', 'sci', 'python', launcher, user_id, exp_id]
    _stream_subprocess_for_job(cmd, job_id, queue_path)


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
    print('** Starting job: ' + jobID)
    print('--------------------------------------------------')

    if queued_command is None:
        queued_command = _load_queued_command(jobID, queue_paths=[queue_path])
    exp_ids = _all_exp_ids(expID)
    _write_pipeline_config_for_experiments(userID, exp_ids, queued_command)
    first_exp_raw, first_exp_processed = _find_exp_paths(userID, exp_ids[0])
    os.makedirs(first_exp_processed, exist_ok=True)

    topology = queued_command['config'].get('topology')
    if topology is None:
        topology = _discover_topology(first_exp_raw)

    if runs2p:
        _run_suite2p_plan(jobID, userID, expID, queued_command, queue_path=queue_path)

    if rundlc:
        print('** Running DLC launcher...')
        _run_dlc(jobID, userID, expID, topology, queue_path=queue_path)

    if runfitpupil:
        print('** Running pupil fit launcher...')
        _run_fit_pupil(jobID, userID, expID, queue_path=queue_path)

    if queued_command['config'].get('runhabituate', False):
        print('** Running habituation setup processing...')
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
