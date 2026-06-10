# Suite2p 1.1 Compatibility Branch

This experimental working copy lives at:

```text
/home/adamranson/code/lab_pipeline_s2p110
```

It is intentionally separate from the stable pipeline at:

```text
/home/adamranson/code/lab_pipeline
```

Keep the normal listener pointed at the stable repo. Use this clone only for explicit tests, preferably on the debug queue.

## Running A Test Job

Use the experimental apps path and set the Suite2p environment explicitly:

```python
step1_config["queue"] = "debug"
step1_config["suite2p_env"] = "suite2p_1.1.0"
```

Launch the experimental debug listener only when testing:

```bash
/opt/scripts/conda-run.sh base python /home/adamranson/code/lab_pipeline_s2p110/apps/queue_listener.py --debug
```

Do not launch the experimental normal listener unless you intend to route normal jobs through this clone.

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
