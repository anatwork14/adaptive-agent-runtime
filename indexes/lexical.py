"""Lexical FTS5 search index."""

import sqlite3
from typing import List, Tuple


class LexicalIndex:
    """Rebuildable full-text search index backed by SQLite FTS5."""

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self._conn = db_conn
        self._init_fts()

    def _init_fts(self) -> None:
        with self._conn:
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    memory_id UNINDEXED,
                    title,
                    content,
                    tags
                );
            """)

    def index_document(self, memory_id: str, title: str, content: str, tags: str = "") -> None:
        with self._conn:
            self._conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            self._conn.execute(
                "INSERT INTO memory_fts(memory_id, title, content, tags) VALUES (?, ?, ?, ?)",
                (memory_id, title, content, tags),
            )

    def search(self, query: str, limit: int = 10) -> List[Tuple[str, float]]:
        """Search lexical index and return list of (memory_id, rank)."""
        # Clean query for FTS5 syntax
        safe_query = " OR ".join([f'"{token}"' for token in query.replace('"', '').split() if token])
        if not safe_query:
            return []

        cursor = self._conn.execute(
            """
            SELECT memory_id, rank
            FROM memory_fts
            WHERE memory_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (safe_query, limit),
        )
        return [(row["memory_id"], float(row["rank"])) for row in cursor.fetchall()]

    def clear(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM memory_fts;")
