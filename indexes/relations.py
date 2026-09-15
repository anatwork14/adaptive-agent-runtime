"""Memory relation graph index."""

import sqlite3
from typing import List, Optional

from memory.models import MemoryRelation, RelationType


class RelationIndex:
    """Manages memory relationships (supports, depends_on, supersedes, contradicts)."""

    def __init__(self, db_conn: sqlite3.Connection) -> None:
        self._conn = db_conn
        self._init_table()

    def _init_table(self) -> None:
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_relations (
                    src_memory_id TEXT NOT NULL,
                    relation      TEXT NOT NULL,
                    dst_memory_id TEXT NOT NULL,
                    created_event INTEGER NOT NULL,
                    PRIMARY KEY(src_memory_id, relation, dst_memory_id)
                );
            """)

    def add_relation(self, relation: MemoryRelation) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO memory_relations (
                    src_memory_id, relation, dst_memory_id, created_event
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    relation.src_memory_id,
                    relation.relation.value if hasattr(relation.relation, "value") else str(relation.relation),
                    relation.dst_memory_id,
                    relation.created_event,
                ),
            )

    def get_related(self, memory_id: str, relation_type: Optional[RelationType] = None) -> List[str]:
        if relation_type:
            rel_val = relation_type.value if hasattr(relation_type, "value") else str(relation_type)
            cursor = self._conn.execute(
                "SELECT dst_memory_id FROM memory_relations WHERE src_memory_id = ? AND relation = ?",
                (memory_id, rel_val),
            )
        else:
            cursor = self._conn.execute(
                "SELECT dst_memory_id FROM memory_relations WHERE src_memory_id = ?",
                (memory_id,),
            )
        return [row[0] for row in cursor.fetchall()]

    def clear(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM memory_relations;")
