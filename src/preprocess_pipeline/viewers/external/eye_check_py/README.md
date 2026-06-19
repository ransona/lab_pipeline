# Eye Check GUI

`eye_view_gui_editor.py` is the canonical in-repository copy of the former
standalone `eye_check_py` application.

Launch it through:

```bash
/opt/scripts/conda-run.sh sci python ~/code/lab_pipeline/apps/eye_check.py
```

The adapter in `preprocess_pipeline.viewers.eye_check` supplies the current
pipeline path resolver in place of the legacy `organise_paths` module.
