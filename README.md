# lab_pipeline

Canonical preprocessing repository for the lab pipeline.

## Apps And Launchers

Use `[username]` as your Linux username on `dream`.

GUI apps:

| App | Purpose | Linux command | Windows launcher |
| --- | --- | --- | --- |
| `qview.py` | Queue GUI for Step 1/Step 2 job setup, queue inspection, logs, and split tools | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/qview.py` | `windows_launchers/run_queue_gui.bat` |
| `imaging_view.py` | Combined raw TIFF and Suite2p `data.bin` viewer | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/imaging_view.py` | `windows_launchers/run_imaging_view.bat` |
| `eye_check.py` | Eye tracking QC GUI adapter | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/eye_check.py` | `windows_launchers/run_eye_check.bat` |
| `s2p_bin_view.py` | Standalone Suite2p binary viewer, retained for direct use; normally use `imaging_view.py` instead | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/s2p_bin_view.py` | none |

Pipeline and subsystem apps:

| App | Purpose | Typical command |
| --- | --- | --- |
| `queue_listener.py` | Normal Step 1 queue listener | `/opt/scripts/conda-run.sh base python /home/[username]/code/lab_pipeline/apps/queue_listener.py` |
| `queue_listener.py --debug` | Debug Step 1 queue listener | `/opt/scripts/conda-run.sh base python /home/[username]/code/lab_pipeline/apps/queue_listener.py --debug` |
| `run_step1.py` | Submit Step 1 jobs from a config | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/run_step1.py` |
| `run_step2.py` | Run Step 2 jobs from a config | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/run_step2.py` |
| `preprocess_step1.py` | Execute one queued Step 1 runtime job directly | `/opt/scripts/conda-run.sh base python /home/[username]/code/lab_pipeline/apps/preprocess_step1.py` |
| `preprocess_step2.py` | Execute Step 2 runtime directly | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/preprocess_step2.py` |
| `s2p_launcher.py` | Suite2p launcher for one work unit | `/opt/scripts/conda-run.sh suite2p python /home/[username]/code/lab_pipeline/apps/s2p_launcher.py` |
| `dlc_launcher.py` | DeepLabCut launcher | `/opt/scripts/conda-run.sh DLC_05_02_2026 python /home/[username]/code/lab_pipeline/apps/dlc_launcher.py` |
| `srdtrans_launcher.py` | SRDTrans denoising launcher | `/opt/scripts/conda-run.sh suite2p python /home/[username]/code/lab_pipeline/apps/srdtrans_launcher.py` |
| `split_combined_s2p.py` | Split combined Suite2p output back into source experiments | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/split_combined_s2p.py` |
| `preprocess_bv.py` | Bonvision preprocessing | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/preprocess_bv.py` |
| `preprocess_cam.py` | Camera timing preprocessing | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/preprocess_cam.py` |
| `preprocess_cut.py` | Trace cutting/preprocessing helper | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/preprocess_cut.py` |
| `preprocess_ephys.py` | Ephys preprocessing | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/preprocess_ephys.py` |
| `preprocess_habituate.py` | Habituation data copy/preprocessing | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/preprocess_habituate.py` |
| `preprocess_pupil.py` | Pupil preprocessing | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/preprocess_pupil.py` |
| `preprocess_pupil_timestamp.py` | Pupil timestamp alignment | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/preprocess_pupil_timestamp.py` |
| `preprocess_s2p.py` | Suite2p postprocessing/timestamp extraction | `/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/preprocess_s2p.py` |

Windows launchers are in `windows_launchers/`. They assume the SSH alias is `dream`, infer the remote username with `ssh dream "whoami"`, and run the GUI apps from `/home/<username>/code/lab_pipeline`. If inference fails, edit `windows_launchers/_run_remote_gui.bat` and set `CODE_HOME`.

`apps/` shims prepend `src/` to `sys.path`, so you do not need `conda develop` for normal use.

## Repository Layout

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

## How To Use It

The usual workflow is:

1. Open the queue GUI.
2. Build or load a Step 1 config.
3. Submit Step 1 from the GUI.
4. Run Step 2 directly once Step 1 has finished.

The queue GUI is the default Step 1 submission path.

Launch it with:

```bash
/opt/scripts/conda-run.sh sci python /home/[username]/code/lab_pipeline/apps/qview.py
```

Step 1 config files are still self-runnable if you want to bypass the GUI:

```bash
python /home/[username]/code/lab_pipeline/configs/examples/config_example_run_step1_standard.py
python /home/[username]/code/lab_pipeline/configs/debug/config_example_run_step1_standard.py
```

Step 2 config files are also self-runnable and run immediately:

```bash
python /home/[username]/code/lab_pipeline/configs/examples/config_example_run_step2_standard.py
python /home/[username]/code/lab_pipeline/configs/debug/config_example_run_step2_standard.py
```

## Queue And Jobs

The queue GUI is the standard way to add Step 1 jobs. It can also inspect queued jobs, show the queue log, and remove your own queued jobs.

Step 1 queue target:

- normal queue:
  - leave `step1_config["queue"]` unset, or set it to `"step1"`
- debug queue:
  - set `step1_config["queue"] = "debug"`

From the GUI:

1. Open the `Step 1` tab.
2. Add one or more `expIDs`.
3. Wait for the experiment summary to appear.
4. Pick the correct Suite2p config form for the detected topology.
5. Leave the queue selector on `Normal` or switch it to `Debug`.
6. Click `Submit Step 1 Job`.

Step 2 is not queued. The `Step 2` tab is for building the config, but Step 2 itself still runs directly from the config file.

If you need the listener manually, the new queue listener can be run with:

```bash
/opt/scripts/conda-run.sh base python /home/[username]/code/lab_pipeline/apps/queue_listener.py
/opt/scripts/conda-run.sh base python /home/[username]/code/lab_pipeline/apps/queue_listener.py --debug
```

The debug queue uses `/data/common/queues/debug/`. The normal queue uses `/data/common/queues/step1/`.

## GUIs

The main GUI entry points are `qview.py`, `imaging_view.py`, and `eye_check.py`. See `Apps And Launchers` at the top of this README for Linux commands and Windows `.bat` launchers.

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
You can assemble the Step 2 config in the GUI, but the actual run still happens by executing the config file itself.

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
step2_config["userID"] = "[username]"
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
