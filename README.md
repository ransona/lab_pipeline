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

## Resolving Experiment Paths

Use the path resolver whenever code needs to locate raw or processed experiment data without hard-coding full directories. Given only a `userID` and an `expID`, it derives the `animalID`, the raw repository path, and the processed repository path using the lab's standard `animalID/expID` folder layout.

The old `organise_paths.find_paths(userID, expID)` helper has been replaced by:

```python
from preprocess_pipeline.shared import paths

animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw = paths.find_paths(
    userID,
    expID,
)
```

The return values are:

- `animalID`: animal ID parsed from the experiment ID.
- `remote_repository_root`: root of the raw remote repository.
- `processed_root`: root of the processed repository for that user.
- `exp_dir_processed`: processed experiment folder.
- `exp_dir_raw`: raw experiment folder.

If you are running from one of this repo's `apps/` shims or `configs/` examples, `src/` is already added to `sys.path`. In your own external script, either install the repo in editable mode or add `src/` explicitly:

```python
from pathlib import Path
import sys

LAB_PIPELINE = Path("/home/adamranson/code/lab_pipeline")
sys.path.insert(0, str(LAB_PIPELINE / "src"))

from preprocess_pipeline.shared import paths

userID = "adamranson"
expID = "2026-02-23_02_ESRC033"

(
    animalID,
    remote_repository_root,
    processed_root,
    exp_dir_processed,
    exp_dir_raw,
) = paths.find_paths(userID, expID)

print("animalID:", animalID)
print("remote_repository_root:", remote_repository_root)
print("processed_root:", processed_root)
print("exp_dir_processed:", exp_dir_processed)
print("exp_dir_raw:", exp_dir_raw)
```

On the server, this prints:

```text
animalID: ESRC033
remote_repository_root: /data/Remote_Repository
processed_root: /home/adamranson/data/Repository
exp_dir_processed: /home/adamranson/data/Repository/ESRC033/2026-02-23_02_ESRC033
exp_dir_raw: /data/Remote_Repository/ESRC033/2026-02-23_02_ESRC033
```

For habituation data, use `userID="habit"` when resolving already-moved habituation experiments:

```python
from preprocess_pipeline.shared import paths

print(paths.find_paths("habit", "2026-01-19_01_ESRC026"))
```

Example output:

```text
('ESRC026', '/data/Remote_Repository', '/data/common/habituation', '/data/common/habituation/ESRC026/2026-01-19_01_ESRC026', '/data/common/habituation/ESRC026/2026-01-19_01_ESRC026')
```

For local Windows or non-server processing, pass local roots directly:

```python
from preprocess_pipeline.shared import paths

paths.find_paths(
    "adamranson",
    "2025-10-30_10_ESYB025",
    local_raw_repository_root=r"D:\data\Repository",
    local_processed_repository_root=r"F:\Local_Repository_Processed",
    local_nas_repository_root=r"\\ar-lab-nas1\DataServer\Remote_Repository",
)
```

The same local roots can also be set through environment variables:

- `LAB_PIPELINE_LOCAL_REPOSITORY_ROOT`
- `LAB_PIPELINE_LOCAL_RAW_REPOSITORY_ROOT`
- `LAB_PIPELINE_LOCAL_PROCESSED_REPOSITORY_ROOT`
- `LAB_PIPELINE_LOCAL_NAS_REPOSITORY_ROOT`

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
2. Add one or more `expIDs`, or click `Picker` to insert saved experiments/groups.
3. Wait for the experiment summary to appear.
4. Pick the correct Suite2p config form for the detected topology.
5. Leave the queue selector on `Normal` or switch it to `Debug`.
6. Click `Submit Step 1 Job`.

Step 2 is not queued. The `Step 2` tab builds and runs the Step 2 config directly, and also has a `Picker` button for inserting saved experiments/groups.

The `Picker` tab stores a personal hierarchical experiment tree in:

```text
~/.config/lab_pipeline/experiment_picker.sqlite
```

Use it to make groups and subgroups, add experiments by `userID`/`expID` or by selecting an experiment folder, and attach notes to each experiment. Experiment imaging metadata is cached in the SQLite file, but processing information is read live from each processed experiment's `pipeline_config.pickle` so it reflects the most recent pipeline execution. Step 1 now writes that `pipeline_config.pickle` into each processed experiment folder when a job runs.

When qView starts, it backs up the Picker database at most once per calendar month if the database already exists. Backups are written next to the database as `experiment_picker_backup_YYYY-MM-DD.sqlite`.

If you need the listener manually, the new queue listener can be run with:

```bash
/opt/scripts/conda-run.sh base python /home/[username]/code/lab_pipeline/apps/queue_listener.py
/opt/scripts/conda-run.sh base python /home/[username]/code/lab_pipeline/apps/queue_listener.py --debug
```

The debug queue uses `/data/common/queues/debug/`. The normal queue uses `/data/common/queues/step1/`.

## GUIs

The main GUI entry points are `qview.py`, `imaging_view.py`, and `eye_check.py`. See `Apps And Launchers` at the top of this README for Linux commands and Windows `.bat` launchers.

In the qView `Build SRDTrans` tab, `1) Register data`, `2) Extract frames`, and `3) Build model` launch in detached `tmux` sessions and write logs under the model folder, for example:

```text
/data/common/srdtrans_models/<model_name>/logs/<action>_YYYYMMDD_HHMMSS.log
```

qView tails that log while it remains open, but the action continues if the GUI or SSH session disconnects. The GUI shows the exact `tmux attach -t ...` command after launch. Use `Save config` after editing frame selections if you want to persist changes before launching an action.

The `Build SRDTrans` tab can resume a partially built model with `Load existing`. Select the model's `build_config.json`; the GUI reloads experiments, Suite2p configs, frame selections, training parameters, and the latest action log. If a matching detached action tmux session is still running, qView reconnects to it and resumes tailing the log.

Detached SRDTrans build tmux sessions self-expire after seven days. qView also cleans up stale `srdtrans_register_*`, `srdtrans_extract_*`, and `srdtrans_build_*` sessions older than seven days on startup.

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

## SRDTrans Denoising

SRDTrans is an optional Step 1 Suite2p path. It is enabled by setting `runsrdtrans=True` and providing `step1_config["srdtrans"]`.

The current processing order is:

1. Suite2p performs an initial shared rigid registration pass.
2. SRDTrans denoises the registered `data.bin` files in place.
3. Suite2p runs the final requested registration, normally non-rigid, plus ROI detection and extraction on the denoised binaries.

The pre-denoise registered binaries are overwritten rather than kept as separate copies, to avoid duplicating large binary files.

Example:

```python
step1_config["runsrdtrans"] = True
step1_config["srdtrans"] = {
    "model_root": "/home/adamranson/data/srt_models",
    "model": "mixed_axon_soma_g8_202412022250",
    "gpu": "0,1",
    "channels": ["ch1"],
    "progress_interval": 1000,
}
```

Supported cases:

- single-channel Suite2p
- dual-channel Suite2p with one shared config
- dual-channel Suite2p with separate channel configs; final registration is still shared, then extraction runs separately per channel config
- multi-plane data
- channel-specific denoising via `srdtrans["channels"]`, for example `["ch1"]`, `["ch2"]`, or `["ch1", "ch2"]`

For dual-channel data without `Register with summed channel`, one channel/config is used for shared registration and those offsets are applied to both channels, matching the normal dual-channel path. `Register with summed channel` is a separate optional Suite2p setting. When enabled, the initial and final shared-registration offsets are computed from `ch1 + ch2`, then applied back to the separate channel binaries before extraction.

Required SRDTrans fields:

- `model_root`: folder containing SRDTrans model folders
- `model`: model folder name under `model_root`
- `gpu`: GPU string passed to SRDTrans, for example `"0"` or `"0,1"`
- `channels`: channels to denoise
- `progress_interval`: optional patch-progress print interval; default is `1000`

Current caveat: the GUI SRDTrans JSON editor can still be left with an empty `"model": ""`. If `runsrdtrans=True`, make sure `model` is filled in before submitting the job. Otherwise Suite2p can complete the initial registration and then SRDTrans will fail with `ValueError: SRDTrans config requires model_root and model`.

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
step1_config["local_processed_repository_root"] = r"F:\Local_Repository_Processed"
step1_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"
step1_config["suite2p_config_root"] = r"F:\s2p_ops"

step2_config["local_raw_repository_root"] = r"D:\data\Repository"
step2_config["local_processed_repository_root"] = r"F:\Local_Repository_Processed"
step2_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"
```

Local mode:

- bypasses the queue
- reads imaging data from `<local_raw_repository_root>/<animalID>/<expID>`
- writes outputs under `<local_processed_repository_root>/<userID>/<animalID>/<expID>`
- falls back to `<local_nas_repository_root>/<animalID>/<expID>` for missing named metadata files
- is intended for direct Step 1 and Step 2 execution
- still uses the normal Suite2p config files and local envs

The older `local_repository_root` setting is still accepted as a shortcut where raw and processed data live in the same tree, but the split-root form above is preferred.

### Local dependencies

For local Step 1 and Step 2 processing, install the pipeline on the workstation and make these environments available:

- `sci` or equivalent analysis env: runs the config files, Step 2, BonVision processing, trace cutting, and general pipeline code.
- `suite2p` env: required for Step 1 Suite2p processing. The Step 1 runner calls this env when `runs2p=True`.
- Suite2p config files: available under `F:\s2p_ops\<userID>\` for local Windows runs, or under `/data/common/configs/s2p_configs/<userID>/` on the server.
- NAS access: the Windows UNC path `\\ar-lab-nas1\DataServer\Remote_Repository` must be readable for missing metadata fallback.
- Python packages for Step 2: `numpy`, `scipy`, `pandas`, `scikit-learn`, `matplotlib`, `scikit-image`, `opencv-python`, `tifffile`, and `suite2p` where relevant.
- BonVision v2 support: `harp` is needed when processing newer BonVision/Harp experiments.
- DLC and pupil support: only needed if `rundlc=True`, `runfitpupil=True`, or `run_dlc_timestamp=True`; the default local examples leave these off.
- Element/Matrix notifications: optional. Local runs continue silently if Matrix/Element packages, tokens, or server config are not present. Set `LAB_PIPELINE_DISABLE_ELEMENT=1` to disable notification attempts explicitly.

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
F:\Local_Repository_Processed\<userID>\ESYB025\2025-10-30_10_ESYB025\
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
step1_config["local_processed_repository_root"] = r"F:\Local_Repository_Processed"
step1_config["local_nas_repository_root"] = r"\\ar-lab-nas1\DataServer\Remote_Repository"
step1_config["suite2p_config_root"] = r"F:\s2p_ops"

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
<suite2p_config_root>\<userID>\
```

For local Windows processing, the default is:

```text
F:\s2p_ops\<userID>\
```

You can override this with `step1_config["suite2p_config_root"]` or the environment variable `LAB_PIPELINE_S2P_CONFIG_ROOT`.

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
step2_config["local_processed_repository_root"] = r"F:\Local_Repository_Processed"
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
