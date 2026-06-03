#!/usr/bin/env python
"""
Standalone scanner for data_manager.

Discovers raw and processed data, logs what it finds, and computes cached metrics
into the shared SQLite DB. Supports immediate run and a nightly 1am schedule
unless interrupted.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from threading import Event, Thread

from data_manager.config import DataPaths, load_user_map
from data_manager.database import DataStore
from data_manager.scanner import list_available_users, scan_scope, calculate_metrics_for_path


def log_nodes(nodes, label: str) -> None:
    print(f"[{label}] {len(nodes)} nodes", flush=True)
    for n in nodes:
        name = f"{n.animal_id}/{n.exp_id}" if n.exp_id else n.animal_id
        owner = n.owner or n.user or "unknown"
        print(f"  - {label} {owner}: {name} ({n.path})", flush=True)
    print("", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verbose scanner for data_manager.")
    parser.add_argument("--watch", action="store_true", help="Run now and then nightly at 1am.")
    args = parser.parse_args()

    paths = DataPaths()
    datastore = DataStore(paths.db_file)
    user_map = load_user_map(paths)
    all_users = list_available_users(paths.home_root)

    stop_event = Event()

    def run_once():
        start = time.time()
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Scanning raw...")
        raw_nodes = scan_scope("raw", "all", paths, datastore, user_map, available_users=all_users)
        log_nodes(raw_nodes, "raw")

        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Scanning processed...")
        proc_nodes = scan_scope("processed", "all", paths, datastore, user_map, available_users=all_users)
        log_nodes(proc_nodes, "processed")

        print("Computing metrics (this may take a while)...")
        all_nodes = raw_nodes + proc_nodes
        total = len(all_nodes)
        for idx, node in enumerate(all_nodes, start=1):
            size_bytes, last_access = 0, None
            if node.path.exists():
                size_bytes, last_access = calculate_metrics_for_path(node.path)
                datastore.upsert_metrics(
                    node.scope, node.animal_id, node.exp_id, size_bytes, last_access
                )
            node.size_bytes = size_bytes
            node.last_access_ts = last_access
            percent = (idx / total) * 100 if total else 100
            sys.stdout.write(f"\rMetrics: {idx}/{total} ({percent:.1f}%)")
            sys.stdout.flush()
        print()
        duration = time.time() - start
        raw_total = sum(n.size_bytes or 0 for n in raw_nodes)
        proc_total = sum(n.size_bytes or 0 for n in proc_nodes)
        print(
            f"Done in {duration/60:.1f} min. Raw total: {raw_total/1e12:.3f} TB, "
            f"Processed total: {proc_total/1e12:.3f} TB"
        )

    def scheduler():
        while not stop_event.is_set():
            now = datetime.now()
            target = now.replace(hour=1, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            print(f"Next run scheduled at {target}. Waiting {wait_seconds/3600:.2f} hours. Press Enter to run now.")
            # Wait with interruption on Enter
            interrupted = wait_with_enter(wait_seconds, stop_event)
            if stop_event.is_set():
                break
            if interrupted:
                print("Manual run requested.")
            run_once()

    def wait_with_enter(timeout: float, stop_evt: Event) -> bool:
        """
        Wait for timeout or Enter key. Returns True if Enter pressed.
        """
        # crude but effective: a thread to wait for input
        enter_evt = Event()

        def input_thread():
            try:
                input()
                enter_evt.set()
            except EOFError:
                pass

        t = Thread(target=input_thread, daemon=True)
        t.start()
        start = time.time()
        while time.time() - start < timeout:
            if stop_evt.is_set():
                return False
            if enter_evt.is_set():
                return True
            time.sleep(0.5)
        return False

    run_once()
    if args.watch:
        try:
            scheduler()
        except KeyboardInterrupt:
            print("Stopping scheduler.")
            stop_event.set()


if __name__ == "__main__":
    main()
