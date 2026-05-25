# preprocess_scripts

Queue submission scripts for running preprocessing jobs.

## Step 1

The normal way to launch preprocessing is:

```bash
cd /home/adamranson/code/preprocess_scripts
python /home/adamranson/code/preprocess_scripts/config_example_run_step1.py
```

That config script builds a `step1_config` dict and submits it through `run_step1_batch.py`.

## Normal Suite2p Run

Use a single Suite2p config file:

```python
step1_config['userID'] = 'adamranson'
step1_config['expIDs'] = ['2024-10-28_06_ESMT190']
step1_config['suite2p_config'] = 'ch_1_depth_1.npy'
step1_config['runs2p'] = True
step1_config['rundlc'] = True
step1_config['runfitpupil'] = True
step1_config['suite2p_env'] = 'suite2p'
```

Run it with:

```bash
python /home/adamranson/code/preprocess_scripts/config_example_run_step1.py
```

This uses one Suite2p ops file for the whole run.

## Multi-Plane Multi-Channel Run

The standard dual-channel path now accepts two Suite2p config files:

```python
step1_config['suite2p_config'] = [
    'ch1_config.npy',
    'ch2_config.npy',
]
```

This means:

1. registration runs once on the raw two-channel data using config 1
2. channel 1 extraction/deconvolution runs with config 1
3. channel 2 extraction/deconvolution runs with config 2

For the current RSC axon-paper example:

```python
step1_config['userID'] = 'adamranson'
step1_config['expIDs'] = ['2026-05-11_03_ESRC033']
step1_config['suite2p_config'] = [
    'ch_2_depth_x_zoom_8_axon_jGCaMP8m.npy',
    'ch_2_depth_x_zoom_8_soma_jRGECO1a.npy',
]
step1_config['runs2p'] = True
step1_config['rundlc'] = False
step1_config['runfitpupil'] = False
```

Run it with:

```bash
python /home/adamranson/code/preprocess_scripts/configs/rsc_axon_paper/config_example_run_step1_dual_channel.py
```

The two config files are expected at:

```text
/data/common/configs/s2p_configs/<userID>/<config_name>.npy
```

For this dual-channel path, the current output layout is:

- root `suite2p/plane*`: green-channel bin and green extraction outputs
- `ch2/suite2p/plane*`: red-channel bin and red extraction outputs

Each output tree is written as a single-channel extraction result, but both reuse the same shared registration pass.

## Combined Runs

To run multiple experiments in one Suite2p job, set:

```python
step1_config['expIDs'] = [[
    '2023-02-28_13_ESMT116',
    '2023-02-28_14_ESMT116',
]]
```

This queues:

1. one combined Suite2p run across all listed raw experiment folders
2. one non-Suite2p follow-up job per experiment for the other step-1 work

The combined Suite2p output is written under the first experiment's processed folder.

## split_combined_s2p.py

`split_combined_s2p.py` is used after a combined Suite2p run to split the combined output back into per-experiment outputs.

It does this by:

1. renaming the original combined `suite2p/` tree to `suite2p_combined/`
2. reading each plane's own `ops.npy`
3. using that plane's `frames_per_folder` to determine how many frames belong to each experiment
4. cropping `F.npy`, `Fneu.npy`, `spks.npy`, and `data.bin` for each experiment
5. recreating per-experiment `suite2p/plane*` folders
6. rewriting each split `ops.npy` so its paths and frame counts point at the new local split outputs

If the combined run also produced `ch2/suite2p/`, the script repeats the same split for the `ch2` tree.

## Notes

- `step1_config['suite2p_config']` must be either:
  - a single config filename
  - a two-item list `[ch1_config, ch2_config]`
- `run_step1_batch.py` validates that the referenced config files exist before queueing the job.
- Processed data are written under:

```text
/home/<userID>/data/Repository/<animal>/<expID>/
```
