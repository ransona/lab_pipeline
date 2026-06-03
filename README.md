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
step1_config["local_raw_repository_root"] = r"D:\data\Repository"
step1_config["local_processed_repository_root"] = r"D:\processed\Repository"
step1_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"

step2_config["local_raw_repository_root"] = r"D:\data\Repository"
step2_config["local_processed_repository_root"] = r"D:\processed\Repository"
step2_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"
```

Local mode:

- bypasses the queue
- reads imaging data from `<local_raw_repository_root>/<animalID>/<expID>`
- writes outputs under `<local_processed_repository_root>/<animalID>/<expID>`
- falls back to `<local_nas_repository_root>/<animalID>/<expID>` for missing named metadata files
- is intended for direct Step 1 and Step 2 execution
- still uses the normal Suite2p config files and local envs

The older `local_repository_root` setting is still accepted as a shortcut where raw and processed data live in the same tree, but the split-root form above is preferred.

### Local mesoscope processing

Local mesoscope raw data must match the normal lab repository layout under `local_raw_repository_root`:

```text
D:\data\Repository\
  ESYB025\
    2025-10-30_10_ESYB025\
      P1\
        R001\
          *.tif
        R002\
          *.tif
        SI_meta.pickle
```

For mesoscope experiments, the pipeline detects the `P*/R*` folders automatically. Each ROI folder becomes a Suite2p work unit, for example `P1/R001` and `P1/R002`. Outputs are written under `local_processed_repository_root`:

```text
D:\processed\Repository\ESYB025\2025-10-30_10_ESYB025\
  P1\R001\suite2p\
  P1\R002\suite2p\
```

Create a local Step 1 config, for example `configs/local/config_run_step1_meso.py`:

```python
from pathlib import Path
import getpass
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step1.run_batch import run_step1_batch_universal

step1_config = {}
step1_config["userID"] = getpass.getuser()
step1_config["expIDs"] = ["2025-10-30_10_ESYB025"]
step1_config["local_raw_repository_root"] = r"D:\data\Repository"
step1_config["local_processed_repository_root"] = r"D:\processed\Repository"
step1_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"

# Use one Suite2p config for every mesoscope path/ROI work unit.
step1_config["suite2p_config"] = {
    "default": "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
}

step1_config["runs2p"] = True
step1_config["rundlc"] = False
step1_config["runfitpupil"] = False

run_step1_batch_universal(step1_config)
```

Suite2p config filenames are resolved from:

```text
/data/common/configs/s2p_configs/<userID>/
```

For local processing, make sure the required `.npy` Suite2p configs are available at that path in the environment where Python is running. On a native Windows setup this usually means running through WSL or otherwise making an equivalent `/data/common/...` path available.

For dual-channel mesoscope data, use a default pair:

```python
step1_config["suite2p_config"] = {
    "default": [
        "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
        "ch_2_depth_x_zoom_8_soma_jRGECO1a.npy",
    ],
}
```

For explicit per-ROI control:

```python
step1_config["suite2p_config"] = {
    "default": "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
    "overrides": {
        "P1/R001": "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
        "P1/R002": "ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy",
    },
}
```

Run local Step 1 directly; it is not submitted to the server queue:

```bat
conda activate sci
python D:\code\lab_pipeline\configs\local\config_run_step1_meso.py
```

The Step 1 runner will call the local `suite2p` conda environment for Suite2p work. Keep `rundlc=False` and `runfitpupil=False` unless those local environments and data paths are also configured.

After Step 1 finishes, create a local Step 2 config:

```python
from pathlib import Path
import getpass
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from preprocess_pipeline.step2.run_batch import run_step2_batch

step2_config = {}
step2_config["userID"] = getpass.getuser()
step2_config["expIDs"] = ["2025-10-30_10_ESYB025"]
step2_config["local_raw_repository_root"] = r"D:\data\Repository"
step2_config["local_processed_repository_root"] = r"D:\processed\Repository"
step2_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"
step2_config["pre_secs"] = 5
step2_config["post_secs"] = 5

step2_config["run_bonvision"] = True
step2_config["run_s2p_timestamp"] = True
step2_config["run_ephys"] = False
step2_config["run_dlc_timestamp"] = False
step2_config["run_cuttraces"] = True

step2_config["settings"] = {
    "neuropil_coeff": [0.7, 0.7],
    "subtract_overall_frame": False,
}

run_step2_batch(step2_config)
```

Run Step 2 directly:

```bat
conda activate sci
python D:\code\lab_pipeline\configs\local\config_run_step2_meso.py
```

Local mode limitations:

- It currently assumes the local machine has a working `sci` env and a working `suite2p` env.
- It is intended first for Suite2p and Suite2p postprocessing/trace cutting.
- DLC, pupil fitting, ephys, and Bonvision steps should only be enabled if the required local files and envs are present.
- The normal server queue GUI is not required for local mode; local configs execute immediately.

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
