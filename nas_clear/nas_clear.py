import subprocess
import os
import re
import sys
from datetime import datetime, timedelta

# NAS must first be mounted using (fill in password):
# sudo mount -t cifs //158.109.209.238/DataServer /mnt/nas2 -o username=nas_clear,password='XXX',vers=1.0
# after unmount:
# sudo umount /mnt/nas2

# Configuration
nas_path = '/mnt/nas2/Remote_Repository/'       # Source (NAS)
server_path = '/data/Remote_Repository/'               # Destination (Server)
age_threshold_days = 21
verbose = True
estimate_space = True   # set to False to skip space estimation

# Folders to exclude from deletion (relative to nas_path)
exclude_folders = [
    "refz",                  # always excluded
    "roi_data",              # always excluded
    "widefield",             # always excluded
    "habituation"
]

# Regex for rsync %M timestamp
TIMESTAMP_RE = re.compile(r"^\d{4}/\d{2}/\d{2}-\d{2}:\d{2}:\d{2}$")


def log(msg):
    if verbose:
        print("[INFO]", msg)


def list_all_nas_items(base_path):
    """Walk NAS directory and return dict: {relative_path: mtime}"""
    items = {}
    for root, dirs, files in os.walk(base_path):
        for name in dirs + files:
            full_path = os.path.join(root, name)
            rel_path = os.path.relpath(full_path, base_path)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(full_path))
                items[rel_path] = mtime
            except Exception as e:
                log(f"Skipping {rel_path} (mtime error: {e})")
    return items


def get_rsync_candidates(nas_path, server_path):
    """Run rsync dry-run in update-only mode and collect items it would sync + errors"""
    log("Running rsync dry-run with timestamps (update-only)...")

    rsync_cmd = [
        'rsync',
        '-avun',
        '--ignore-existing',
        '--out-format=%M %n',
        nas_path,
        server_path
    ]

    result = subprocess.run(
        rsync_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode not in (0, 23, 24):
        print(f"[ERROR] rsync exited with unexpected code {result.returncode}")
        print("STDERR:\n", result.stderr)
        return set(), set(), set()

    if result.returncode == 23:
        log("rsync exited with code 23: Some files could not be read.")
    elif result.returncode == 24:
        log("rsync exited with code 24: Some files vanished during transfer.")

    candidates = set()
    skipped = []

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            skipped.append(line)
            continue
        mod_str, name = parts
        if not TIMESTAMP_RE.match(mod_str):
            skipped.append(line)
            continue
        if name == ".":  # skip root directory
            continue
        candidates.add(name)

    # Problematic files reported on stderr
    error_lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
    problematic = set()
    for err in error_lines:
        tokens = err.split()
        for t in tokens:
            if "/" in t:
                problematic.add(t)

    if skipped and verbose:
        print("\nSkipped non-timestamp lines (ignored):")
        for s in skipped:
            print(f"[SKIP] {s}")

    # Split into files vs directories
    file_candidates = {c for c in candidates if not c.endswith("/")}
    dir_candidates = {c for c in candidates if c.endswith("/")}

    return file_candidates, dir_candidates, problematic


def is_excluded(path, exclude_folders):
    """Check if a path is inside one of the excluded folders"""
    for ex in exclude_folders:
        if path == ex or path.startswith(ex + "/"):
            return True
    return False


def write_list_to_file(filename, items):
    """Write a list of items to a text file"""
    try:
        with open(filename, "w") as f:
            for item in items:
                f.write(item + "\n")
        print(f"[INFO] Wrote {len(items)} items to {filename}")
    except Exception as e:
        print(f"[ERROR] Could not write to {filename}: {e}")


def progress_bar(current, total, prefix=""):
    bar_length = 40
    percent = float(current) / total if total else 1
    filled_length = int(bar_length * percent)
    bar = "#" * filled_length + "-" * (bar_length - filled_length)
    sys.stdout.write(f"\r{prefix} |{bar}| {percent*100:.1f}%")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")


def main():
    threshold_date = datetime.now() - timedelta(days=age_threshold_days)

    # Step 1: NAS full listing
    log("Walking NAS directory...")
    nas_items = list_all_nas_items(nas_path)

    # Step 2: rsync output
    file_candidates, dir_candidates, problematic = get_rsync_candidates(nas_path, server_path)
    rsync_candidates = file_candidates | dir_candidates

    # Step 3: Derive categories
    old_but_unsynced = [
        rel_path for rel_path, mtime in nas_items.items()
        if mtime <= threshold_date and rel_path in rsync_candidates
        and not is_excluded(rel_path, exclude_folders)
    ]

    safe_old = [
        rel_path for rel_path, mtime in nas_items.items()
        if mtime <= threshold_date
        and rel_path not in rsync_candidates
        and rel_path not in problematic
        and not is_excluded(rel_path, exclude_folders)
    ]

    old_error_files = [
        rel_path for rel_path, mtime in nas_items.items()
        if mtime <= threshold_date and rel_path in problematic
        and not is_excluded(rel_path, exclude_folders)
    ]

    # Summary
    print(f"\nSummary:")
    print(f"  Total NAS items scanned: {len(nas_items)}")
    print(f"  Rsync candidates: {len(rsync_candidates)} "
          f"({len(file_candidates)} files, {len(dir_candidates)} directories)")
    print(f"  Problematic items (all ages): {len(problematic)}")
    print(f"  Old but unsynced (> {age_threshold_days} days): {len(old_but_unsynced)}")
    print(f"  Old error items (> {age_threshold_days} days): {len(old_error_files)}")
    print(f"  Safe old items (> {age_threshold_days} days, synced, no errors): {len(safe_old)}")
    if exclude_folders:
        print(f"  Excluded folders: {exclude_folders}")

    # Ask user about old-but-unsynced
    if old_but_unsynced:
        choice = input(f"\nDo you want to list the {len(old_but_unsynced)} old-but-unsynced items? (y/n): ").strip().lower()
        if choice == 'y':
            print("\nOld but unsynced items:")
            for item in old_but_unsynced:
                print(item)
    else:
        print("\nNo old-but-unsynced items.")

    # Ask user about safe old deletions
    if safe_old:
        if estimate_space:
            print("\n[INFO] Calculating total size of safe old files...")
            total_bytes = 0
            for idx, item in enumerate(safe_old, 1):
                full_path = os.path.join(nas_path, item)
                if os.path.isfile(full_path):
                    try:
                        total_bytes += os.path.getsize(full_path)
                    except Exception:
                        pass
                progress_bar(idx, len(safe_old), prefix="Calculating")
            size_mb = total_bytes / (1024 * 1024)
            size_gb = total_bytes / (1024 * 1024 * 1024)
            print(f"\nServer synced data older than {age_threshold_days} days that can be deleted occupies: {size_mb:.2f} MB ({size_gb:.2f} GB)")
        else:
            print("\n[INFO] Skipping size estimation (disabled by config).")

        choice = input(f"\nDo you want to list the {len(safe_old)} safe old items that could be deleted? (y/n): ").strip().lower()
        if choice == 'y':
            print("\nSafe old items:")
            for item in safe_old:
                print(item)
            write_list_to_file("safe_old_files.txt", safe_old)

        choice = input(f"\nDo you want to DELETE the {len(safe_old)} safe old items (synced + older than {age_threshold_days} days)? (y/n): ").strip().lower()
        if choice == 'y':
            print("\n[INFO] Starting deletion...")
            safe_old_sorted = sorted(safe_old, key=lambda x: x.count("/"), reverse=True)
            for idx, item in enumerate(safe_old_sorted, 1):
                full_path = os.path.join(nas_path, item)
                try:
                    if os.path.isdir(full_path):
                        os.rmdir(full_path)
                    else:
                        os.remove(full_path)
                except Exception as e:
                    print(f"[ERROR] Could not delete {full_path}: {e}")
                progress_bar(idx, len(safe_old_sorted), prefix="Deleting")

            print("\n[INFO] Cleaning up empty directories...")
            for root, dirs, _ in os.walk(nas_path, topdown=False):
                for d in dirs:
                    dir_path = os.path.join(root, d)
                    try:
                        os.rmdir(dir_path)
                    except OSError:
                        pass
    else:
        print("\nNo safe old items to delete.")

    # Ask user about old error files
    if old_error_files:
        choice = input(f"\nDo you want to list the {len(old_error_files)} old error items? (y/n): ").strip().lower()
        if choice == 'y':
            print("\nOld error items:")
            for item in old_error_files:
                print(item)
    else:
        print("\nNo old error items.")

    log("Done.")


if __name__ == '__main__':
    main()
