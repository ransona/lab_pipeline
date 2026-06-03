# Windows GUI Launchers

These `.bat` files launch the `lab_pipeline` GUI apps on the `dream` server from a Windows machine.

They assume:

- your Windows SSH config has an alias named `dream`
- `ssh dream "whoami"` returns your remote Linux username
- the repo is at `/home/<username>/code/lab_pipeline`
- SSH X forwarding, or another remote GUI display setup, is available

Launchers:

- `run_queue_gui.bat` starts the queue/config GUI
- `run_imaging_view.bat` starts the combined Suite2p bin / raw TIFF viewer
- `run_eye_check.bat` starts the eye-check GUI adapter

If username detection fails, edit `_run_remote_gui.bat` and set:

```bat
set "CODE_HOME=/home/your_remote_username/code/lab_pipeline"
```

If your SSH alias is not `dream`, edit:

```bat
set "SSH_ALIAS=dream"
```
