-- Authoritative Event Store Schema
-- SQLite WAL mode append-only log

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

CREATE INDEX IF NOT EXISTS idx_events_project_id
ON events(project_id, id);

CREATE INDEX IF NOT EXISTS idx_events_task_id
ON events(task_id, id);

CREATE INDEX IF NOT EXISTS idx_events_kind
ON events(kind, id);
