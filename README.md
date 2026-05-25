# lab_pipeline

Fresh consolidation repo for the lab preprocessing pipeline.

## Current state

- the old source repos remain unchanged:
  - `/home/adamranson/code/preprocess_py`
  - `/home/adamranson/code/preprocess_scripts`
- their histories are imported under `legacy/`
- the forward path is now the canonical universal pipeline under `src/preprocess_pipeline/`
- non-universal paths are retained only under `legacy/`

Imported legacy snapshots:
- `legacy/preprocess_py` from `c31fcc6`
- `legacy/preprocess_scripts` from `8ef0335`

## Canonical structure

- `src/preprocess_pipeline/`
  - package-first canonical code
  - current first-pass promoted modules:
    - shared paths, matrix notifications, file integrity checks
    - universal step-1 queueing/runtime
    - universal queue listener
    - universal Suite2p launcher and preprocessing
    - universal DLC and pupil paths
    - universal combined Suite2p splitter
- `apps/`
  - thin runnable shims for direct subsystem execution
- `configs/`
  - future home for run configs and examples
- `docs/`
  - migration and architecture notes
- `legacy/`
  - imported source repos kept intact for reference and history

## Direct subsystem execution

The new repo keeps direct runnable entrypoints so subsystems remain independently testable without the full pipeline:

- `python /home/adamranson/code/lab_pipeline/apps/run_step1.py <config.py>`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_step1.py <job_id> <user_id> <exp_id> <runs2p> <rundlc> <runfitpupil>`
- `python /home/adamranson/code/lab_pipeline/apps/s2p_launcher.py ...`
- `python /home/adamranson/code/lab_pipeline/apps/dlc_launcher.py <user> <exp>`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_pupil.py <user> <exp>`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_s2p.py`
- `python /home/adamranson/code/lab_pipeline/apps/split_combined_s2p.py`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_habituate.py`
- `python /home/adamranson/code/lab_pipeline/apps/queue_listener.py`
- `python /home/adamranson/code/lab_pipeline/apps/run_step2.py <config.py>`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_step2.py <user> <exp> <pre_secs> <post_secs> <run_bonvision> <run_s2p_timestamp> <run_ephys> <run_dlc_timestamp> <run_cuttraces>`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_cam.py`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_ephys.py`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_cut.py`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_bv.py`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_pupil_timestamp.py`

These wrappers do not require `conda develop` because they prepend `/home/adamranson/code/lab_pipeline/src` to `sys.path` themselves.

## Environment expectations

- `apps/run_step1.py`
  - submission only, standard Python environment is fine
- `apps/preprocess_step1.py`
  - standard Python environment, but it launches Suite2p/DLC/pupil subprocesses in their target envs
- `apps/s2p_launcher.py`
  - run inside the `suite2p` environment
- `apps/dlc_launcher.py`
  - run inside the `DLC_05_02_2026` environment
- `apps/preprocess_pupil.py`
  - run inside the `sci` environment
- `apps/preprocess_s2p.py`
  - run inside the environment that has the scientific Python stack required by Suite2p postprocessing
- `apps/run_step2.py` / `apps/preprocess_step2.py`
  - standard scientific Python environment with the step-2 dependencies

## Ready-to-run examples

- `/home/adamranson/code/lab_pipeline/configs/config_example_run_step1_standard.py`
- `/home/adamranson/code/lab_pipeline/configs/config_example_run_step1_dual_channel.py`
- `/home/adamranson/code/lab_pipeline/configs/config_example_run_step1_standard_combined.py`
- `/home/adamranson/code/lab_pipeline/configs/config_example_run_step1_meso.py`
- `/home/adamranson/code/lab_pipeline/configs/config_example_run_step1_meso_dual_channel.py`
- `/home/adamranson/code/lab_pipeline/configs/config_example_run_step1_meso_combined.py`
- `/home/adamranson/code/lab_pipeline/configs/config_example_run_step2_standard.py`
- `/home/adamranson/code/lab_pipeline/configs/config_example_run_step2_meso.py`

## Next migration steps

- continue promoting only the canonical universal path into `src/preprocess_pipeline`
- move configs into `configs/`
- add tests around queue planning, work-unit discovery, and direct subsystem entrypoints
- archive or explicitly freeze legacy-only code once the universal path is fully validated
