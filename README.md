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
- `python /home/adamranson/code/lab_pipeline/apps/s2p_launcher.py ...`
- `python /home/adamranson/code/lab_pipeline/apps/dlc_launcher.py <user> <exp>`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_pupil.py <user> <exp>`
- `python /home/adamranson/code/lab_pipeline/apps/preprocess_s2p.py`
- `python /home/adamranson/code/lab_pipeline/apps/split_combined_s2p.py`
- `python /home/adamranson/code/lab_pipeline/apps/queue_listener.py`

## Next migration steps

- continue promoting only the canonical universal path into `src/preprocess_pipeline`
- move configs into `configs/`
- add tests around queue planning, work-unit discovery, and direct subsystem entrypoints
- archive or explicitly freeze legacy-only code once the universal path is fully validated
