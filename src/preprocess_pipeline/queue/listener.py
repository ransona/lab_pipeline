# queue listener
import os
import time
import pickle
import shutil
from preprocess_pipeline.shared import file_check, matrix_notify, paths
from preprocess_pipeline.step1 import runtime as step1_runtime
import grp
import stat
import sys
from datetime import datetime


DEFAULT_QUEUE_PATH = '/data/common/queues/step1/'
DEBUG_QUEUE_PATH = '/data/common/queues/debug/'


class TeeStream:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def queue_log_path(queue_path):
    return os.path.join(queue_path, 'qlistener-log.txt')


def detect_gpus():
    try:
        import torch
    except Exception as e:
        return 0, [], f'Unable to import torch: {e}'

    try:
        if not torch.cuda.is_available():
            return 0, [], 'torch.cuda.is_available() returned False'

        ngpus = torch.cuda.device_count()
        gpu_names = [torch.cuda.get_device_name(i) for i in range(ngpus)]
        return ngpus, gpu_names, None
    except Exception as e:
        return 0, [], f'PyTorch GPU detection failed: {e}'


def gpu_check_is_soft_failure(gpu_error):
    if not gpu_error:
        return False
    soft_markers = (
        'Unable to import torch',
        'torch.cuda.is_available() returned False',
    )
    return any(marker in gpu_error for marker in soft_markers)

class JobScheduler:
    def __init__(self):
        self.last_30_jobs = []  # Rolling list of last 30 jobs, (runtime, user)
        self.user_runtime = {}  # User cumulative runtime in the last 30 jobs

    @staticmethod
    def _normalise_runtime(value):
        return 0.0 if abs(value) < 1e-9 else value

    def is_priority_job(self, filename):
        # Check if the job filename ends with "_x.pickle"
        return filename.endswith("_x.pickle")

    def parse_filename(self, filename):
        # Extract submission date/time and user from filename
        parts = filename.split("_")
        timestamp = "_".join(parts[:6])
        submission_date = datetime.strptime(timestamp, "%Y_%m_%d_%H_%M_%S")
        user = parts[6]
        return submission_date, user

    def add_runtime(self, runtime, user):
        # Add job runtime to rolling log
        self.last_30_jobs.append((runtime, user))
        if len(self.last_30_jobs) > 30:
            old_runtime, old_user = self.last_30_jobs.pop(0)
            self.user_runtime[old_user] = self._normalise_runtime(
                self.user_runtime.get(old_user, 0.0) - old_runtime
            )

        # Update user runtime
        if user not in self.user_runtime:
            self.user_runtime[user] = 0.0
        self.user_runtime[user] += runtime
        self.user_runtime[user] = self._normalise_runtime(self.user_runtime[user])

    def sort_jobs_by_priority(self, job_files, output_directory=DEFAULT_QUEUE_PATH):
        # Separate priority and regular jobs
        priority_jobs = []
        regular_jobs = []

        for job in job_files:
            if self.is_priority_job(job):
                priority_jobs.append(job)
            else:
                regular_jobs.append(job)

        # Sort priority jobs by submission date
        priority_jobs.sort(key=lambda job: self.parse_filename(job)[0])

        # Group regular jobs by user
        user_jobs = {}
        job_submission_times = {}  # Store submission time for regular jobs
        for job in regular_jobs:
            submission_date, user = self.parse_filename(job)
            if user not in user_jobs:
                user_jobs[user] = []
            user_jobs[user].append(job)
            job_submission_times[job] = submission_date

        # Sort users by compute time, breaking ties by submission time of their earliest job
        sorted_users = sorted(
            user_jobs.keys(),
            key=lambda user: (
                self.user_runtime.get(user, 0),  # Primary: Least compute time
                min(job_submission_times[job] for job in user_jobs[user]) if user_jobs[user] else float('inf')  # Secondary: Earliest submission time if applicable
            )
        )

        # Write all users with runtime info to a file
        os.makedirs(output_directory, exist_ok=True)  # Ensure the directory exists
        output_file = os.path.join(output_directory, "user_totals.txt")
        with open(output_file, "w") as f:
            for user, runtime in sorted(self.user_runtime.items(), key=lambda x: x[1]):  # Sort all users by runtime
                f.write(f"{user} {round(runtime, 2)}\n")
            # print(f"User priority list written to {output_file}")

        # Sort jobs within each user's group by submission time
        for user in user_jobs:
            user_jobs[user].sort(key=lambda job: job_submission_times[job])

        # Build the sorted list of regular jobs
        sorted_regular_jobs = []
        for user in sorted_users:
            sorted_regular_jobs.extend(user_jobs[user])

        # Combine priority jobs and sorted regular jobs
        return priority_jobs + sorted_regular_jobs


def main(debug=False, queue_path=None):
    scheduler = JobScheduler()
    if queue_path is None:
        queue_path = DEBUG_QUEUE_PATH if debug else DEFAULT_QUEUE_PATH

    os.makedirs(queue_path, exist_ok=True)
    log_handle = open(queue_log_path(queue_path), 'a', encoding='utf-8', buffering=1)
    sys.stdout = TeeStream(sys.__stdout__, log_handle)
    sys.stderr = TeeStream(sys.__stderr__, log_handle)

    restart_msg = 'Queue restarted (debug)' if debug else 'Queue restarted'
    matrix_notify.main('adamranson', restart_msg)
    matrix_notify.main('adamranson', restart_msg, 'Server queue notifications')
    print(f'** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Waiting for jobs in {queue_path}...')

    try:
        while True:
        # Get list of all files in the directory
            time.sleep(0.5)
            files = os.listdir(queue_path)
            files = [file for file in files if file.endswith('.pickle')]
            prioritised_jobs = scheduler.sort_jobs_by_priority(files, output_directory=queue_path)

        # Write the sorted jobs to a file
            output_file = os.path.join(queue_path,'prioritised_jobs.txt')
            with open(output_file, "w") as f:
                for job in prioritised_jobs:
                    f.write(f"{job}\n")    

        # if there are items in the queue
            if len(prioritised_jobs) > 0:
                try:
                
                    files_ready = True

                # Open the job (without integrity check)
                    with open(os.path.join(queue_path,prioritised_jobs[0]), "rb") as file: 
                        queued_command = pickle.load(file)

                # Cycle through the jobs trying to find one that has its files in order
                    for ijob in range(len(prioritised_jobs)):
                    # assume files ready unless find otherwise
                        files_ready = True
                    
                    # Open the job
                        with open(os.path.join(queue_path,prioritised_jobs[ijob]), "rb") as file: 
                            queued_command = pickle.load(file)

                    # if the experiment was done before integrity check was implemented then don't do check
                        target_date_str = '2023-05-10' # define cutoff
                        date_format = "%Y-%m-%d"
                        if type(queued_command['expID']) == str:
                        # make copy which is a list of 1 item
                            allExps = list([queued_command['expID']])
                        else:
                        # then it is a sequence of experiments
                            allExps = queued_command['expID']

                    # cycle through all experiments checking integrity - only run if all files of all experiments are there
                        for nextExpID in allExps:
                            animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw = paths.find_paths(queued_command['userID'], nextExpID)
                            date_str = nextExpID[:10] # get experiment date

                            file_date = datetime.strptime(date_str, date_format)
                            target_date = datetime.strptime(target_date_str, date_format)

                        exp_has_integrity_check = file_date >= target_date

                        if exp_has_integrity_check:
                            if queued_command['config'].get('runhabituate', False):
                                print(
                                    'Habituation job detected; skipping NAS/cams integrity checks '
                                    f'for {nextExpID}'
                                )
                                continue
                            # you always need to have your nas data verified (contains experiment log, timeline, bonvision etc)
                            ready,comment = file_check.verify_file_data('nas',exp_dir_raw,exp_dir_processed)
                            matrix_notify.main(queued_command['userID'],'----------')

                            if not ready:
                                files_ready = False
                                matrix_notify.main(queued_command['userID'],'Awaiting NAS data integrity verification: ' + comment)
                            else:          
                                matrix_notify.main(queued_command['userID'],'NAS data verified')
                                print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} NAS data verified')

                            if queued_command['config']['runs2p']:
                            # if you want to do suite2p you need to have your scanimage data verified
                                ready,comment = file_check.verify_file_data('scanimage',exp_dir_raw,exp_dir_processed)
                                if not ready:
                                    files_ready = False
                                    matrix_notify.main(queued_command['userID'],'Awaiting SI data integrity verification: ' + comment) 
                                else:          
                                    matrix_notify.main(queued_command['userID'],'SI data verified')
                                    print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} SI data verified')

                                if queued_command['config']['rundlc']:
                                # if you want to do dlc you need to have your video data verified
                                    ready,comment = file_check.verify_file_data('cams',exp_dir_raw,exp_dir_processed)
                                    if not ready:
                                        files_ready = False
                                        matrix_notify.main(queued_command['userID'],'Awaiting video data integrity verification: ' + comment)          
                                    else:          
                                        matrix_notify.main(queued_command['userID'],'video data verified')
                                        print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Vid data verified')
                            else:
                            # pre integrity check so just assume all files are there and run it
                                print('Experiment is pre 2023-05-10 so no file integrity data so assuming all data present and running')
                                files_ready = True

                        if files_ready:
                        # then run that job
                            break

                    if files_ready:
                        if type(queued_command['expID']) == str:
                        # then a single experiment
                        # expID only used here for matrix msg
                            expID = queued_command['expID']
                        else:
                        # then several experiments being run through suite2p as one
                            expID = queued_command['expID'][0]
                            matrix_notify.main(queued_command['userID'],'Running COMBINED experiment')

                        matrix_notify.main(queued_command['userID'],'----------')
                    
                    # if the above loop through the jobs found one that is ready
                        print(f'** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Running:')
                        print(queued_command['command'])

                        matrix_notify.main(queued_command['userID'],'Starting ' + expID)
                        matrix_notify.main('adamranson','Starting ' + expID,'Server queue notifications')
                    
                        ngpus, gpu_names, gpu_error = detect_gpus()

                        if ngpus > 0:
                            print(f'PyTorch detected {ngpus} GPU(s): {", ".join(gpu_names)}')
                        else:
                            if gpu_check_is_soft_failure(gpu_error):
                                gpu_message = f'Listener GPU check skipped: {gpu_error}'
                                print(gpu_message)
                            else:
                                gpu_message = f'GPU problems: expecting at least 1 GPU, found {ngpus}'
                                if gpu_error:
                                    gpu_message += f' ({gpu_error})'
                                print(gpu_message)
                                matrix_notify.main(queued_command['userID'], gpu_message)

                    # make the output directory if it doesn't already exist (will be first expID if several are being run through suite2p together)
                        animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw = paths.find_paths(queued_command['userID'], allExps[0])
                        os.makedirs(exp_dir_processed, exist_ok = True) 
                    # save the command file to the output folder so that the settings field can be accessed in the pipeline
                        with open(os.path.join(exp_dir_processed,'pipeline_config.pickle'), 'wb') as f: pickle.dump(queued_command, f) 

                        start_time = time.time()
                    # run command file
                        if queued_command.get('job_type') != 'step1_universal':
                            raise ValueError(f"Unsupported job_type in lab_pipeline queue: {queued_command.get('job_type')}")
                        step1_runtime.run_preprocess_step1_job(
                            prioritised_jobs[ijob],
                            queued_command,
                            queue_path=queue_path.rstrip('/'),
                        )
                    # if it gets here it has somewhat worked
                    # move job to completed
                        shutil.move(os.path.join(queue_path,prioritised_jobs[ijob]),os.path.join(queue_path,'completed',prioritised_jobs[ijob]))
                        print('#####################')
                        print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Completed ' + prioritised_jobs[ijob] + ' without errors')
                        print('Run time: ' + str(round((time.time()-start_time) / 60,2)) + ' mins')
                        print('#####################')

                        scheduler.add_runtime(round((time.time()-start_time) / 60,2), queued_command['userID'])  

                        matrix_notify.main(queued_command['userID'],'Complete ' + prioritised_jobs[ijob] + ' without errors')
                        matrix_notify.main(queued_command['userID'],'Run time: ' + str(round((time.time()-start_time) / 60,2)) + ' mins')
                        matrix_notify.main('adamranson','Complete ' + prioritised_jobs[ijob] + ' without errors','Server queue notifications')
                        matrix_notify.main('adamranson','Run time: ' + str(round((time.time()-start_time) / 60,2)) + ' mins','Server queue notifications')
                    else:
                    # no files have been found to be ready in the queue but there are jobs in the 
                    # queue so we are probably waiting for experiments to sync to the google drive
                    # we therefore timeout for 10 mins to avoid repeatedly polling the google drive
                    # for file presence/integrity
                        print('Pausing 10 mins to await probable NAS -> Server sync')
                        time.sleep(60*2)

                except Exception as e:

                    matrix_notify.main(queued_command['userID'],'Error running ' + prioritised_jobs[ijob])
                    matrix_notify.main(queued_command['userID'],str(e))
                    matrix_notify.main(queued_command['userID'],'Run time: ' + str(round((time.time()-start_time) / 60,2)) + ' mins')
                    matrix_notify.main('adamranson','Error running ' + prioritised_jobs[ijob],'Server queue notifications')
                    matrix_notify.main('adamranson',str(e),'Server queue notifications')
                    matrix_notify.main('adamranson','Run time: ' + str(round((time.time()-start_time) / 60,2)) + ' mins','Server queue notifications')                
                    
                    try:
                    # some kind of error
                        queued_command['error'] = str(e)
                    # save in pickle
                        with open(os.path.join(queue_path,prioritised_jobs[ijob]), 'wb') as f: pickle.dump(queued_command, f)  
                        shutil.move(os.path.join(queue_path,prioritised_jobs[ijob]),os.path.join(queue_path,'failed',prioritised_jobs[ijob]))
                    except:
                    # unable to write to command file
                        try:
                            shutil.move(os.path.join(queue_path,prioritised_jobs[ijob]),os.path.join(queue_path,'failed',prioritised_jobs[ijob]))
                        except:
                        # unable to move command file
                        # this kills the queue
                            print(f'** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Error with ' + prioritised_jobs[ijob])
                            print('Unmovable file in the queue - please investigate')
                            print('Run time: ' + str((time.time()-start_time) / 60) + ' mins')
                            exit()
                    
                    print('#####################')
                    print('** Error with ' + prioritised_jobs[ijob])
                    print('Run time: ' + str((time.time()-start_time) / 60) + ' mins')
                    print('#####################')            
                
                    print('** Waiting for jobs...')
    except Exception as e:
        print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} Error caused queue to crash!')
        print('Will require queue restart!')
        print(e)


if __name__ == "__main__":
    debug = '--debug' in sys.argv
    main(debug=debug)
