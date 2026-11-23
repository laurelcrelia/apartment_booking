"""SQLite access shared by the repositories."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from pathlib import Path

MEMORY = ":memory:"


class Database:
    """One SQLite database file with its schema applied.

    A file database opens a fresh connection for every transaction, so it is
    safe to use from many threads and processes at once (WAL mode lets readers
    run while one writer works). ":memory:" keeps a single connection behind a
    lock instead, because every new connection would see an empty database;
    tests use it.
    """

    def __init__(self, path: str | Path, schema: str):
        self.path = str(path)
        self._memory = self.path == MEMORY
        self._lock = threading.RLock() if self._memory else nullcontext()
        if self._memory:
            self._conn = self._connect()
            self._conn.executescript(schema)
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            conn = self._connect()
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(schema)
            finally:
                conn.close()

    def close(self) -> None:
        """Release the in-memory connection; file databases hold no open connection."""
        if self._memory:
            self._conn.close()

    def __del__(self):
        if hasattr(self, "_conn"):
            self.close()

    def _connect(self) -> sqlite3.Connection:
        # isolation_level=None: we issue BEGIN/COMMIT ourselves.
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transaction(self, immediate: bool = False):
        """Run a block in one transaction; it commits on success and rolls back on error.

        Use immediate=True for every transaction that writes. It takes the
        write lock up front, so a check followed by a write (like "no
        overlapping booking, then insert") can't interleave with another
        writer. Without it, a transaction that reads and then writes fails at
        once with "database is locked" if another connection committed in
        between (WAL mode doesn't wait in that case).
        """
        with self._lock:
            conn = self._conn if self._memory else self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                try:
                    yield conn
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
            finally:
                if not self._memory:
                    conn.close()
