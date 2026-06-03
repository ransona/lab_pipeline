from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from .config import ensure_parent


ScopeKey = Tuple[str, str, Optional[str]]


class DataStore:
    """
    Thin SQLite wrapper. Uses WAL mode so multiple users can write concurrently.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        ensure_parent(self.db_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ownership_overrides (
                    scope TEXT NOT NULL,
                    animal_id TEXT NOT NULL,
                    exp_id TEXT,
                    owner TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (scope, animal_id, exp_id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kill_list (
                    scope TEXT NOT NULL,
                    animal_id TEXT NOT NULL,
                    exp_id TEXT NOT NULL,
                    marked_by TEXT NOT NULL,
                    marked_at INTEGER NOT NULL,
                    note TEXT,
                    status TEXT DEFAULT 'pending',
                    PRIMARY KEY (scope, animal_id, exp_id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deletion_blocks (
                    scope TEXT NOT NULL,
                    animal_id TEXT NOT NULL,
                    exp_id TEXT NOT NULL,
                    blocking_user TEXT NOT NULL,
                    requested_by TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (scope, animal_id, exp_id, blocking_user)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    scope TEXT NOT NULL,
                    animal_id TEXT NOT NULL,
                    exp_id TEXT,
                    size_bytes INTEGER,
                    last_access_ts INTEGER,
                    scanned_at INTEGER NOT NULL,
                    PRIMARY KEY (scope, animal_id, exp_id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_deletions (
                    path TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    animal_id TEXT NOT NULL,
                    exp_id TEXT,
                    marked_by TEXT NOT NULL,
                    marked_at INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending'
                );
                """
            )
            conn.commit()

    # Ownership overrides
    def load_overrides(self) -> Dict[ScopeKey, str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT scope, animal_id, exp_id, owner FROM ownership_overrides"
            ).fetchall()
            return {(row["scope"], row["animal_id"], row["exp_id"]): row["owner"] for row in rows}

    def set_override(
        self, scope: str, animal_id: str, exp_id: Optional[str], owner: Optional[str]
    ) -> None:
        with self._connect() as conn:
            if owner:
                conn.execute(
                    """
                    INSERT INTO ownership_overrides(scope, animal_id, exp_id, owner, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(scope, animal_id, exp_id)
                    DO UPDATE SET owner=excluded.owner, updated_at=excluded.updated_at
                    """,
                    (scope, animal_id, exp_id, owner, int(time.time())),
                )
            else:
                conn.execute(
                    "DELETE FROM ownership_overrides WHERE scope=? AND animal_id=? AND exp_id IS ?",
                    (scope, animal_id, exp_id),
                )
            conn.commit()

    # Kill list
    def load_kill_flags(self) -> Dict[ScopeKey, sqlite3.Row]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT scope, animal_id, exp_id, marked_by, marked_at, note, status FROM kill_list"
            ).fetchall()
            return {
                (row["scope"], row["animal_id"], row["exp_id"]): row for row in rows
            }

    def set_kill_flag(
        self,
        scope: str,
        animal_id: str,
        exp_id: Optional[str],
        marked_by: str,
        note: Optional[str] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kill_list(scope, animal_id, exp_id, marked_by, marked_at, note, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                ON CONFLICT(scope, animal_id, exp_id)
                DO UPDATE SET marked_by=excluded.marked_by,
                              marked_at=excluded.marked_at,
                              note=excluded.note,
                              status='pending'
                """,
                (scope, animal_id, exp_id, marked_by, int(time.time()), note),
            )
            conn.commit()

    def set_kill_status(self, scope: str, animal_id: str, exp_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE kill_list SET status=? WHERE scope=? AND animal_id=? AND exp_id=?",
                (status, scope, animal_id, exp_id),
            )
            conn.commit()

    def clear_kill_flag(self, scope: str, animal_id: str, exp_id: Optional[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM kill_list WHERE scope=? AND animal_id=? AND exp_id IS ?",
                (scope, animal_id, exp_id),
            )
            conn.commit()

    # Metrics
    def load_metrics(self) -> Dict[ScopeKey, sqlite3.Row]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT scope, animal_id, exp_id, size_bytes, last_access_ts, scanned_at FROM metrics"
            ).fetchall()
            return {
                (row["scope"], row["animal_id"], row["exp_id"]): row for row in rows
            }

    def upsert_metrics(
        self,
        scope: str,
        animal_id: str,
        exp_id: Optional[str],
        size_bytes: Optional[int],
        last_access_ts: Optional[int],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO metrics(scope, animal_id, exp_id, size_bytes, last_access_ts, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, animal_id, exp_id)
                DO UPDATE SET size_bytes=excluded.size_bytes,
                              last_access_ts=excluded.last_access_ts,
                              scanned_at=excluded.scanned_at
                """,
                (scope, animal_id, exp_id, size_bytes, last_access_ts, int(time.time())),
            )
            conn.commit()

    # File-level deletions (e.g., tifs)
    def set_file_deletion(
        self,
        path: str,
        scope: str,
        animal_id: str,
        exp_id: Optional[str],
        marked_by: str,
        status: str = "pending",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO file_deletions(path, scope, animal_id, exp_id, marked_by, marked_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path)
                DO UPDATE SET status=excluded.status,
                              marked_by=excluded.marked_by,
                              marked_at=excluded.marked_at
                """,
                (path, scope, animal_id, exp_id, marked_by, int(time.time()), status),
            )
            conn.commit()

    def load_file_deletions(self) -> Dict[str, sqlite3.Row]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT path, scope, animal_id, exp_id, marked_by, marked_at, status FROM file_deletions"
            ).fetchall()
            return {row["path"]: row for row in rows}

    def clear_file_deletion(self, path: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM file_deletions WHERE path=?", (path,))
            conn.commit()

    def clear_file_deletions_for_exp(self, scope: str, animal_id: str, exp_id: Optional[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM file_deletions WHERE scope=? AND animal_id=? AND exp_id IS ?",
                (scope, animal_id, exp_id),
            )
            conn.commit()

    # Deletion blocks (processed data conflicts)
    def upsert_block(
        self,
        scope: str,
        animal_id: str,
        exp_id: str,
        blocking_user: str,
        requested_by: Optional[str],
        status: str = "pending",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO deletion_blocks(scope, animal_id, exp_id, blocking_user, requested_by, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope, animal_id, exp_id, blocking_user)
                DO UPDATE SET requested_by=excluded.requested_by,
                              status=excluded.status,
                              updated_at=excluded.updated_at
                """,
                (scope, animal_id, exp_id, blocking_user, requested_by, status, int(time.time())),
            )
            conn.commit()

    def load_blocks(self) -> Dict[ScopeKey, List[sqlite3.Row]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT scope, animal_id, exp_id, blocking_user, requested_by, status, updated_at FROM deletion_blocks"
            ).fetchall()
            grouped: Dict[ScopeKey, List[sqlite3.Row]] = {}
            for row in rows:
                key = (row["scope"], row["animal_id"], row["exp_id"])
                grouped.setdefault(key, []).append(row)
            return grouped

    def clear_blocks(self, scope: str, animal_id: str, exp_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM deletion_blocks WHERE scope=? AND animal_id=? AND exp_id=?",
                (scope, animal_id, exp_id),
            )
            conn.commit()

    def resolve_block(self, scope: str, animal_id: str, exp_id: str, blocking_user: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM deletion_blocks WHERE scope=? AND animal_id=? AND exp_id=? AND blocking_user=?",
                (scope, animal_id, exp_id, blocking_user),
            )
            conn.commit()
