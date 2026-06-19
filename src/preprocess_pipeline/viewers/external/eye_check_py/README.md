# Eye Check GUI

`eye_view_gui_editor.py` is the canonical in-repository copy of the former
standalone `eye_check_py` application.

Launch it through:

```bash
/opt/scripts/conda-run.sh sci python ~/code/lab_pipeline/apps/eye_check.py
```

The GUI imports the canonical resolver from `preprocess_pipeline.shared.paths`
and does not depend on the retired standalone pipeline repositories.
