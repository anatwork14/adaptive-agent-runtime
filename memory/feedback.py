"""Memory retrieval feedback recorder."""

import sqlite3
from pathlib import Path
from typing import List, Optional
from memory.models import MemoryFeedback


class MemoryFeedbackStore:
    """Stores and retrieves operational utility feedback for delivered memories."""

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self._conn = db_conn
        self._init_table()

    def _init_table(self) -> None:
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_feedback (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id       TEXT NOT NULL,
                    context_id      TEXT NOT NULL,
                    task_id         TEXT NOT NULL,
                    delivered       INTEGER NOT NULL,
                    used            INTEGER,
                    useful          INTEGER,
                    stale           INTEGER,
                    misleading      INTEGER,
                    downstream_gate TEXT,
                    event_id        INTEGER NOT NULL
                );
            """)

    def record_feedback(self, feedback: MemoryFeedback) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO memory_feedback (
                    memory_id, context_id, task_id, delivered,
                    used, useful, stale, misleading, downstream_gate, event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback.memory_id,
                    feedback.context_id,
                    feedback.task_id,
                    feedback.delivered,
                    feedback.used,
                    feedback.useful,
                    feedback.stale,
                    feedback.misleading,
                    feedback.downstream_gate,
                    feedback.event_id,
                ),
            )

    def get_feedback_for_memory(self, memory_id: str) -> List[MemoryFeedback]:
        cursor = self._conn.execute(
            "SELECT * FROM memory_feedback WHERE memory_id = ? ORDER BY id ASC",
            (memory_id,),
        )
        rows = cursor.fetchall()
        return [
            MemoryFeedback(
                id=r["id"],
                memory_id=r["memory_id"],
                context_id=r["context_id"],
                task_id=r["task_id"],
                delivered=r["delivered"],
                used=r["used"],
                useful=r["useful"],
                stale=r["stale"],
                misleading=r["misleading"],
                downstream_gate=r["downstream_gate"],
                event_id=r["event_id"],
            )
            for r in rows
        ]
