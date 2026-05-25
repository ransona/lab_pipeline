# Architecture

## Canonical rule

`src/preprocess_pipeline/` is the only place for forward-path code.

## Legacy rule

`legacy/` is reference history, not the place to continue building the pipeline.

## Workflow-first layout

- `shared/`: cross-cutting helpers
- `queue/`: queue processing and dispatch
- `step1/`: queue submission, runtime orchestration, combined split tools
- `suite2p/`: Suite2p launcher and downstream Suite2p preprocessing
- `dlc/`: DeepLabCut launch
- `pupil/`: pupil fitting

## Entry-point rule

Each subsystem should remain runnable outside the full pipeline.

That means:
- canonical modules keep direct callable functions
- where practical they also keep a `main()`
- `apps/` contains thin wrappers only
