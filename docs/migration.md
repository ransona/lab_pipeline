# Migration Notes

## Goal

Create a clean canonical repo for the lab pipeline without modifying the historical source repos.

## Principles

- keep `/home/adamranson/code/preprocess_py` unchanged
- keep `/home/adamranson/code/preprocess_scripts` unchanged
- preserve both histories inside `legacy/`
- promote only the universal path into the canonical package
- keep direct runnable entrypoints for subsystem-level testing

## First reorg pass

The first pass promotes these universal modules into `src/preprocess_pipeline/`:

- shared support:
  - `shared/paths.py`
  - `shared/matrix_notify.py`
  - `shared/file_check.py`
- step 1:
  - `step1/run_batch.py`
  - `step1/runtime.py`
  - `step1/habituate.py`
  - `step1/split_combined_s2p.py`
- queue:
  - `queue/listener.py`
- suite2p:
  - `suite2p/launcher.py`
  - `suite2p/preprocess.py`
- dlc:
  - `dlc/launcher.py`
- pupil:
  - `pupil/core.py`
  - `pupil/preprocess.py`

The next pass promotes the canonical step-2 stack:

- `step2/run_batch.py`
- `step2/runtime.py`
- `behavior/bonvision.py`
- `behavior/preprocess_bv.py`
- `behavior/preprocess_bv2.py`
- `behavior/preprocess_cam.py`
- `behavior/preprocess_cut.py`
- `behavior/preprocess_ephys.py`
- `pupil/timestamp.py`
- `pupil/calibration.py`

## Important cleanup choices

- the new queue listener dispatches the canonical universal job type directly instead of relying on `eval(...)`
- direct testability is preserved through `main()` functions and thin `apps/` wrappers
- the forward path is now “universal only”; non-universal variants are not promoted into `src/`
