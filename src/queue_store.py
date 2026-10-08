"""Durable, locally saved conversion collections.

Each operation owns a SQLite connection and transaction, so UI reads and worker
updates can safely use the same store from different threads. Failed reads or
writes propagate to the caller; a damaged database is never replaced.
"""

from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import sqlite3
import unicodedata
from uuid import uuid4


class QueueBusyError(RuntimeError):
    """Another worker or queue mutation currently owns the queue lock."""


class QueueStore:
    SCHEMA_VERSION = 1
    ITEM_FIELDS = frozenset({
        "status", "error", "output_path", "word_count", "options",
        "checkpoint_path", "receipt_path", "source", "title", "group_name",
    })
    STATUSES = frozenset({"waiting", "processing", "done", "failed"})
    KINDS = frozenset({"file", "url", "text"})

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self, *, write=False):
        connection = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._connection(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if version == self.SCHEMA_VERSION:
                if tables != {"queues", "items", "settings"}:
                    raise sqlite3.DatabaseError("Saved queue database has an invalid schema")
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise sqlite3.DatabaseError("Saved queue database failed its integrity check")
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise sqlite3.DatabaseError("Saved queue database contains invalid references")
                # Never silently recreate missing settings or discard existing work.
                self._active_id(connection)
                return
            if version != 0 or tables:
                raise sqlite3.DatabaseError("Unsupported saved queue database schema")
            connection.execute(
                "CREATE TABLE queues (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
                "name_key TEXT NOT NULL UNIQUE)"
            )
            connection.execute(
                "CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
                "active_id TEXT NOT NULL REFERENCES queues(id))"
            )
            connection.execute("""
                CREATE TABLE items (
                    id TEXT PRIMARY KEY,
                    queue_id TEXT NOT NULL REFERENCES queues(id),
                    kind TEXT NOT NULL CHECK (kind IN ('file', 'url', 'text')),
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    group_name TEXT,
                    status TEXT NOT NULL DEFAULT 'waiting'
                        CHECK (status IN ('waiting', 'processing', 'done', 'failed')),
                    error TEXT,
                    output_path TEXT,
                    word_count INTEGER NOT NULL DEFAULT 0 CHECK (word_count >= 0),
                    options TEXT NOT NULL DEFAULT '{}',
                    checkpoint_path TEXT,
                    receipt_path TEXT,
                    UNIQUE (queue_id, kind, source)
                )
            """)
            inbox = str(uuid4())
            connection.execute("INSERT INTO queues (id, name, name_key) VALUES (?, ?, ?)",
                               (inbox, "Inbox", "inbox"))
            connection.execute("INSERT INTO settings (id, active_id) VALUES (1, ?)", (inbox,))
            connection.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")

    @staticmethod
    def _name(name):
        if not isinstance(name, str):
            raise ValueError("A collection name must be text")
        if any(unicodedata.category(character).startswith("C") for character in name):
            raise ValueError("A collection name cannot contain control characters")
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError("A collection name must contain 1–120 characters")
        return name

    @staticmethod
    def _source(kind, source):
        if not isinstance(source, str) or not source.strip() or "\x00" in source:
            raise ValueError("An item source must be nonempty text without null characters")
        if kind == "file":
            return str(Path(source).expanduser().resolve())
        # URL normalization/validation belongs to intake. Preserve query strings
        # and pasted text byte for byte, so unrelated inputs are never collapsed.
        return source

    @classmethod
    def _fields(cls, fields, *, kind=None):
        unknown = fields.keys() - cls.ITEM_FIELDS
        if unknown:
            raise ValueError(f"Unsupported item fields: {', '.join(sorted(unknown))}")
        values = dict(fields)
        for field, value in values.items():
            if field == "status":
                if not isinstance(value, str) or value not in cls.STATUSES:
                    raise ValueError("Invalid saved item status")
            elif field == "word_count":
                if type(value) is not int or value < 0:
                    raise ValueError("Word count must be a nonnegative integer")
            elif field == "options":
                if not isinstance(value, dict):
                    raise ValueError("Saved conversion options must be a dictionary")
                values[field] = json.dumps(value, ensure_ascii=False, allow_nan=False)
            elif field == "source":
                values[field] = cls._source(kind, value)
            elif field == "title":
                if not isinstance(value, str):
                    raise ValueError("An item title must be text")
            elif value is not None and not isinstance(value, str):
                raise ValueError(f"{field} must be text or None")
        return values

    @staticmethod
    def _require_queue(connection, queue_id):
        if connection.execute("SELECT 1 FROM queues WHERE id = ?", (queue_id,)).fetchone() is None:
            raise KeyError(f"Unknown collection: {queue_id}")

    @staticmethod
    def _active_id(connection):
        row = connection.execute(
            "SELECT active_id FROM settings JOIN queues ON queues.id = settings.active_id WHERE settings.id = 1"
        ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("Saved queue database has no active collection")
        return row[0]

    @staticmethod
    def _item(row):
        item = dict(row)
        item["options"] = json.loads(item["options"])
        if not isinstance(item["options"], dict):
            raise sqlite3.DatabaseError("Saved conversion options are invalid")
        return item

    @property
    def active_id(self):
        with self._connection() as connection:
            return self._active_id(connection)

    def state(self):
        """Read the active collection and counts in one consistent snapshot."""
        with self._connection() as connection:
            active_id = self._active_id(connection)
            queues = [dict(row) for row in connection.execute("SELECT id, name FROM queues ORDER BY rowid")]
            items = [self._item(row) for row in connection.execute(
                "SELECT * FROM items WHERE queue_id = ? ORDER BY rowid", (active_id,)
            )]
        return {
            "active_id": active_id, "queues": queues, "items": items,
            "waiting": sum(item["status"] == "waiting" for item in items),
            "failed": sum(item["status"] == "failed" for item in items),
            "done": sum(item["status"] == "done" for item in items),
            "total": len(items),
        }

    def create_queue(self, name):
        name = self._name(name)
        queue_id = str(uuid4())
        with self.worker_lock(), self._connection(write=True) as connection:
            if connection.execute("SELECT 1 FROM queues WHERE name_key = ?", (name.casefold(),)).fetchone():
                raise ValueError("A collection with that name already exists")
            connection.execute("INSERT INTO queues (id, name, name_key) VALUES (?, ?, ?)",
                               (queue_id, name, name.casefold()))
            connection.execute("UPDATE settings SET active_id = ? WHERE id = 1", (queue_id,))
        return queue_id

    def rename_queue(self, queue_id, name):
        name = self._name(name)
        with self.worker_lock(), self._connection(write=True) as connection:
            self._require_queue(connection, queue_id)
            if connection.execute("SELECT 1 FROM queues WHERE name_key = ? AND id != ?",
                                  (name.casefold(), queue_id)).fetchone():
                raise ValueError("A collection with that name already exists")
            connection.execute("UPDATE queues SET name = ?, name_key = ? WHERE id = ?",
                               (name, name.casefold(), queue_id))

    def select_queue(self, queue_id):
        with self.worker_lock(), self._connection(write=True) as connection:
            self._require_queue(connection, queue_id)
            connection.execute("UPDATE settings SET active_id = ? WHERE id = 1", (queue_id,))

    def add_items(self, queue_id, items):
        prepared = []
        for item in items:
            kind = item.get("kind")
            if not isinstance(kind, str) or kind not in self.KINDS:
                raise ValueError("Invalid saved item kind")
            source = self._source(kind, item.get("source"))
            fields = self._fields({"title": item.get("title", source), "group_name": item.get("group_name")})
            prepared.append((str(uuid4()), queue_id, kind, source, fields["title"], fields["group_name"]))
        added = 0
        with self.worker_lock(), self._connection(write=True) as connection:
            self._require_queue(connection, queue_id)
            for values in prepared:
                cursor = connection.execute(
                    "INSERT INTO items (id, queue_id, kind, source, title, group_name) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (queue_id, kind, source) DO NOTHING", values
                )
                added += cursor.rowcount
        return added

    def items(self, queue_id):
        with self._connection() as connection:
            self._require_queue(connection, queue_id)
            return [self._item(row) for row in connection.execute(
                "SELECT * FROM items WHERE queue_id = ? ORDER BY rowid", (queue_id,)
            )]

    def get_item(self, item_id):
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown saved item: {item_id}")
            return self._item(row)

    def update_item(self, item_id, **fields):
        self.update_items([item_id], **fields)

    def update_items(self, item_ids, **fields):
        """Atomically update worker records; callers own the worker/UI lock.

        Worker updates must remain usable while worker_lock is held. A caller
        changing sources outside a conversion must itself hold worker_lock.
        """
        self._fields(fields)
        with self._connection(write=True) as connection:
            for item_id in item_ids:
                row = connection.execute("SELECT kind FROM items WHERE id = ?", (item_id,)).fetchone()
                if row is None:
                    raise KeyError(f"Unknown saved item: {item_id}")
                values = self._fields(fields, kind=row["kind"])
                if values:
                    assignments = ", ".join(f"{field} = ?" for field in values)
                    connection.execute(f"UPDATE items SET {assignments} WHERE id = ?", (*values.values(), item_id))

    def remove_item(self, item_id):
        with self.worker_lock(), self._connection(write=True) as connection:
            result = connection.execute("DELETE FROM items WHERE id = ?", (item_id,))
            if result.rowcount != 1:
                raise KeyError(f"Unknown saved item: {item_id}")

    def clear_queue(self, queue_id, completed_only=False):
        with self.worker_lock(), self._connection(write=True) as connection:
            self._require_queue(connection, queue_id)
            condition = " AND status = 'done'" if completed_only else ""
            connection.execute("DELETE FROM items WHERE queue_id = ?" + condition, (queue_id,))

    def delete_queue(self, queue_id):
        """Remove a collection atomically, retaining original files and exports."""
        with self.worker_lock(), self._connection(write=True) as connection:
            self._require_queue(connection, queue_id)
            replacement = connection.execute(
                "SELECT id FROM queues WHERE id != ? ORDER BY rowid LIMIT 1", (queue_id,)
            ).fetchone()
            if replacement is None:
                # The single settings row must always reference a real queue.
                # All changes, including a fresh Inbox, commit together.
                connection.execute("DELETE FROM settings WHERE id = 1")
            elif self._active_id(connection) == queue_id:
                connection.execute("UPDATE settings SET active_id = ? WHERE id = 1", (replacement[0],))
            connection.execute("DELETE FROM items WHERE queue_id = ?", (queue_id,))
            connection.execute("DELETE FROM queues WHERE id = ?", (queue_id,))
            if replacement is None:
                inbox = str(uuid4())
                connection.execute("INSERT INTO queues (id, name, name_key) VALUES (?, ?, ?)",
                                   (inbox, "Inbox", "inbox"))
                connection.execute("INSERT INTO settings (id, active_id) VALUES (1, ?)", (inbox,))

    @contextmanager
    def worker_lock(self):
        """Exclude overlapping workers and collection mutations across apps.

        The lock file must never be unlinked: replacing its inode would allow
        another application instance to acquire a different, ineffective lock.
        """
        with self.lock_path.open("a+b") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise QueueBusyError("A conversion worker or queue update is already running") from error
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def recover_interrupted(self):
        """Requeue interrupted items only after proving no worker is running."""
        try:
            with self.worker_lock(), self._connection(write=True) as connection:
                result = connection.execute("UPDATE items SET status = 'waiting' WHERE status = 'processing'")
                return result.rowcount
        except QueueBusyError:
            return 0
