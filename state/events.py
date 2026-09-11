"""SQLite-backed append-only Authoritative Event Store."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from state.hashing import canonical_json, compute_content_hash
from state.models import Event


class EventStore:
    """Append-only authoritative event store backed by SQLite in WAL mode."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
            schema_path = Path(__file__).parent / "schema.sql"
            if schema_path.exists():
                schema_sql = schema_path.read_text(encoding="utf-8")
                self._conn.executescript(schema_sql)
            else:
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts              TEXT NOT NULL,
                        actor           TEXT NOT NULL,
                        kind            TEXT NOT NULL,
                        project_id      TEXT NOT NULL,
                        task_id         TEXT,
                        payload         TEXT NOT NULL,
                        causation_id    INTEGER,
                        correlation_id  TEXT,
                        fencing_token   INTEGER,
                        content_hash    TEXT NOT NULL
                    );
                """)
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_project_id ON events(project_id, id);")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id, id);")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, id);")

    def append(
        self,
        *,
        actor: str,
        kind: str,
        project_id: str,
        payload: Dict[str, Any],
        task_id: Optional[str] = None,
        causation_id: Optional[int] = None,
        correlation_id: Optional[str] = None,
        fencing_token: Optional[int] = None,
    ) -> int:
        """Append an authoritative event to the store and return its monotonic event ID."""
        if not actor or not kind or not project_id:
            raise ValueError("actor, kind, and project_id are required")

        content_hash = compute_content_hash(
            actor=actor,
            kind=kind,
            project_id=project_id,
            payload=payload,
            task_id=task_id,
            causation_id=causation_id,
            correlation_id=correlation_id,
            fencing_token=fencing_token,
        )

        payload_json = canonical_json(payload)
        now_ts = datetime.now(timezone.utc).isoformat()

        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO events (
                    ts, actor, kind, project_id, task_id,
                    payload, causation_id, correlation_id,
                    fencing_token, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_ts,
                    actor,
                    kind,
                    project_id,
                    task_id,
                    payload_json,
                    causation_id,
                    correlation_id,
                    fencing_token,
                    content_hash,
                ),
            )
            event_id = cursor.lastrowid
            if event_id is None:
                raise RuntimeError("Failed to retrieve inserted event ID")
            return event_id

    def read_event(self, event_id: int) -> Optional[Event]:
        """Read a single event by ID."""
        cursor = self._conn.execute(
            "SELECT * FROM events WHERE id = ?",
            (event_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_event(row)

    def read_after(
        self,
        event_id: int,
        *,
        project_id: str,
        limit: Optional[int] = None,
    ) -> List[Event]:
        """Read events occurring strictly after event_id for a specific project."""
        query = "SELECT * FROM events WHERE project_id = ? AND id > ? ORDER BY id ASC"
        params: List[Any] = [project_id, event_id]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        cursor = self._conn.execute(query, params)
        return [self._row_to_event(row) for row in cursor.fetchall()]

    def read_range(
        self,
        start_id: int,
        end_id: int,
        *,
        project_id: str,
    ) -> List[Event]:
        """Read events in inclusive range [start_id, end_id] for a project."""
        cursor = self._conn.execute(
            "SELECT * FROM events WHERE project_id = ? AND id >= ? AND id <= ? ORDER BY id ASC",
            (project_id, start_id, end_id),
        )
        return [self._row_to_event(row) for row in cursor.fetchall()]

    def read_all(self, *, project_id: Optional[str] = None) -> List[Event]:
        """Read all events, optionally filtered by project_id."""
        if project_id:
            cursor = self._conn.execute(
                "SELECT * FROM events WHERE project_id = ? ORDER BY id ASC",
                (project_id,),
            )
        else:
            cursor = self._conn.execute("SELECT * FROM events ORDER BY id ASC")
        return [self._row_to_event(row) for row in cursor.fetchall()]

    def current_version(self, project_id: str) -> int:
        """Return the highest event ID committed for the given project, or 0 if none exist."""
        cursor = self._conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM events WHERE project_id = ?",
            (project_id,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        """Close SQLite connection."""
        self._conn.close()

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        payload_data = json.loads(row["payload"])
        return Event(
            id=row["id"],
            ts=row["ts"],
            actor=row["actor"],
            kind=row["kind"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            payload=payload_data,
            causation_id=row["causation_id"],
            correlation_id=row["correlation_id"],
            fencing_token=row["fencing_token"],
            content_hash=row["content_hash"],
        )
