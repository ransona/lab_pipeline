# Suite2p 1.1 Compatibility

Suite2p 1.1 compatibility is integrated into the main pipeline at:

```text
~/code/lab_pipeline
```

## Running A Test Job

Set the Suite2p environment explicitly:

```python
step1_config["queue"] = "debug"
step1_config["suite2p_env"] = "suite2p_1.1.0"
```

Launch the debug listener when testing:

```bash
/opt/scripts/conda-run.sh lab_pipeline python ~/code/lab_pipeline/apps/queue_listener.py --debug
```

## Compatibility Layer

Suite2p compatibility is isolated in:

```text
src/preprocess_pipeline/suite2p/backend.py
```

The launcher keeps using the same high-level pipeline flow, but Suite2p calls now go through backend wrappers. The default `suite2p` env remains compatible with Suite2p `0.14.2`; `suite2p_1.1.0` uses the new `db/settings` API.

The backend normalizes old config fields that break Suite2p 1.x, especially empty `subfolders=[]`, and preserves the canonical pipeline output layout:

```text
<work_unit>/suite2p/plane*/data.bin
<work_unit>/suite2p/plane*/ops.npy
<work_unit>/ch2/suite2p/plane*/data.bin
```

## Probe Status

The current implementation has been smoke-tested with synthetic TIFFs in both envs:

- `suite2p` / Suite2p `0.14.2`: full run and plane rerun passed.
- `suite2p_1.1.0` / Suite2p `1.1.0`: full run and plane rerun passed.

Remaining validation before real use:

- dual-channel two-config real data
- SRDTrans denoise path
- register-with-summed-channel path
- combined experiment split path
