# lab_pipeline

Canonical preprocessing repository for the lab pipeline.

The repo is organised around workflow, not around old script-vs-library splits:

- `src/preprocess_pipeline/`
  - importable pipeline code
  - queueing, step 1, step 2, Suite2p, DLC, pupil, viewers, utilities
- `apps/`
  - thin runnable shims for direct execution of subsystems and GUIs
- `configs/`
  - runnable example configs, debug configs, and local configs
- `docs/`
  - short reference notes
- `legacy/`
  - archived historical code snapshots kept for reference only

`apps/` shims prepend `src/` to `sys.path`, so you do not need `conda develop` for normal use.

## How To Use It

The usual workflow is:

1. Pick a config in `configs/examples/`, `configs/debug/`, or `configs/local/`.
2. Edit `userID`, `expIDs`, and the relevant config fields.
3. Run the config directly with `python`.
4. Watch or inspect the job with the queue GUI if it was submitted to the queue.

Step 1 config files are self-runnable and submit jobs when executed:

```bash
python /home/adamranson/code/lab_pipeline/configs/examples/config_example_run_step1_standard.py
python /home/adamranson/code/lab_pipeline/configs/debug/config_example_run_step1_standard.py
```

Step 2 config files are also self-runnable and run immediately:

```bash
python /home/adamranson/code/lab_pipeline/configs/examples/config_example_run_step2_standard.py
python /home/adamranson/code/lab_pipeline/configs/debug/config_example_run_step2_standard.py
```

## Queue And Jobs

Step 1 jobs are added by running a Step 1 config file. The config decides whether the job goes to the normal queue or the debug queue.

- normal queue:
  - leave `step1_config["queue"]` unset, or set it to `"step1"`
- debug queue:
  - set `step1_config["queue"] = "debug"`

The queue GUI is for monitoring, inspecting, and removing queued jobs. It does not create jobs by itself.

Launch the queue GUI with:

```bash
/opt/scripts/conda-run.sh sci python /home/adamranson/code/lab_pipeline/apps/qview.py
```

If you need the listener manually, the new queue listener can be run with:

```bash
/opt/scripts/conda-run.sh base python /home/adamranson/code/lab_pipeline/apps/queue_listener.py
/opt/scripts/conda-run.sh base python /home/adamranson/code/lab_pipeline/apps/queue_listener.py --debug
```

The debug queue uses `/data/common/queues/debug/`. The normal queue uses `/data/common/queues/step1/`.

## GUIs

Queue manager:

```bash
/opt/scripts/conda-run.sh sci python /home/adamranson/code/lab_pipeline/apps/qview.py
```

Imaging viewer with raw TIFF and Suite2p binary modes:

```bash
/opt/scripts/conda-run.sh sci python /home/adamranson/code/lab_pipeline/apps/imaging_view.py
```

Standalone Suite2p binary viewer:

```bash
/opt/scripts/conda-run.sh sci python /home/adamranson/code/lab_pipeline/apps/s2p_bin_view.py
```

Eye-check viewer:

```bash
/opt/scripts/conda-run.sh sci python /home/adamranson/code/lab_pipeline/apps/eye_check.py
```

## Step 1 Configs

Step 1 config files define:

- `userID`
- `expIDs`
- `suite2p_config`
- `runs2p`
- `rundlc`
- `runfitpupil`
- optional `runsrdtrans`
- optional `srdtrans`
- optional `queue`
- optional `jump_queue`
- optional `suite2p_env`
- optional `settings`

The universal Step 1 submitter supports these `suite2p_config` shapes:

### 1. One config string

Use the same Suite2p config for every work unit.

```python
step1_config["suite2p_config"] = "ch_1_depth_1.npy"
```

### 2. One or two configs in a list

For standard dual-channel data, pass one config per channel.

```python
step1_config["suite2p_config"] = [
    "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
    "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy",
]
```

### 3. A mapping with `default` and optional `overrides`

Use this when most work units share a config, but a few need special handling.

```python
step1_config["suite2p_config"] = {
    "default": "ch_1_depth_1.npy",
    "overrides": {
        "P1/R002": "ch_1_depth_1_special.npy",
    },
}
```

You can also use a default dual-channel pair:

```python
step1_config["suite2p_config"] = {
    "default": [
        "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
        "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy",
    ],
}
```

### 4. A direct work-unit mapping

This is the most explicit form. Use work-unit IDs such as `root` for standard data, or `P1/R001` for mesoscope data.

```python
step1_config["suite2p_config"] = {
    "root": "ch_1_depth_1.npy",
    "P1/R001": "ch_1_depth_1.npy",
    "P1/R002": "ch_1_depth_1.npy",
}
```

For explicit dual-channel overrides:

```python
step1_config["suite2p_config"] = {
    "default": [
        "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
        "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy",
    ],
    "overrides": {
        "P1/R002": [
            "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
            "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy",
        ],
    },
}
```

### Standard experiment examples

Single experiment:

```python
step1_config["expIDs"] = ["2026-05-11_03_ESRC033"]
step1_config["suite2p_config"] = "ch_1_depth_1.npy"
```

Combined experiment:

```python
step1_config["expIDs"] = [["2026-05-11_03_ESRC033", "2026-05-11_99_ESRC033"]]
step1_config["suite2p_config"] = "ch_1_depth_1.npy"
```

Dual-channel standard experiment:

```python
step1_config["suite2p_config"] = [
    "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
    "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy",
]
```

### Meso experiment examples

Same config for all paths and ROIs:

```python
step1_config["suite2p_config"] = {
    "default": "ch_1_depth_1.npy",
}
```

Same dual-channel pair for all paths and ROIs:

```python
step1_config["suite2p_config"] = {
    "default": [
        "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
        "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy",
    ],
}
```

Explicit per-path or per-ROI overrides:

```python
step1_config["suite2p_config"] = {
    "default": "ch_1_depth_1.npy",
    "overrides": {
        "P1/R001": "ch_1_depth_1.npy",
        "P1/R002": "ch_1_depth_1_special.npy",
    },
}
```

The GUI in `apps/qview.py` can build these forms for you.

## Step 2 Configs

Step 2 runs directly, not through the queue listener.

Typical fields:

- `userID`
- `expIDs`
- `pre_secs`
- `post_secs`
- `run_bonvision`
- `run_s2p_timestamp`
- `run_ephys`
- `run_dlc_timestamp`
- `run_cuttraces`
- optional `settings`

Example:

```python
step2_config["userID"] = "adamranson"
step2_config["expIDs"] = ["2026-05-11_03_ESRC033"]
step2_config["pre_secs"] = 5
step2_config["post_secs"] = 5
step2_config["run_bonvision"] = True
step2_config["run_s2p_timestamp"] = True
step2_config["run_ephys"] = True
step2_config["run_dlc_timestamp"] = True
step2_config["run_cuttraces"] = True
```

The default example settings include:

```python
settings["neuropil_coeff"] = [0.7, 0.7]
settings["subtract_overall_frame"] = False
```

## Local Mode

For a local workstation or Windows machine, set:

```python
step1_config["local_repository_root"] = r"D:\data\Repository"
step2_config["local_repository_root"] = r"D:\data\Repository"
```

Local mode:

- bypasses the queue
- writes outputs under `<local_repository_root>/<animalID>/<expID>`
- is intended for direct Step 1 and Step 2 execution
- still uses the normal Suite2p config files and local envs

## Environment Expectations

- `apps/qview.py`
  - run in `sci`
- `apps/imaging_view.py`
  - run in `sci`
- `apps/s2p_bin_view.py`
  - run in `sci`
- `apps/eye_check.py`
  - run in `sci`
- `apps/s2p_launcher.py`
  - run in `suite2p`
- `apps/dlc_launcher.py`
  - run in `DLC_05_02_2026`
- `apps/preprocess_pupil.py`
  - run in `sci`
- `apps/srdtrans_launcher.py`
  - run in `srdtrans`

The Step 1 and Step 2 config files can be executed directly from any normal shell as long as the required downstream envs are available for the subprocesses they launch.
