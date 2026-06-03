from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import os
import getpass
from datetime import datetime
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .config import DataPaths, load_user_map
from .database import DataStore
from .models import DataNode
from .scanner import (
    detect_current_user,
    guess_owner,
    list_available_users,
    scan_scope,
    update_metrics_for_nodes,
)
from .tif_scan import find_tif_candidates


def format_size(value: Optional[int]) -> str:
    if value is None:
        return "—"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}PB"


def format_time(ts: Optional[int]) -> str:
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


class DataManagerApp:
    def __init__(self, paths: Optional[DataPaths] = None):
        self.paths = paths or DataPaths()
        self.root = tk.Tk()
        self.root.title("Data Manager")
        self.root.geometry("1200x700")

        self.datastore = DataStore(self.paths.db_file)
        self.user_map = load_user_map(self.paths)
        self.available_users = list_available_users(self.paths.home_root)
        self.current_user = detect_current_user()
        initial_selection = "all" if self.current_user == "adamranson" else self.current_user
        self.selected_user = tk.StringVar(value=initial_selection)

        self.metric_queue: "queue.Queue[DataNode]" = queue.Queue()
        self.metric_thread: Optional[threading.Thread] = None
        self.metric_stop = threading.Event()

        self.nodes_by_key: Dict[str, DataNode] = {}
        self.processed_all: List[DataNode] = []
        self.kill_window: Optional[tk.Toplevel] = None
        self.usage_var = tk.StringVar(value="")
        self.action_progress = tk.DoubleVar(value=0.0)
        self.action_progress_label = tk.StringVar(value="")
        self.conflict_banner = tk.StringVar(value="")
        self._conflict_choice_cached = None  # (choice, apply_all)
        self.cross_prompt_var = tk.BooleanVar(value=False)
        self.active_tree: Optional[ttk.Treeview] = None
        self.show_unknown_var = tk.BooleanVar(value=False)
        self.progress_window: Optional[tk.Toplevel] = None
        self.show_only_marked_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.refresh_all()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # UI construction
    def _build_ui(self) -> None:
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="User:").pack(side=tk.LEFT)
        user_choices = (
            ["all"] + self.available_users if self.current_user == "adamranson" else self.available_users
        )
        self.user_combo = ttk.Combobox(
            top_frame,
            values=user_choices,
            textvariable=self.selected_user,
            state="readonly" if self.current_user == "adamranson" else "disabled",
            width=30,
        )
        self.user_combo.pack(side=tk.LEFT, padx=5)
        self.user_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_all())

        refresh_btn = ttk.Button(top_frame, text="Refresh", command=self.refresh_all)
        refresh_btn.pack(side=tk.LEFT, padx=5)

        self.scan_btn = ttk.Button(
            top_frame, text="Scan metrics (background)", command=self.start_metric_scan
        )
        self.scan_btn.pack(side=tk.LEFT, padx=5)

        ttk.Button(top_frame, text="View delete list", command=self.open_delete_list).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(top_frame, text="Show all conflicts", command=self.open_all_conflicts).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(top_frame, text="Scan for removable tifs", command=self.scan_tif_candidates).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(top_frame, text="Show orphans", command=self.show_orphans).pack(
            side=tk.LEFT, padx=5
        )
        if self.current_user == "adamranson":
            ttk.Button(top_frame, text="Admin", command=self.open_admin).pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="")
        ttk.Label(top_frame, textvariable=self.status_var).pack(side=tk.LEFT, padx=10)
        ttk.Label(top_frame, textvariable=self.usage_var).pack(side=tk.LEFT, padx=10)
        # Progress is shown in a modal popup when needed.
        ttk.Button(top_frame, text="Conflicts", command=self.open_conflicts).pack(side=tk.RIGHT, padx=5)
        ttk.Button(top_frame, text="Show usage", command=self.show_usage_panel).pack(side=tk.RIGHT, padx=5)

        paths_frame = ttk.Frame(self.root, padding=(10, 0))
        paths_frame.pack(fill=tk.X)
        ttk.Label(
            paths_frame,
            text=f"Raw: {self.paths.raw_root}    |    Processed: <user>/Data/Repository",
        ).pack(side=tk.LEFT)
        ttk.Label(paths_frame, textvariable=self.conflict_banner, foreground="red").pack(side=tk.RIGHT)

        # Trees
        main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_pane.pack(fill=tk.BOTH, expand=True, pady=10, padx=10)

        self.raw_tree = self._build_tree(main_pane, "Raw data")
        self.proc_tree = self._build_tree(main_pane, "Processed data")

        # Details / actions
        detail = ttk.Frame(self.root, padding=10)
        detail.pack(fill=tk.X)
        self.detail_label = ttk.Label(detail, text="Select an animal or experiment…")
        self.detail_label.pack(anchor="w")

        controls = ttk.Frame(detail)
        controls.pack(fill=tk.X, pady=5)

        self.mark_btn = ttk.Button(
            controls, text="Mark for deletion", command=self.toggle_mark
        )
        self.mark_btn.pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(
            controls, text="Ask about raw/processed together", variable=self.cross_prompt_var
        ).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(
            controls,
            text="Show unknown owners (raw)",
            variable=self.show_unknown_var,
            command=self.refresh_all,
        ).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(
            controls,
            text="Show only marked for deletion",
            variable=self.show_only_marked_var,
            command=self.refresh_all,
        ).pack(side=tk.LEFT, padx=5)

        self.owner_value = tk.StringVar()
        ttk.Label(controls, text="Owner override:").pack(side=tk.LEFT, padx=(10, 2))
        self.owner_combo = ttk.Combobox(
            controls, values=self.available_users, textvariable=self.owner_value, width=30
        )
        self.owner_combo.pack(side=tk.LEFT)
        ttk.Button(controls, text="Apply", command=self.apply_owner_override).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(controls, text="Clear override", command=self.clear_owner_override).pack(
            side=tk.LEFT, padx=2
        )

    def _build_tree(self, parent: ttk.PanedWindow, title: str) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        parent.add(frame, weight=1)
        ttk.Label(frame, text=title, font=("Arial", 11, "bold")).pack(anchor="w")
        columns = ("size", "last", "owner", "marked")
        tree = ttk.Treeview(frame, columns=columns, show="tree headings", selectmode="extended")
        tree.heading("#0", text="Item")
        tree.heading("size", text="Size")
        tree.heading("last", text="Last access")
        tree.heading("owner", text="Owner")
        tree.heading("marked", text="Kill?")
        tree.column("#0", width=260)
        tree.column("size", width=120, anchor="e")
        tree.column("last", width=150)
        tree.column("owner", width=140)
        tree.column("marked", width=60, anchor="center")
        tree.pack(fill=tk.BOTH, expand=True)
        tree.bind("<<TreeviewSelect>>", self._on_select)
        tree.bind("<Button-3>", lambda e, t=tree: self._on_right_click(t, e))
        # Derive a strike-through font for marked items
        base_font = tkfont.nametofont("TkDefaultFont").copy()
        base_font.configure(overstrike=True)
        tree.tag_configure("marked_tag", font=base_font)
        return tree

    def _on_right_click(self, tree: ttk.Treeview, event) -> None:
        # Select the item under cursor and trigger mark toggle across selection
        item = tree.identify_row(event.y)
        if item:
            self.active_tree = tree
            current = set(tree.selection())
            if item not in current:
                tree.selection_set(item)
                current = {item}
            nodes = self._selected_nodes(active_only=True)
            if not nodes:
                return
            targets = []
            seen = set()
            for node in nodes:
                if node.exp_id is None:
                    exp_targets = self._visible_exp_targets_for_animal(node)
                    for t in exp_targets:
                        if t.key not in seen:
                            seen.add(t.key)
                            targets.append(t)
                else:
                    if node.key not in seen:
                        seen.add(node.key)
                        targets.append(node)
            if not targets:
                return
            tagged = sum(1 for n in targets if n.marked_for_deletion)
            if tagged == 0:
                mark_state = True
            elif tagged == len(targets):
                mark_state = False
            else:
                mark_state = False if tagged / len(targets) >= 0.5 else True
            self._mark_nodes(targets, mark_state)

    # Actions
    def refresh_all(self) -> None:
        selected_user = self.selected_user.get()
        show_all = selected_user == "all"
        raw_nodes = scan_scope(
            "raw",
            selected_user,
            self.paths,
            self.datastore,
            self.user_map,
            available_users=self.available_users,
        )
        processed_nodes = scan_scope(
            "processed",
            selected_user,
            self.paths,
            self.datastore,
            self.user_map,
            available_users=self.available_users,
        )
        # Cache all processed across users for conflict checks
        self.processed_all = scan_scope(
            "processed",
            "all",
            self.paths,
            self.datastore,
            self.user_map,
            available_users=self.available_users,
        )

        if not show_all:
            def filter_nodes(nodes: List[DataNode]) -> List[DataNode]:
                grouped: Dict[str, List[DataNode]] = {}
                for n in nodes:
                    grouped.setdefault(n.animal_id, []).append(n)
                filtered: List[DataNode] = []
                for items in grouped.values():
                    animal_node = next((i for i in items if i.exp_id is None), None)
                    matching_exps = [
                        i
                        for i in items
                        if i.exp_id
                        and ((i.owner or "") == selected_user or (self.show_unknown_var.get() and not i.owner))
                    ]
                    if matching_exps:
                        if animal_node:
                            filtered.append(animal_node)
                        filtered.extend(matching_exps)
                    elif animal_node and (
                        (animal_node.owner or "") == selected_user
                        or (self.show_unknown_var.get() and not animal_node.owner)
                    ):
                        filtered.append(animal_node)
                if self.show_only_marked_var.get():
                    marked = []
                    grouped_filtered: Dict[str, List[DataNode]] = {}
                    for n in filtered:
                        grouped_filtered.setdefault(n.animal_id, []).append(n)
                    for items in grouped_filtered.values():
                        animal_node = next((i for i in items if i.exp_id is None), None)
                        marked_exps = [i for i in items if i.exp_id and i.marked_for_deletion]
                        if marked_exps:
                            if animal_node:
                                marked.append(animal_node)
                            marked.extend(marked_exps)
                    return marked
                return filtered

            raw_nodes = filter_nodes(raw_nodes)
            processed_nodes = filter_nodes(processed_nodes)

        self.nodes_by_key = {node.key: node for node in [*raw_nodes, *processed_nodes]}

        def marked_only(nodes: List[DataNode]) -> List[DataNode]:
            grouped: Dict[str, List[DataNode]] = {}
            for n in nodes:
                grouped.setdefault(n.animal_id, []).append(n)
            marked = []
            for items in grouped.values():
                animal_node = next((i for i in items if i.exp_id is None), None)
                marked_exps = [i for i in items if i.exp_id and i.marked_for_deletion]
                if marked_exps:
                    if animal_node:
                        marked.append(animal_node)
                    marked.extend(marked_exps)
            return marked

        if show_all and self.show_only_marked_var.get():
            raw_nodes = marked_only(raw_nodes)
            processed_nodes = marked_only(processed_nodes)

        self._populate_tree(self.raw_tree, raw_nodes, scope="raw", show_all=show_all)
        self._populate_tree(self.proc_tree, processed_nodes, scope="processed", show_all=show_all)

        self._update_usage(raw_nodes, processed_nodes, selected_user)

        msg = []
        if not self.user_map:
            msg.append("user map missing")
        if not raw_nodes:
            msg.append("no raw data found")
        if selected_user not in self.available_users and self.available_users:
            msg.append("user not in /home")
        self.status_var.set(" | ".join(msg) if msg else "")
        self._stop_metric_scan()
        self._update_conflict_banner(self._acting_user())

    def _populate_tree(self, tree: ttk.Treeview, nodes: List[DataNode], scope: str, show_all: bool) -> None:
        tree.delete(*tree.get_children())
        parents: Dict[tuple, str] = {}

        # group by animal (and user when showing all to avoid collisions)
        animals: Dict[tuple, List[DataNode]] = {}
        for node in nodes:
            key = (node.user if show_all else None, node.animal_id)
            animals.setdefault(key, []).append(node)

        for (animal_user, animal_id), items in sorted(animals.items(), key=lambda kv: kv[0][1]):
            animal_node = next((n for n in items if n.exp_id is None), None)
            if animal_node is None:
                continue
            label = (
                f"{animal_node.user}/{animal_node.display_name}"
                if show_all and animal_node.user
                else animal_node.display_name
            )
            a_item = tree.insert(
                "",
                tk.END,
                iid=animal_node.key,
                text=label,
                values=(
                    format_size(animal_node.size_bytes),
                    format_time(animal_node.last_access_ts),
                    animal_node.owner or "",
                    "yes" if animal_node.marked_for_deletion else "",
                ),
                tags=(animal_node.key, "marked_tag") if animal_node.marked_for_deletion else (animal_node.key,),
            )
            parents[(animal_user, animal_id)] = a_item
            for exp_node in sorted([n for n in items if n.exp_id], key=lambda n: n.exp_id):
                label = (
                    f"{exp_node.user}/{exp_node.display_name}"
                    if show_all and exp_node.user
                    else exp_node.display_name
                )
                tree.insert(
                    a_item,
                    tk.END,
                    iid=exp_node.key,
                    text=label,
                    values=(
                        format_size(exp_node.size_bytes),
                        format_time(exp_node.last_access_ts),
                        exp_node.owner or animal_node.owner or "",
                        "yes" if exp_node.marked_for_deletion else "",
                    ),
                    tags=(exp_node.key, "marked_tag") if exp_node.marked_for_deletion else (exp_node.key,),
                )

        self._apply_size_colors(tree, nodes)

    def _apply_size_colors(self, tree: ttk.Treeview, nodes: Iterable[DataNode]) -> None:
        sizes = [n.size_bytes for n in nodes if n.size_bytes]
        if not sizes:
            return
        min_size, max_size = min(sizes), max(sizes)
        span = max(max_size - min_size, 1)
        for node in nodes:
            if not node.size_bytes:
                continue
            ratio = (node.size_bytes - min_size) / span
            color = self._gradient_color(ratio)
            tree.tag_configure(node.key, background=color)

    @staticmethod
    def _gradient_color(value: float) -> str:
        # value in [0,1]; blue -> red
        cold = (208, 225, 255)
        hot = (255, 138, 128)
        r = int(cold[0] + (hot[0] - cold[0]) * value)
        g = int(cold[1] + (hot[1] - cold[1]) * value)
        b = int(cold[2] + (hot[2] - cold[2]) * value)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _acting_user(self) -> str:
        sel = self.selected_user.get()
        if self.current_user == "adamranson" and sel != "all":
            return sel
        return self.current_user

    def _on_select(self, event=None) -> None:
        if event is not None:
            self.active_tree = event.widget
        node = self._selected_node()
        if not node:
            self.detail_label.config(text="Select an animal or experiment…")
            return
        info = [
            f"Scope: {node.scope}",
            f"Path: {node.path}",
            f"Owner: {node.owner or 'unknown'}",
            f"Size: {format_size(node.size_bytes)}",
            f"Last access: {format_time(node.last_access_ts)}",
            f"Marked for deletion: {'yes' if node.marked_for_deletion else 'no'}",
        ]
        self.detail_label.config(text=" | ".join(info))
        self.owner_value.set(node.owner or "")
        self.mark_btn.config(
            text="Unmark deletion" if node.marked_for_deletion else "Mark for deletion"
        )

    def _selected_nodes(self, active_only: bool = False) -> List[DataNode]:
        keys = []
        trees = [self.active_tree] if active_only and self.active_tree else [self.raw_tree, self.proc_tree]
        for tree in trees:
            if tree:
                keys.extend(tree.selection())
        nodes: List[DataNode] = []
        for k in keys:
            node = self.nodes_by_key.get(k)
            if node:
                nodes.append(node)
        return nodes

    def _selected_node(self) -> Optional[DataNode]:
        nodes = self._selected_nodes(active_only=True)
        if not nodes:
            nodes = self._selected_nodes()
        return nodes[0] if nodes else None

    def toggle_mark(self) -> None:
        nodes = self._selected_nodes(active_only=True)
        if not nodes:
            return
        # If a single animal is selected, use visible child expIDs to decide toggle
        if len(nodes) == 1 and nodes[0].exp_id is None:
            exp_targets = self._visible_exp_targets_for_animal(nodes[0])
            if exp_targets:
                mark_state = not all(n.marked_for_deletion for n in exp_targets)
                self._mark_nodes(exp_targets, mark_state)
                return
        # otherwise: if any unmarked -> mark, else unmark
        mark_state = not all(n.marked_for_deletion for n in nodes)
        self._mark_nodes(nodes, mark_state)

    def _targets_for_node(self, node: DataNode) -> List[DataNode]:
        if node.exp_id is None:
            return [
                n
                for n in self.nodes_by_key.values()
                if n.scope == node.scope
                and n.animal_id == node.animal_id
                and n.owner == node.owner
                and n.exp_id is not None
            ]
        return [node]

    def _visible_exp_targets_for_animal(self, node: DataNode) -> List[DataNode]:
        if node.exp_id is not None:
            return [node]
        tree = self.raw_tree if node.scope == "raw" else self.proc_tree
        if not tree.exists(node.key):
            return []
        exp_targets = []
        for child in tree.get_children(node.key):
            child_node = self.nodes_by_key.get(child)
            if child_node and child_node.exp_id is not None:
                exp_targets.append(child_node)
        return exp_targets

    def _mark_nodes(self, nodes: List[DataNode], mark_state: bool) -> None:
        # gather targets based on animals -> expIDs
        target_set = []
        seen = set()
        for node in nodes:
            for t in self._targets_for_node(node):
                if t.key not in seen:
                    seen.add(t.key)
                    target_set.append(t)
        if not target_set:
            return

        total = len(target_set)
        self.action_progress.set(0)
        if total > 10:
            self._show_progress_modal("Updating…")
        self._conflict_choice_cached = None
        for idx, n in enumerate(target_set, start=1):
            if not mark_state:
                self.datastore.clear_kill_flag(n.scope, n.animal_id, n.exp_id)
                self.datastore.clear_blocks(n.scope, n.animal_id, n.exp_id)
                n.marked_for_deletion = False
                self._log_action(f"UNMARK {n.scope} {n.animal_id}/{n.exp_id or ''}")
            else:
                actor = self._acting_user()
                blockers = self._blocking_users(n.animal_id, n.exp_id) if n.scope == "raw" else []
                choice_to_apply = None
                if actor in blockers:
                    if self._conflict_choice_cached:
                        choice_to_apply, _ = self._conflict_choice_cached
                    elif self.cross_prompt_var.get():
                        choice_to_apply, apply_all = self._prompt_conflict_choice(n.animal_id, n.exp_id, actor)
                        if apply_all:
                            self._conflict_choice_cached = (choice_to_apply, True)
                    else:
                        choice_to_apply = "keep_processed"
                if choice_to_apply:
                    if choice_to_apply == "cancel":
                        self.action_progress.set((idx / total) * 100)
                        continue
                    if choice_to_apply == "delete_both":
                        for proc in self.processed_all:
                            if (
                                proc.scope == "processed"
                                and proc.user == actor
                                and proc.animal_id == n.animal_id
                                and proc.exp_id == n.exp_id
                            ):
                                self.datastore.set_kill_flag(
                                    proc.scope, proc.animal_id, proc.exp_id, marked_by=actor
                                )
                                self.datastore.set_kill_status(proc.scope, proc.animal_id, proc.exp_id, "pending")
                                proc.marked_for_deletion = True
                                self.nodes_by_key[proc.key] = proc
                                self._refresh_node_in_tree(proc)
                        self.datastore.resolve_block(n.scope, n.animal_id, n.exp_id, actor)
                        blockers = [b for b in blockers if b != actor]
                    elif choice_to_apply == "keep_processed":
                        self.datastore.resolve_block(n.scope, n.animal_id, n.exp_id, actor)
                        blockers = [b for b in blockers if b != actor]

                status = "blocked" if blockers else "pending"
                self.datastore.set_kill_flag(
                    n.scope, n.animal_id, n.exp_id, marked_by=actor
                )
                self.datastore.set_kill_status(n.scope, n.animal_id, n.exp_id, status)
                if n.scope == "processed":
                    # If user also owns processed, clear their block on raw
                    self.datastore.resolve_block("raw", n.animal_id, n.exp_id, actor)
                    remaining = self.datastore.load_blocks().get(("raw", n.animal_id, n.exp_id), [])
                    if not remaining:
                        self.datastore.set_kill_status("raw", n.animal_id, n.exp_id, "pending")
                for user in blockers:
                    self.datastore.upsert_block(
                        n.scope,
                        n.animal_id,
                        n.exp_id,
                        blocking_user=user,
                        requested_by=actor,
                        status="pending",
                    )
                n.marked_for_deletion = True
                self._log_action(f"MARK {n.scope} {n.animal_id}/{n.exp_id or ''}")
            self._refresh_node_in_tree(n)
            self.action_progress.set((idx / total) * 100)
            self.root.update_idletasks()
        if total > 10:
            self._hide_progress_modal()
        self._on_select()
        self._update_conflict_banner(self.selected_user.get())

    def apply_owner_override(self) -> None:
        node = self._selected_node()
        if not node:
            return
        owner = self.owner_value.get().strip() or None
        if owner:
            self.datastore.set_override(node.scope, node.animal_id, node.exp_id, owner)
            node.owner = owner
            node.has_override = True
            if node.exp_id is None:
                # Propagate owner override to all expIDs under this animal
                for child in self.nodes_by_key.values():
                    if (
                        child.scope == node.scope
                        and child.animal_id == node.animal_id
                        and child.exp_id is not None
                    ):
                        self.datastore.set_override(child.scope, child.animal_id, child.exp_id, owner)
                        child.owner = owner
                        child.has_override = True
                        self._refresh_node_in_tree(child)
        self._refresh_node_in_tree(node)
        self._on_select()

    def clear_owner_override(self) -> None:
        node = self._selected_node()
        if not node:
            return
        self.datastore.set_override(node.scope, node.animal_id, node.exp_id, owner=None)
        node.has_override = False
        node.owner = None
        if node.exp_id is None:
            for child in self.nodes_by_key.values():
                if (
                    child.scope == node.scope
                    and child.animal_id == node.animal_id
                    and child.exp_id is not None
                ):
                    self.datastore.set_override(child.scope, child.animal_id, child.exp_id, owner=None)
                    child.has_override = False
                    child.owner = None
                    self._refresh_node_in_tree(child)
        self._refresh_node_in_tree(node)
        self._on_select()

    def _refresh_node_in_tree(self, node: DataNode) -> None:
        tree = self.raw_tree if node.scope == "raw" else self.proc_tree
        if not tree.exists(node.key):
            return
        tree.set(node.key, "size", format_size(node.size_bytes))
        tree.set(node.key, "last", format_time(node.last_access_ts))
        owner_value = node.owner or ""
        if not owner_value and node.exp_id is not None:
            parent_key = f"{node.scope}|{node.user or ''}|{node.animal_id}|"
            parent = self.nodes_by_key.get(parent_key)
            if parent and parent.owner:
                owner_value = parent.owner
        tree.set(node.key, "owner", owner_value)
        tree.set(node.key, "marked", "yes" if node.marked_for_deletion else "")
        # Update color
        tree.tag_configure(node.key, background="")
        scoped_nodes = [n for n in self.nodes_by_key.values() if n.scope == node.scope]
        self._apply_size_colors(tree, scoped_nodes)
        # strike-through toggling
        tags = list(tree.item(node.key, "tags"))
        if node.marked_for_deletion and "marked_tag" not in tags:
            tags.append("marked_tag")
        elif not node.marked_for_deletion and "marked_tag" in tags:
            tags.remove("marked_tag")
        tree.item(node.key, tags=tuple(tags))
        # Display blocked status in marked column if relevant
        key = (node.scope, node.animal_id, node.exp_id)
        blocks = self.datastore.load_blocks().get(key, [])
        if blocks:
            blockers = ", ".join(sorted({row["blocking_user"] for row in blocks}))
            tree.set(node.key, "marked", f"blocked by {blockers}")

    # Metrics scanning
    def start_metric_scan(self) -> None:
        if self.metric_thread and self.metric_thread.is_alive():
            messagebox.showinfo("Metrics", "Scan already running.")
            return
        nodes = list(self.nodes_by_key.values())
        self.metric_stop.clear()
        self.metric_thread = threading.Thread(
            target=self._metric_worker, args=(nodes,), daemon=True
        )
        self.metric_thread.start()
        self.status_var.set("Scanning metrics…")
        self._poll_metric_queue()

    def _metric_worker(self, nodes: Iterable[DataNode]) -> None:
        for node in nodes:
            if self.metric_stop.is_set():
                break
            size_bytes, last_access = 0, None
            if node.path.exists():
                from .scanner import calculate_metrics_for_path

                size_bytes, last_access = calculate_metrics_for_path(node.path)
                self.datastore.upsert_metrics(
                    node.scope, node.animal_id, node.exp_id, size_bytes, last_access
                )
            node.size_bytes = size_bytes
            node.last_access_ts = last_access
            self.metric_queue.put(node)
        self.metric_queue.put(None)  # sentinel

    def _poll_metric_queue(self) -> None:
        try:
            while True:
                node = self.metric_queue.get_nowait()
                if node is None:
                    self.status_var.set("Metrics scan complete")
                    return
                self._refresh_node_in_tree(node)
        except queue.Empty:
            pass
        self.root.after(300, self._poll_metric_queue)

    def _stop_metric_scan(self) -> None:
        if self.metric_thread and self.metric_thread.is_alive():
            self.metric_stop.set()
        self.metric_thread = None

    def _show_progress_modal(self, message: str) -> None:
        if self.progress_window and tk.Toplevel.winfo_exists(self.progress_window):
            self.action_progress_label.set(message)
            return
        win = tk.Toplevel(self.root)
        win.title("Updating")
        win.geometry("300x120")
        win.transient(self.root)
        win.lift()
        win.attributes("-topmost", True)
        self.progress_window = win
        self.action_progress_label.set(message)
        ttk.Label(win, textvariable=self.action_progress_label).pack(pady=10)
        bar = ttk.Progressbar(win, variable=self.action_progress, length=240, mode="determinate")
        bar.pack(pady=5)
        # Ensure window is viewable before grabbing focus
        win.update_idletasks()
        try:
            win.wait_visibility()
            win.grab_set()
        except tk.TclError:
            # If the window isn't viewable yet, skip grab to avoid crash
            pass
        win.attributes("-topmost", False)

    def _hide_progress_modal(self) -> None:
        if self.progress_window and tk.Toplevel.winfo_exists(self.progress_window):
            self.progress_window.grab_release()
            self.progress_window.destroy()
        self.progress_window = None
        # restore focus to any open child window
        for child in self.root.winfo_children():
            if isinstance(child, tk.Toplevel) and child.winfo_exists():
                child.lift()

    def _log_action(self, message: str) -> None:
        username = getpass.getuser()
        log_path = Path(f"/data/common/configs/data_manager/data_gui_{username}.txt")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass

    def _prompt_conflict_choice(self, animal_id: str, exp_id: str, actor: str) -> tuple:
        """
        Prompt the user for how to handle processed conflicts.
        Returns (choice, apply_all) where choice in {cancel, delete_both, keep_processed}.
        """
        choice_var = tk.StringVar(value="cancel")
        apply_all_var = tk.BooleanVar(value=False)

        win = tk.Toplevel(self.root)
        win.title("Processed data conflict")
        ttk.Label(
            win,
            text=f"Processed data found for {animal_id}/{exp_id} (user {actor}). Choose how to proceed:",
            wraplength=380,
        ).pack(padx=10, pady=10)

        options = [
            ("Cancel delete from raw", "cancel"),
            ("Delete raw and processed", "delete_both"),
            ("Delete raw, keep processed", "keep_processed"),
        ]
        for label, val in options:
            ttk.Radiobutton(win, text=label, variable=choice_var, value=val).pack(anchor="w", padx=15, pady=2)

        ttk.Checkbutton(win, text="Do this for all conflicts in this action", variable=apply_all_var).pack(
            anchor="w", padx=15, pady=8
        )
        ttk.Button(win, text="OK", command=win.destroy).pack(pady=8)
        self.root.wait_window(win)
        return choice_var.get(), apply_all_var.get()

    def _blocking_users(self, animal_id: str, exp_id: str) -> List[str]:
        blockers = []
        for n in self.processed_all:
            if n.animal_id == animal_id and n.exp_id == exp_id and n.user:
                blockers.append(n.user)
        return sorted(set(blockers))

    def _update_conflict_banner(self, actor: str) -> None:
        blocks = self.datastore.load_blocks()
        mine = [
            row
            for rows in blocks.values()
            for row in rows
            if row["blocking_user"] == actor and row["status"] == "pending"
        ]
        blocked = []
        kill_rows = self.datastore.load_kill_flags()
        for key, row in kill_rows.items():
            if row["marked_by"] == actor and row["status"] == "blocked":
                blk_rows = blocks.get(key, [])
                if blk_rows:
                    blocked.append((key, blk_rows))
        if mine or blocked:
            self.conflict_banner.set("Conflicts pending. Open Conflicts to resolve.")
        else:
            self.conflict_banner.set("")

    def _update_usage(self, raw_nodes: List[DataNode], proc_nodes: List[DataNode], user: str) -> None:
        if user == "all":
            self.usage_var.set("")
            return

        def total_size(nodes: List[DataNode]) -> Optional[int]:
            total = 0
            any_size = False
            # Sum experiments when present; otherwise fall back to animals
            by_animal: Dict[str, List[DataNode]] = {}
            for n in nodes:
                by_animal.setdefault(n.animal_id, []).append(n)
            for items in by_animal.values():
                exp_nodes = [n for n in items if n.exp_id is not None and n.size_bytes]
                if exp_nodes:
                    any_size = True
                    total += sum(n.size_bytes for n in exp_nodes if n.size_bytes)
                else:
                    animal_nodes = [n for n in items if n.exp_id is None and n.size_bytes]
                    if animal_nodes:
                        any_size = True
                        total += sum(n.size_bytes for n in animal_nodes if n.size_bytes)
            return total if any_size else None

        raw_total = total_size(raw_nodes)
        proc_total = total_size(proc_nodes)
        raw_txt = f"raw {format_size(raw_total)}" if raw_total is not None else "raw size unknown"
        proc_txt = f"processed {format_size(proc_total)}" if proc_total is not None else "processed size unknown"
        self.usage_var.set(f"{user}: {raw_txt} | {proc_txt} (cached)")

    def _collect_usage(self) -> List[tuple]:
        """Collect usage summary per user based on cached metrics."""
        metrics = self.datastore.load_metrics()
        # Build map: (scope, user, animal, exp) -> size
        per_user: Dict[str, Dict[str, int]] = {}

        # Raw: owner inferred from nodes_by_key (current view) is not enough; just use metrics and guess owner from animal/exp?
        # Simpler: rely on current scan cached in nodes_by_key grouped by owner
        grouped: Dict[str, List[DataNode]] = {}
        for n in self.nodes_by_key.values():
            owner = n.owner or (n.user if n.scope == "processed" else None)
            if not owner:
                continue
            grouped.setdefault(owner, []).append(n)

        result: List[tuple] = []
        for user, nodes in grouped.items():
            raw_nodes = [n for n in nodes if n.scope == "raw"]
            proc_nodes = [n for n in nodes if n.scope == "processed"]

            def total(nodes: List[DataNode]) -> Optional[int]:
                # similar logic as _update_usage
                total_size = 0
                any_size = False
                by_animal: Dict[str, List[DataNode]] = {}
                for n in nodes:
                    by_animal.setdefault(n.animal_id, []).append(n)
                for items in by_animal.values():
                    exp_nodes = [n for n in items if n.exp_id is not None and n.size_bytes]
                    if exp_nodes:
                        any_size = True
                        total_size += sum(n.size_bytes for n in exp_nodes if n.size_bytes)
                    else:
                        animal_nodes = [n for n in items if n.exp_id is None and n.size_bytes]
                        if animal_nodes:
                            any_size = True
                            total_size += sum(n.size_bytes for n in animal_nodes if n.size_bytes)
                return total_size if any_size else None

            result.append((user, total(raw_nodes), total(proc_nodes)))
        return result

    def show_usage_panel(self) -> None:
        usage = self._collect_usage()
        win = tk.Toplevel(self.root)
        win.title("Usage")
        win.geometry("500x400")
        columns = ("user", "raw", "processed")
        tree = ttk.Treeview(win, columns=columns, show="headings")
        for col, width in [("user", 140), ("raw", 150), ("processed", 150)]:
            tree.heading(col, text=col.title())
            tree.column(col, width=width, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        if not usage:
            tree.insert("", tk.END, values=("None", "", ""))
        else:
            for user, raw_size, proc_size in sorted(usage, key=lambda x: x[0]):
                tree.insert(
                    "",
                    tk.END,
                    values=(user, format_size(raw_size), format_size(proc_size)),
                )
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=5)

    def open_delete_list(self) -> None:
        if self.kill_window and tk.Toplevel.winfo_exists(self.kill_window):
            self.kill_window.destroy()

        win = tk.Toplevel(self.root)
        self.kill_window = win
        win.title("Delete list")
        win.geometry("800x400")
        controls = ttk.Frame(win)
        controls.pack(fill=tk.X, padx=10, pady=(8, 4))
        ttk.Label(controls, text="Show:").pack(side=tk.LEFT, padx=(0, 6))
        selected_var = tk.StringVar(value=self._acting_user())
        user_combo = ttk.Combobox(controls, values=["all"] + self.available_users, textvariable=selected_var, width=18)
        user_combo.pack(side=tk.LEFT, padx=4)
        user_combo.bind("<<ComboboxSelected>>", lambda _e: render(selected_var.get()))

        total_label = ttk.Label(win, text="Total size (current view): —")
        total_label.pack(anchor="w", padx=10, pady=(0, 4))
        hide_deleted_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            controls, text="Hide deleted", variable=hide_deleted_var, command=lambda: render(selected_var.get())
        ).pack(side=tk.LEFT, padx=6)

        columns = ("scope", "animal", "exp", "status", "note", "marked_at", "marked_by")
        tree = ttk.Treeview(win, columns=columns, show="tree headings")
        tree.heading("#0", text="Owner")
        tree.heading("scope", text="Scope")
        tree.heading("animal", text="Animal")
        tree.heading("exp", text="ExpID / whole animal")
        tree.heading("status", text="Status")
        tree.heading("note", text="Note")
        tree.heading("marked_at", text="Marked at")
        tree.heading("marked_by", text="Marked by")
        for col, width in [
            ("scope", 80),
            ("animal", 120),
            ("exp", 200),
            ("status", 80),
            ("note", 200),
            ("marked_at", 130),
            ("marked_by", 120),
        ]:
            tree.column(col, width=width, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(win, text="File-level deletions").pack(anchor="w", padx=10, pady=(4, 0))
        file_tree = ttk.Treeview(win, columns=("path", "scope", "exp", "marked_by", "age"), show="headings")
        for col, width in [("path", 420), ("scope", 70), ("exp", 180), ("marked_by", 100), ("age", 60)]:
            file_tree.heading(col, text=col.title())
            file_tree.column(col, width=width, anchor="w")
        file_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        def owner_for_row(row) -> str:
            key = (row["scope"], row["animal_id"], row["exp_id"])
            parent_key = (row["scope"], row["animal_id"], None)
            if row["scope"] == "processed":
                return row["marked_by"] or "unknown"
            overrides = self.datastore.load_overrides()
            if key in overrides:
                return overrides[key]
            if row["exp_id"] and parent_key in overrides:
                return overrides[parent_key]
            if row["scope"] == "raw":
                exp_owner = guess_owner(row["animal_id"], row["exp_id"], self.user_map)
                if exp_owner:
                    return exp_owner
                animal_owner = guess_owner(row["animal_id"], None, self.user_map)
                return animal_owner or "unknown"
            return "unknown"

        def owner_for_file(row) -> str:
            if row["scope"] == "processed":
                return row["marked_by"] or "unknown"
            exp_owner = guess_owner(row["animal_id"], row["exp_id"], self.user_map)
            if exp_owner:
                return exp_owner
            animal_owner = guess_owner(row["animal_id"], None, self.user_map)
            return animal_owner or "unknown"

        def render(filter_user: str) -> None:
            tree.delete(*tree.get_children())
            file_tree.delete(*file_tree.get_children())
            metrics = self.datastore.load_metrics()
            kill_rows = self.datastore.load_kill_flags().values()
            file_rows = self.datastore.load_file_deletions().values()

            grouped: Dict[str, List[Dict]] = {}
            total_bytes = 0
            for row in kill_rows:
                if hide_deleted_var.get() and row["status"] == "deleted":
                    continue
                if filter_user != "all" and row["marked_by"] != filter_user:
                    continue
                owner = owner_for_row(row)
                grouped.setdefault(owner, []).append(row)
                mkey = (row["scope"], row["animal_id"], row["exp_id"])
                mrow = metrics.get(mkey)
                if mrow and mrow["size_bytes"]:
                    total_bytes += mrow["size_bytes"]

            if not grouped:
                tree.insert("", tk.END, text="(empty)", values=("", "", "", "", "", ""))
            else:
                for owner, entries in sorted(grouped.items(), key=lambda kv: kv[0]):
                    parent = tree.insert("", tk.END, text=owner, open=True)
                    for row in entries:
                        exp_display = row["exp_id"] or "(entire animal)"
                        marked_at = (
                            time.strftime("%Y-%m-%d %H:%M", time.localtime(row["marked_at"]))
                            if row["marked_at"]
                            else ""
                        )
                        tree.insert(
                            parent,
                            tk.END,
                            text="",
                            values=(
                                row["scope"],
                                row["animal_id"],
                                exp_display,
                                row["status"],
                                row["note"] or "",
                                marked_at,
                                row["marked_by"] or "",
                            ),
                        )

            if not file_rows:
                file_tree.insert("", tk.END, values=("none", "", "", "", ""))
            else:
                for row in file_rows:
                    if hide_deleted_var.get() and row["status"] == "deleted":
                        continue
                    if filter_user != "all" and row["marked_by"] != filter_user:
                        continue
                    owner = owner_for_file(row)
                    age = ""
                    if row["marked_at"]:
                        age = f"{(time.time() - row['marked_at'])/86400:.1f} d"
                    try:
                        total_bytes += Path(row["path"]).stat().st_size
                    except OSError:
                        pass
                    file_tree.insert(
                        "",
                        tk.END,
                        values=(
                            row["path"],
                            row["scope"],
                            f"{row['animal_id']}/{row['exp_id'] or ''}",
                            row["marked_by"],
                            age,
                        ),
                    )

            total_gb = total_bytes / (1024 ** 3) if total_bytes else 0
            total_label.config(text=f"Total size (current view): {total_gb:.2f} GB")

        def set_filter(user: str) -> None:
            selected_var.set(user)
            render(user)

        ttk.Button(controls, text="Current user", command=lambda: set_filter(self._acting_user())).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(controls, text="All users", command=lambda: set_filter("all")).pack(side=tk.LEFT, padx=4)
        ttk.Button(controls, text="Show user", command=lambda: set_filter(selected_var.get())).pack(side=tk.LEFT, padx=4)

        render(self._acting_user())
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))

    def open_conflicts(self) -> None:
        if hasattr(self, "conflict_window") and tk.Toplevel.winfo_exists(self.conflict_window):
            self.conflict_window.lift()
            self._refresh_conflicts_window()
            return
        win = tk.Toplevel(self.root)
        win.title("Conflicts")
        win.geometry("900x500")
        self.conflict_window = win
        self._refresh_conflicts_window()

    def _refresh_conflicts_window(self) -> None:
        # Refresh existing conflict window contents without reopening
        if not hasattr(self, "conflict_window") or not tk.Toplevel.winfo_exists(self.conflict_window):
            return
        win = self.conflict_window
        for child in win.winfo_children():
            child.destroy()
        # Rebuild the window
        blocks = self.datastore.load_blocks()
        kill_flags = self.datastore.load_kill_flags()
        metrics = self.datastore.load_metrics()

        actor = self._acting_user()
        blocking_me = []
        for key, rows in blocks.items():
            for row in rows:
                if row["blocking_user"] == actor and row["status"] == "pending":
                    requester = row["requested_by"] or "unknown"
                    blocking_me.append((key, requester))

        blocked_by = []
        for key, row in kill_flags.items():
            if row["marked_by"] != actor or row["status"] != "blocked":
                continue
            blk_rows = blocks.get(key, [])
            pending_users = [r["blocking_user"] for r in blk_rows if r["status"] == "pending"]
            if pending_users:
                blocked_by.append((key, pending_users))

        panes = ttk.PanedWindow(win, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        def build_list(frame, title, entries, is_blocking: bool, other_label: str):
            ttk.Label(frame, text=title, font=("Arial", 11, "bold")).pack(anchor="w")
            columns = ("animal", "exp", "other", "size", "status")
            tree = ttk.Treeview(frame, columns=columns, show="headings", height=12, selectmode="browse")
            tree.heading("animal", text="Animal")
            tree.heading("exp", text="ExpID")
            tree.heading("other", text=other_label)
            tree.heading("size", text="Size (cached)")
            tree.heading("status", text="Status")
            for col, width in [("animal", 140), ("exp", 220), ("other", 220), ("size", 120), ("status", 120)]:
                tree.column(col, width=width, anchor="w")
            tree.pack(fill=tk.BOTH, expand=True)

            strike_font = tkfont.nametofont("TkDefaultFont").copy()
            strike_font.configure(overstrike=True)
            tree.tag_configure("resolved", font=strike_font)

            for key, others in entries:
                scope, animal_id, exp_id = key
                mrow = metrics.get(key)
                size_txt = format_size(mrow["size_bytes"]) if mrow and mrow["size_bytes"] else "—"
                status_txt = ""
                tag = ""
                if is_blocking:
                    # Check if block still exists
                    exists = any(
                        r["blocking_user"] == actor and r["status"] == "pending"
                        for r in blocks.get(key, [])
                    )
                    if not exists:
                        status_txt = "approved"
                        tag = "resolved"
                    else:
                        status_txt = "blocking"
                else:
                    pending_users = [r["blocking_user"] for r in blocks.get(key, []) if r["status"] == "pending"]
                    if not pending_users:
                        status_txt = "unblocked"
                        tag = "resolved"
                    else:
                        status_txt = "waiting"

                tree.insert(
                    "",
                    tk.END,
                    iid="|".join(key),
                    values=(
                        animal_id,
                        exp_id,
                        ", ".join(sorted(set(others))) if isinstance(others, list) else others,
                        size_txt,
                        status_txt,
                    ),
                    tags=(tag,) if tag else (),
                )

            btn_frame = ttk.Frame(frame)
            btn_frame.pack(fill=tk.X, pady=5)
            if is_blocking:
                ttk.Button(btn_frame, text="Keep (take ownership)", command=lambda: self._conflict_keep(tree)).pack(
                    side=tk.LEFT, padx=5
                )
                ttk.Button(btn_frame, text="Allow deletion", command=lambda: self._conflict_allow(tree)).pack(
                    side=tk.LEFT, padx=5
                )
            else:
                ttk.Button(btn_frame, text="Refresh", command=self._refresh_conflicts_window).pack(side=tk.LEFT, padx=5)
            return tree

        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=1)

        self.conflict_blocking_tree = build_list(
            left,
            "You are blocking deletion (processed data present)",
            blocking_me,
            is_blocking=True,
            other_label="Requested by",
        )
        self.conflict_blocking_tree.bind(
            "<Button-3>",
            lambda e: (self.conflict_blocking_tree.selection_set(self.conflict_blocking_tree.identify_row(e.y)), self._toggle_conflict_blocks()),
        )
        self.conflict_blocked_tree = build_list(
            right,
            "Your deletions are blocked by others",
            blocked_by,
            is_blocking=False,
            other_label="Blocking users",
        )

        ttk.Button(
            win,
            text="Close",
            command=lambda: (win.destroy(), self._update_conflict_banner(self._acting_user())),
        ).pack(pady=5)
        # Update banner based on whether conflicts exist
        if blocking_me or blocked_by:
            self.conflict_banner.set("Conflicts pending. Resolve if possible.")
        else:
            self.conflict_banner.set("")

    def _conflict_keep(self, tree: ttk.Treeview) -> None:
        sel = tree.selection()
        if not sel:
            return
        scope, animal_id, exp_id = sel[0].split("|")
        # Take ownership and clear deletion + block
        actor = self._acting_user()
        self.datastore.set_override(scope, animal_id, exp_id, actor)
        self.datastore.clear_kill_flag(scope, animal_id, exp_id)
        self.datastore.clear_blocks(scope, animal_id, exp_id)
        self.refresh_all()
        # Mark resolved in-place
        current = list(tree.item(sel, "values"))
        if len(current) >= 5:
            current[-1] = "kept"
        tree.item(sel, values=current, tags=("resolved",))
        self._update_conflict_banner(actor)

    def _toggle_conflict_blocks(self) -> None:
        tree = getattr(self, "conflict_blocking_tree", None)
        if not tree:
            return
        sel = tree.selection()
        if not sel:
            return
        actor = self._acting_user()
        # Determine current blocking state from DB
        blocks = self.datastore.load_blocks()
        pending_count = 0
        targets = []
        for iid in sel:
            try:
                scope, animal_id, exp_id = iid.split("|")
            except ValueError:
                continue
            targets.append((scope, animal_id, exp_id, iid))
            blk_rows = blocks.get((scope, animal_id, exp_id), [])
            if any(r["blocking_user"] == actor and r["status"] == "pending" for r in blk_rows):
                pending_count += 1
        if not targets:
            return
        # Apply 50% rule: if >=50% pending, unallow (remove block), else re-block
        if pending_count / len(targets) >= 0.5:
            # allow deletion (remove block)
            for scope, animal_id, exp_id, iid in targets:
                self.datastore.resolve_block(scope, animal_id, exp_id, actor)
                remaining = self.datastore.load_blocks().get((scope, animal_id, exp_id), [])
                if not remaining:
                    self.datastore.set_kill_status(scope, animal_id, exp_id, "pending")
                # update UI row
                values = list(tree.item(iid, "values"))
                if len(values) >= 5:
                    values[-1] = "approved"
                tree.item(iid, values=values, tags=("resolved",))
        else:
            # re-block (unallow)
            for scope, animal_id, exp_id, iid in targets:
                values = list(tree.item(iid, "values"))
                requested_by = values[2] if len(values) >= 3 else None
                self.datastore.upsert_block(
                    scope,
                    animal_id,
                    exp_id,
                    blocking_user=actor,
                    requested_by=requested_by,
                    status="pending",
                )
                self.datastore.set_kill_status(scope, animal_id, exp_id, "blocked")
                values = list(tree.item(iid, "values"))
                if len(values) >= 5:
                    values[-1] = "blocking"
                tree.item(iid, values=values, tags=())
        self._update_conflict_banner(actor)

    def _conflict_allow(self, tree: ttk.Treeview) -> None:
        sel = tree.selection()
        if not sel:
            return
        scope, animal_id, exp_id = sel[0].split("|")
        # Approve deletion: remove our block
        actor = self._acting_user()
        self.datastore.resolve_block(scope, animal_id, exp_id, actor)
        # If no more blocks, update kill status to pending
        remaining = self.datastore.load_blocks().get((scope, animal_id, exp_id), [])
        if not remaining:
            self.datastore.set_kill_status(scope, animal_id, exp_id, "pending")
        self.refresh_all()
        current = list(tree.item(sel, "values"))
        if len(current) >= 5:
            current[-1] = "approved"
        tree.item(sel, values=current, tags=("resolved",))
        self._update_conflict_banner(actor)

    def open_all_conflicts(self) -> None:
        blocks = self.datastore.load_blocks()
        kill_flags = self.datastore.load_kill_flags()
        metrics = self.datastore.load_metrics()

        entries = []
        for key, row in kill_flags.items():
            blk_rows = blocks.get(key, [])
            if not blk_rows:
                continue
            requested_by = row["marked_by"]
            blockers = [r["blocking_user"] for r in blk_rows if r["status"] == "pending"]
            if not blockers:
                continue
            mrow = metrics.get(key)
            size_txt = format_size(mrow["size_bytes"]) if mrow and mrow["size_bytes"] else "—"
            days = ""
            if row["marked_at"]:
                days_elapsed = (time.time() - row["marked_at"]) / 86400
                days = f"{days_elapsed:.1f} d"
            entries.append((key, requested_by, blockers, size_txt, days))

        win = tk.Toplevel(self.root)
        win.title("All conflicts")
        win.geometry("900x500")
        columns = ("scope", "animal", "exp", "requested_by", "blockers", "size", "age")
        tree = ttk.Treeview(win, columns=columns, show="headings")
        for heading, width in [
            ("scope", 80),
            ("animal", 120),
            ("exp", 200),
            ("requested_by", 120),
            ("blockers", 200),
            ("size", 100),
            ("age", 80),
        ]:
            tree.heading(heading, text=heading.replace("_", " ").title())
            tree.column(heading, width=width, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        for key, requested_by, blockers, size_txt, days in entries:
            scope, animal_id, exp_id = key
            tree.insert(
                "",
                tk.END,
                values=(
                    scope,
                    animal_id,
                    exp_id,
                    requested_by,
                    ", ".join(sorted(set(blockers))),
                    size_txt,
                    days,
                ),
            )
        if not entries:
            tree.insert("", tk.END, values=("(none)", "", "", "", "", "", ""))
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=5)

    def open_admin(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Admin")
        win.geometry("400x200")
        ttk.Label(win, text="Admin tools", font=("Arial", 11, "bold")).pack(pady=10)

        def clear_kill():
            if not messagebox.askyesno("Confirm", "Clear all kill list entries?"):
                return
            # Danger: clears all kill flags and blocks
            with self.datastore._connect() as conn:  # reuse connection helper
                conn.execute("DELETE FROM kill_list")
                conn.execute("DELETE FROM deletion_blocks")
                conn.execute("DELETE FROM file_deletions")
                conn.commit()
            messagebox.showinfo("Cleared", "Kill list and deletion blocks cleared.")
            self.refresh_all()

        ttk.Button(win, text="Clear kill list", command=clear_kill).pack(pady=10)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=5)

        ttk.Button(win, text="Show per-user usage", command=self.show_usage_panel).pack(pady=5)

    def scan_tif_candidates(self) -> None:
        selected_user = self.selected_user.get()
        show_all = selected_user == "all"
        processed_nodes = scan_scope(
            "processed",
            selected_user,
            self.paths,
            self.datastore,
            self.user_map,
            available_users=self.available_users,
        )
        if not show_all:
            processed_nodes = [n for n in processed_nodes if (n.owner or "") == selected_user]

        candidates = find_tif_candidates(processed_nodes, self.paths)

        win = tk.Toplevel(self.root)
        win.title("Removable tifs")
        win.geometry("700x400")
        columns = ("animal", "exp", "tifs", "raw_path")
        tree = ttk.Treeview(win, columns=columns, show="headings", selectmode="extended")
        for col, width in [("animal", 120), ("exp", 200), ("tifs", 80), ("raw_path", 260)]:
            tree.heading(col, text=col.title())
            tree.column(col, width=width, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        strike_font = tkfont.nametofont("TkDefaultFont").copy()
        strike_font.configure(overstrike=True)
        tree.tag_configure("marked_tag", font=strike_font)

        existing_files = self.datastore.load_file_deletions().values()
        marked_exps = {(row["animal_id"], row["exp_id"]) for row in existing_files}
        for animal, exp, raw_path, tif_count in candidates:
            tags = ("marked_tag",) if (animal, exp) in marked_exps else ()
            tree.insert("", tk.END, iid=f"{animal}|{exp}", values=(animal, exp, tif_count, str(raw_path)), tags=tags)

        def apply_mark(iids, mark_state: bool):
            actor = self._acting_user()
            for key in iids:
                animal, exp = key.split("|")
                raw_path = self.paths.raw_root / animal / exp
                if mark_state:
                    from .tif_scan import list_tif_files

                    for tif_path in list_tif_files(raw_path):
                        self.datastore.set_file_deletion(
                            str(tif_path), "raw", animal, exp, marked_by=actor, status="pending"
                        )
                    tree.item(key, tags=("marked_tag",))
                    self._log_action(f"MARK_TIFS raw {animal}/{exp}")
                else:
                    self.datastore.clear_file_deletions_for_exp("raw", animal, exp)
                    tree.item(key, tags=tuple(t for t in tree.item(key, "tags") if t != "marked_tag"))
                    self._log_action(f"UNMARK_TIFS raw {animal}/{exp}")

        def mark_selected():
            sel = tree.selection()
            if not sel:
                return
            mark_state = not all("marked_tag" in tree.item(key, "tags") for key in sel)
            apply_mark(sel, mark_state)

        def on_right_click(event):
            iid = tree.identify_row(event.y)
            if iid:
                tree.selection_set(iid)
                mark_state = not ("marked_tag" in tree.item(iid, "tags"))
                apply_mark([iid], mark_state)
                self.refresh_all()
        tree.bind("<Button-3>", on_right_click)

        ttk.Button(win, text="Mark selected for deletion", command=mark_selected).pack(pady=5)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=5)

    def show_orphans(self) -> None:
        selected_user = self.selected_user.get()
        show_all = selected_user == "all"
        processed_nodes = scan_scope(
            "processed",
            selected_user,
            self.paths,
            self.datastore,
            self.user_map,
            available_users=self.available_users,
        )
        if not show_all:
            processed_nodes = [n for n in processed_nodes if (n.owner or "") == selected_user]

        raw_nodes = scan_scope(
            "raw",
            selected_user,
            self.paths,
            self.datastore,
            self.user_map,
            available_users=self.available_users,
        )
        # exclude raw items already marked for deletion
        kill_flags = self.datastore.load_kill_flags()
        raw_keep = [
            n
            for n in raw_nodes
            if not (n.exp_id and (n.scope, n.animal_id, n.exp_id) in kill_flags)
        ]

        raw_exp_set = {(n.animal_id, n.exp_id) for n in raw_keep if n.exp_id}
        raw_animals_set = {animal for animal, _exp in raw_exp_set}

        orphan_animals = []
        orphan_exps = []
        for n in processed_nodes:
            if n.exp_id is None:
                continue
            if (n.animal_id, n.exp_id) not in raw_exp_set:
                orphan_exps.append(n)
        for n in processed_nodes:
            if n.exp_id is None and n.animal_id not in raw_animals_set:
                orphan_animals.append(n)

        win = tk.Toplevel(self.root)
        win.title("Orphans")
        win.geometry("900x500")
        panes = ttk.PanedWindow(win, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left = ttk.Frame(panes)
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=2)

        ttk.Label(left, text="Orphan animals", font=("Arial", 11, "bold")).pack(anchor="w")
        animal_tree = ttk.Treeview(left, columns=("user", "animal", "path"), show="headings", selectmode="extended")
        animal_tree.heading("user", text="User")
        animal_tree.heading("animal", text="Animal")
        animal_tree.heading("path", text="Path")
        for col, width in [("user", 120), ("animal", 120), ("path", 260)]:
            animal_tree.column(col, width=width, anchor="w")
        animal_tree.pack(fill=tk.BOTH, expand=True)
        strike_font = tkfont.nametofont("TkDefaultFont").copy()
        strike_font.configure(overstrike=True)
        animal_tree.tag_configure("marked_tag", font=strike_font)

        ttk.Label(right, text="Orphan expIDs", font=("Arial", 11, "bold")).pack(anchor="w")
        exp_tree = ttk.Treeview(right, columns=("user", "exp", "path"), show="tree headings", selectmode="extended")
        exp_tree.heading("#0", text="Animal")
        exp_tree.heading("user", text="User")
        exp_tree.heading("exp", text="ExpID")
        exp_tree.heading("path", text="Path")
        exp_tree.column("#0", width=140)
        exp_tree.column("user", width=120, anchor="w")
        exp_tree.column("exp", width=200, anchor="w")
        exp_tree.column("path", width=260, anchor="w")
        exp_tree.pack(fill=tk.BOTH, expand=True)
        exp_tree.tag_configure("marked_tag", font=strike_font)

        # fill animals
        for n in orphan_animals:
            tags = ("marked_tag",) if n.marked_for_deletion else ()
            animal_tree.insert(
                "",
                tk.END,
                iid=n.key,
                values=(n.user or "", n.animal_id, str(n.path)),
                tags=tags,
            )

        # fill exp tree grouped by animal (and user when showing all)
        exp_groups: Dict[tuple, List[DataNode]] = {}
        for n in orphan_exps:
            key = (n.user if show_all else None, n.animal_id)
            exp_groups.setdefault(key, []).append(n)
        for (user, animal), items in sorted(exp_groups.items(), key=lambda kv: kv[0][1]):
            label = f"{user}/{animal}" if show_all and user else animal
            parent = exp_tree.insert("", tk.END, text=label, values=("", "", ""), open=True)
            for n in sorted(items, key=lambda x: x.exp_id or ""):
                tags = ("marked_tag",) if n.marked_for_deletion else ()
                exp_tree.insert(
                    parent,
                    tk.END,
                    iid=n.key,
                    text="",
                    values=(n.user or "", n.exp_id, str(n.path)),
                    tags=tags,
                )

        def selection_nodes(tree: ttk.Treeview) -> List[DataNode]:
            nodes: List[DataNode] = []
            for iid in tree.selection():
                node = self.nodes_by_key.get(iid)
                if node:
                    nodes.append(node)
                else:
                    # Parent row in exp tree: include its children
                    for child in tree.get_children(iid):
                        child_node = self.nodes_by_key.get(child)
                        if child_node:
                            nodes.append(child_node)
            return nodes

        def expand_targets(tree: ttk.Treeview, nodes: List[DataNode]) -> List[DataNode]:
            targets = []
            seen = set()
            for node in nodes:
                if node.exp_id is None:
                    # collect all expIDs under this animal from processed nodes
                    for child in self.nodes_by_key.values():
                        if (
                            child.scope == "processed"
                            and child.animal_id == node.animal_id
                            and child.exp_id is not None
                            and (show_all or child.owner == selected_user)
                        ):
                            if child.key not in seen:
                                seen.add(child.key)
                                targets.append(child)
                else:
                    if node.key not in seen:
                        seen.add(node.key)
                        targets.append(node)
            return targets

        def toggle_selected(tree: ttk.Treeview):
            nodes = selection_nodes(tree)
            if not nodes:
                return
            targets = expand_targets(tree, nodes)
            if not targets:
                return
            tagged = sum(1 for n in targets if n.marked_for_deletion)
            if tagged == 0:
                mark_state = True
            elif tagged == len(targets):
                mark_state = False
            else:
                mark_state = False if tagged / len(targets) >= 0.5 else True
            self._mark_nodes(targets, mark_state)
            for n in targets:
                if tree.exists(n.key):
                    tags = list(tree.item(n.key, "tags"))
                    if n.marked_for_deletion and "marked_tag" not in tags:
                        tags.append("marked_tag")
                    elif not n.marked_for_deletion and "marked_tag" in tags:
                        tags.remove("marked_tag")
                    tree.item(n.key, tags=tuple(tags))
            # Update animal rows too
            for node in nodes:
                if node.exp_id is None and tree.exists(node.key):
                    tags = list(tree.item(node.key, "tags"))
                    if mark_state and "marked_tag" not in tags:
                        tags.append("marked_tag")
                    elif not mark_state and "marked_tag" in tags:
                        tags.remove("marked_tag")
                    tree.item(node.key, tags=tuple(tags))
            # Refresh exp tree tags when animal orphans are toggled
            if tree is animal_tree:
                for child in exp_tree.get_children(""):
                    for exp_iid in exp_tree.get_children(child):
                        exp_node = self.nodes_by_key.get(exp_iid)
                        if exp_node:
                            tags = list(exp_tree.item(exp_iid, "tags"))
                            if exp_node.marked_for_deletion and "marked_tag" not in tags:
                                tags.append("marked_tag")
                            elif not exp_node.marked_for_deletion and "marked_tag" in tags:
                                tags.remove("marked_tag")
                            exp_tree.item(exp_iid, tags=tuple(tags))

        animal_tree.bind(
            "<Button-3>",
            lambda e: (animal_tree.selection_set(animal_tree.identify_row(e.y)), toggle_selected(animal_tree)),
        )
        exp_tree.bind(
            "<Button-3>",
            lambda e: (exp_tree.selection_set(exp_tree.identify_row(e.y)), toggle_selected(exp_tree)),
        )

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=5)
    def _on_close(self) -> None:
        self._stop_metric_scan()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
