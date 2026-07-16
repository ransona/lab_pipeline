# Data Manager

Data Manager is a Tk GUI plus a small set of command-line maintenance scripts for
reviewing lab repository data, assigning ownership, marking data for deletion, and
executing approved deletions.

The normal user-facing entry point is:

```bash
/opt/scripts/conda-run.sh lab_pipeline python /home/<username>/code/lab_pipeline/apps/data_manager.py
```

`apps/data_manager.py` is only a launcher shim. It resolves this directory under
`src/preprocess_pipeline/viewers/external/data_manager`, prepends it to
`sys.path`, changes the process working directory here, and executes `main.py`.
That setup matters because the external app imports the local `data_manager`
package directly and reads local files such as `exclude_dirs.txt`.

## Components

- `apps/data_manager.py`: repository-level launcher used by Linux and Windows
  launch commands.
- `main.py`: constructs `DataManagerApp` and starts the Tk event loop.
- `data_manager/gui.py`: GUI, delete-list workflow, ownership overrides,
  conflict handling, usage display, TIFF cleanup marking, and orphan view.
- `data_manager/scanner.py`: discovers raw and processed animal/experiment
  folders and computes cached metrics.
- `data_manager/database.py`: shared SQLite state store.
- `delete_runner.py`: destructive admin-side job processor that reads pending
  deletion requests from SQLite and removes files/folders from disk.
- `scan_verbose.py`: command-line scanner that can populate metrics immediately
  or run nightly with `--watch`.
- `nas_clear.py`: optional NAS cleanup helper used before destructive deletion
  to remove old data already synced to the server.

## Paths and shared state

Default paths are defined in `data_manager/config.py`:

- Raw server data: `/data/Remote_Repository`
- Processed data: `/home/<user>/Data/Repository` or
  `/home/<user>/data/Repository`
- User initials map: `/data/common/configs/data_manager/users.txt`
- Shared SQLite DB: `/data/common/configs/data_manager/data_manager.db`
- GUI action logs: `/data/common/configs/data_manager/data_gui_<user>.txt`
- Delete runner log: `/data/common/configs/data_manager/delete_runner_log.txt`

The SQLite database is opened in WAL mode so multiple GUI sessions can write at
the same time. Tables are created automatically:

- `ownership_overrides`: manual owner assignments by scope, animal, and expID.
- `kill_list`: folder-level deletion requests and their status.
- `deletion_blocks`: raw deletion conflicts caused by processed data belonging
  to other users.
- `metrics`: cached folder size and latest file access time, keyed by scope,
  processed user, animal, and expID.
- `file_deletions`: file-level deletion requests, currently used for raw TIFFs.
- `imaging_deletions`: grouped imaging-only file and directory targets.
- `animal_deletions`: explicit recursive whole-animal folder requests.

## Discovery and ownership

The GUI scans two scopes:

- `raw`: animal and experiment directories under `/data/Remote_Repository`.
- `processed`: each user's repository under `/home/<user>/Data/Repository` and
  `/home/<user>/data/Repository`.

Entries listed in `exclude_dirs.txt` are skipped by name. Raw experiment
ownership is read from `<expID>_experiment_metadata.json` when that file exists
inside the raw experiment folder:

```json
{
  "expID": "2026-06-18_16_TEST",
  "animalID": "TEST",
  "user": "yannickbollmann"
}
```

Manual overrides in `ownership_overrides` still take precedence over metadata.
If no metadata user is available, raw-data ownership is shown as unknown.

For processed data, the default owner is the home-directory user. Applying an
owner override to an animal also writes overrides for the visible child
experiments.

## GUI workflow

On startup the GUI selects the current Linux user. The `adamranson` user gets an
`all` view and can switch to any `/home/*` user; other users are restricted to
their own selection.

The main window has raw and processed tree views. Each tree shows animals with
experiment children, cached size, cached last-access time, owner, and deletion
state. `Scan metrics (background)` walks the currently loaded nodes, computes
total bytes plus latest file `atime`, and stores the result in `metrics`.
Processed metrics are stored per home-directory user so same-named animals under
different users do not share cached sizes.

Common actions:

- `Refresh`: rescan directory structure and reload SQLite state.
- `Mark for deletion` or right-click: toggle deletion marking for selected
  experiments. Selecting an animal requests recursive deletion of the complete
  animal folder after confirmation. Raw whole-animal requests are rejected when
  another user has processed data for that animal, and the runner checks again
  immediately before deletion.
- `View delete list`: inspect pending, blocked, deleted, and file-level deletion
  rows grouped by owner.
- `Conflicts`: resolve raw deletion conflicts where processed data exists.
- `Show all conflicts`: admin-style overview of blocked deletion requests.
- `Scan for removable tifs`: find raw TIFF files for experiments that already
  have processed Suite2p `.bin` files, then write per-file deletion requests.
- `Show orphans`: find processed experiments or animals whose raw experiment is
  absent or already marked for deletion.
- `Show usage`: summarize cached raw and processed usage by owner.

Pressing Space in either data tree toggles imaging-only deletion for selected
experiments. Raw imaging cleanup tags all `.tif` and `.tiff` files recursively.
Processed cleanup tags directories named `suite2p`, `suite2p_combined`, `ch2`,
`P0`, `P1`, or `P2`, plus `recordings/s2p_*.pickle` and
`cut/s2p_*.pickle`. Selecting an animal applies the action to its visible
experiments after confirmation. Imaging-only rows are struck through and shown
with `(imaging)`; full experiment deletion continues to use the existing mark.

The non-modal `Debug` window reports deletion tagging while it is open. Its
output automatically scrolls, and `Delete output` clears the displayed text.

Normal GUI use does not delete data from disk. It only updates SQLite and writes
per-user action logs.

### Simple deletion steps

1. Start Data Manager and select the user whose raw or processed data you want
   to manage.
2. To remove one experiment, select its row in the raw or processed tree and
   click `Mark for deletion` or right-click it.
3. To remove a complete animal, select the animal row, click
   `Mark for deletion` or right-click it, then confirm the whole-animal warning.
4. For raw requests, open `Conflicts` and resolve any processed-data conflicts.
   Blocked requests are not deleted.
5. Open `View delete list` and check every pending path before continuing.
6. Run the deletion processor from a terminal:

   ```bash
   cd /home/<username>/code/lab_pipeline/src/preprocess_pipeline/viewers/external/data_manager
   sudo /home/<username>/miniconda3/envs/lab_pipeline/bin/python delete_runner.py
   ```

7. Read the displayed paths and sizes, then answer `y` only when they are
   correct. The same procedure handles both raw and processed requests.
8. Return to Data Manager and click `Refresh` to update the trees.

### Remove only imaging data

1. Select one or more experiment rows in either tree and press Space.
2. To apply imaging-only cleanup to every visible experiment for an animal,
   select the animal row, press Space, and confirm the prompt.
3. A raw imaging request includes all `.tif` and `.tiff` files below the
   selected experiment, but leaves the experiment folder and other raw files.
4. A processed imaging request includes `suite2p`, `suite2p_combined`, `ch2`,
   `P0`, `P1`, and `P2` directories, plus `recordings/s2p_*.pickle` and
   `cut/s2p_*.pickle` files. Other processed outputs remain in place.
5. Imaging-only requests are crossed out and labelled `(imaging)`. Press Space
   again to unmark them.
6. Review the targets in `View delete list`, then run `delete_runner.py` using
   the same terminal command shown above.

### Watch tagging in the Debug window

1. Click `Debug` before marking or unmarking deletion requests.
2. Leave the non-modal Debug window open while using the main Data Manager
   window.
3. Full experiments, whole animals, imaging targets, and individual files are
   appended to the multiline output as they are tagged. The view scrolls to the
   newest entry automatically.
4. Debug messages are shown only while the Debug window is open. Click
   `Delete output` to clear the displayed messages without changing any
   deletion requests.

## Deletion request states

Folder-level deletion requests live in `kill_list`:

- `pending`: eligible for `delete_runner.py`.
- `blocked`: requested, but at least one pending `deletion_blocks` row exists.
- `deleted`: the runner successfully removed the corresponding path.

Raw and processed rows are treated differently in the main data trees:

- Raw data remains marked after any deletion request, including rows already
  marked `deleted`. Raw expIDs are treated as permanent experiment identities and
  are not expected to be regenerated.
- Processed data is marked only for `pending` and `blocked` requests. Processed
  `deleted` rows are kept as history in the delete list, but do not mark a
  same-named processed folder if it is recreated later.

When a user marks raw data for deletion, the GUI checks all processed
repositories for the same animal/expID. If processed data exists for another
user, the raw request is stored as `blocked` and a `deletion_blocks` row is
created for each blocking processed-data user. Blocking users can open
`Conflicts` and either:

- `Allow deletion`: remove their block. When the last block is removed, the raw
  request becomes `pending`.
- `Keep (take ownership)`: set themselves as owner override and clear the
  deletion request plus all blocks for that item.

When logged in as `adamranson`, the `Conflicts` window also shows an `Act as`
selector. Choose a user there to view and resolve conflicts as that user without
changing the main raw/processed data filter.

If the actor owns both raw and processed copies, the GUI can either keep
processed data, mark both raw and processed data, or cancel, depending on the
raw/processed conflict prompt option.

File-level raw TIFF deletions are stored separately in `file_deletions` and are
also consumed by the delete runner.

## Admin job processor: `delete_runner.py`

`delete_runner.py` is the destructive job processor for Data Manager. It reads
the shared SQLite database, gathers eligible `pending` folder deletions from
`kill_list` and `pending` file deletions from `file_deletions`, summarizes the
paths and sizes, optionally runs `nas_clear.py`, then deletes from disk.

Typical manual run:

```bash
cd /home/<username>/code/lab_pipeline/src/preprocess_pipeline/viewers/external/data_manager
sudo /home/<username>/miniconda3/envs/lab_pipeline/bin/python delete_runner.py
```

Useful options:

```bash
sudo /home/<username>/miniconda3/envs/lab_pipeline/bin/python delete_runner.py --min-age-days 7
sudo /home/<username>/miniconda3/envs/lab_pipeline/bin/python delete_runner.py --auto
sudo /home/<username>/miniconda3/envs/lab_pipeline/bin/python delete_runner.py --include-deleted
```

Important behavior:

- The runner first verifies it can write to `/data/Remote_Repository`; it exits
  if raw storage is not writable.
- Without `--auto`, it prompts before running `nas_clear.py` and before deleting.
- Raw folder and raw TIFF deletions also attempt to delete the matching path
  under `/mnt/nas2/Remote_Repository`, but only if the resolved NAS path is under
  that root.
- Processed deletion paths are resolved from the `marked_by` user under
  `/home/<user>/Data/Repository` or `/home/<user>/data/Repository`.
- Successful folder deletions are marked `deleted` in `kill_list`.
- Successful whole-animal deletions are marked `deleted` in `animal_deletions`.
- Successful file deletions are removed from `file_deletions`.
- Empty raw and processed animal directories are removed after child deletions.

Defaults in the current code are intentionally important:

- `DEFAULT_MIN_AGE_DAYS = 0`: pending requests are immediately eligible unless
  `--min-age-days` is supplied.
- `DEFAULT_AUTO = False`: the runner prompts interactively by default.
- `DEFAULT_INCLUDE_DELETED = False`: rows already marked `deleted` are not
  retried unless `--include-deleted` is supplied. This prevents old deletion
  requests from deleting a newly recreated folder with the same animal/expID.

## NAS cleanup helper

`nas_clear.py` is optional and interactive. It compares `/mnt/nas2/Remote_Repository`
against `/data/Remote_Repository` with an rsync dry run, identifies old NAS items
that already exist on the server, and can delete those old synced items from the
NAS. The script assumes the NAS is already mounted at `/mnt/nas2`.

Excluded NAS folders are hard-coded in `nas_clear.py`: `refz`, `roi_data`,
`widefield`, and `habituation`.

## Metrics scanner

Use `scan_verbose.py` when you want to populate metrics outside the GUI:

```bash
cd /home/<username>/code/lab_pipeline/src/preprocess_pipeline/viewers/external/data_manager
/opt/scripts/conda-run.sh lab_pipeline python scan_verbose.py
/opt/scripts/conda-run.sh lab_pipeline python scan_verbose.py --watch
```

Without `--watch`, it scans once. With `--watch`, it scans immediately and then
schedules nightly scans at 01:00, with Enter triggering an extra manual run.

## Notes and caveats

- Last access time comes from filesystem `atime`; on filesystems with disabled
  or coarse atime updates, it may be stale or blank.
- Size and usage values are cached. Use `Scan metrics (background)` or
  `scan_verbose.py` to update them.
- The GUI can clear all kill-list, block, and file-deletion rows from the Admin
  panel for `adamranson`.
- The code is designed around the server path layout above. If testing
  elsewhere, instantiate `DataManagerApp(DataPaths(...))` rather than changing
  global defaults.
