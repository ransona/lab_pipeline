# lab_pipeline

Fresh consolidation repo for the lab preprocessing pipeline.

Current state:
- legacy histories are imported under `legacy/`
- the old source repos remain unchanged
- the new canonical structure will be built in this repo over time
- imported legacy snapshots:
  - `legacy/preprocess_py` from `c31fcc6`
  - `legacy/preprocess_scripts` from `8ef0335`

Planned top-level layout:
- `src/preprocess_pipeline/`
- `apps/`
- `configs/`
- `tests/`
- `docs/`
- `legacy/`
