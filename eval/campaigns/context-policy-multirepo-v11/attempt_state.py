"""Append-only, atomic task state for context-policy-multirepo-v11.

This module is deliberately provider-neutral. It is the durable boundary
between an execution attempt and campaign scoring: filesystem artifacts alone
cannot advance a logical task.
"""

from __future__ import annotations

import json
import sqlite3
import time
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


class TaskState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PROVIDER_CENSORED = "PROVIDER_CENSORED"
    TIMEOUT = "TIMEOUT"
    MODEL_FAILED = "MODEL_FAILED"
    INFRASTRUCTURE_FAILED = "INFRASTRUCTURE_FAILED"


class TaskIdentity:
    def __init__(self, repository: str, repetition: int, baseline: str, task: str) -> None:
        self.repository = repository
        self.repetition = repetition
        self.baseline = baseline
        self.task = task

    @property
    def key(self) -> str:
        return f"{self.repository}/r{self.repetition}/{self.baseline}/{self.task}"


TERMINAL_STATES = {
    TaskState.COMPLETED,
    TaskState.PROVIDER_CENSORED,
    TaskState.TIMEOUT,
    TaskState.MODEL_FAILED,
    TaskState.INFRASTRUCTURE_FAILED,
}
PROVIDER_REASON_CLASSES = {
    "USAGE_LIMIT",
    "QUOTA_EXCEEDED",
    "RATE_LIMIT",
    "PROVIDER_5XX",
    "SERVICE_UNAVAILABLE",
    "AUTHENTICATION_SERVICE",
    "SESSION_SERVICE",
    "TRANSPORT_BEFORE_OUTPUT",
}


class AttemptStateStore:
    """SQLite ledger with transactional transitions and immutable instances."""

    def __init__(self, path: str | Path, *, max_provider_censor_retries: int = 1) -> None:
        if max_provider_censor_retries < 0:
            raise ValueError("max_provider_censor_retries must be non-negative")
        self.path = Path(path)
        self.max_provider_censor_retries = max_provider_censor_retries
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS logical_tasks (
                logical_key TEXT PRIMARY KEY,
                repository TEXT NOT NULL,
                repetition INTEGER NOT NULL,
                baseline TEXT NOT NULL,
                task TEXT NOT NULL,
                state TEXT NOT NULL,
                scientific_status TEXT NOT NULL,
                latest_instance_id TEXT,
                task_metric_json TEXT,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS execution_instances (
                instance_id TEXT PRIMARY KEY,
                logical_key TEXT NOT NULL REFERENCES logical_tasks(logical_key),
                ordinal INTEGER NOT NULL,
                state TEXT NOT NULL,
                execution_status TEXT NOT NULL,
                scientific_status TEXT NOT NULL,
                provider_start REAL,
                provider_end REAL,
                model TEXT,
                config_identity TEXT,
                provider_status TEXT,
                provider_reason_json TEXT,
                token_usage_json TEXT,
                agent_terminal_state TEXT,
                patch_commit TEXT,
                visible_eval_json TEXT,
                hidden_eval_json TEXT,
                score_components_json TEXT,
                artifact_hashes_json TEXT,
                safe_to_retry INTEGER,
                created_at REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS execution_identity_ordinal
                ON execution_instances(logical_key, ordinal);
            """
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "AttemptStateStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _json(value: Any) -> str | None:
        return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _identity(identity: Any) -> tuple[Any, ...]:
        return (identity.key, identity.repository, identity.repetition, identity.baseline, identity.task)

    def register(self, identities: Iterable[Any]) -> None:
        now = time.time()
        with self._db:
            for identity in identities:
                self._db.execute(
                    """INSERT OR IGNORE INTO logical_tasks
                    (logical_key, repository, repetition, baseline, task, state,
                     scientific_status, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*self._identity(identity), TaskState.PENDING.value, "UNOBSERVED", now),
                )

    def _row(self, identity: Any) -> sqlite3.Row:
        row = self._db.execute(
            "SELECT * FROM logical_tasks WHERE logical_key = ?", (identity.key,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unregistered logical task: {identity.key}")
        return row

    def state(self, identity: Any) -> TaskState:
        return TaskState(self._row(identity)["state"])

    def instances(self, identity: Any) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM execution_instances WHERE logical_key = ? ORDER BY ordinal",
            (identity.key,),
        ).fetchall()
        return [dict(row) for row in rows]

    def start_execution(
        self,
        identity: Any,
        instance_id: str,
        *,
        model: str,
        config_identity: str,
        provider_start: float | None = None,
    ) -> None:
        now = time.time()
        with self._db:
            row = self._row(identity)
            current = TaskState(row["state"])
            history = self.instances(identity)
            if current == TaskState.COMPLETED:
                raise ValueError(f"completed task cannot be rerun: {identity.key}")
            if current == TaskState.RUNNING:
                raise ValueError(f"task already running: {identity.key}")
            censor_count = sum(item["state"] == TaskState.PROVIDER_CENSORED.value for item in history)
            if current == TaskState.PROVIDER_CENSORED and history[-1].get("safe_to_retry") != 1:
                raise ValueError(f"provider-censored task is not safe for automatic retry: {identity.key}")
            if censor_count > self.max_provider_censor_retries:
                raise ValueError(f"provider-censor retry bound exceeded: {identity.key}")
            ordinal = len(history) + 1
            self._db.execute(
                """INSERT INTO execution_instances
                (instance_id, logical_key, ordinal, state, execution_status,
                 scientific_status, provider_start, model, config_identity, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (instance_id, identity.key, ordinal, TaskState.RUNNING.value, "RUNNING",
                 "UNOBSERVED", provider_start or now, model, config_identity, now),
            )
            self._db.execute(
                "UPDATE logical_tasks SET state=?, scientific_status=?, latest_instance_id=?, updated_at=? WHERE logical_key=?",
                (TaskState.RUNNING.value, "UNOBSERVED", instance_id, now, identity.key),
            )

    def _finish(self, identity: Any, instance_id: str, state: TaskState, *, scientific_status: str,
                provider_end: float | None = None, provider_status: str | None = None,
                reason: dict[str, Any] | None = None, token_usage: dict[str, Any] | None = None,
                agent_terminal_state: str | None = None, patch_commit: str | None = None,
                visible_eval: dict[str, Any] | None = None, hidden_eval: dict[str, Any] | None = None,
                score_components: dict[str, Any] | None = None,
                artifact_hashes: dict[str, str] | None = None, safe_to_retry: bool | None = None,
                task_metric: dict[str, Any] | None = None) -> None:
        if state not in TERMINAL_STATES:
            raise ValueError("finish requires a terminal state")
        now = time.time()
        with self._db:
            row = self._db.execute(
                "SELECT state FROM execution_instances WHERE instance_id=? AND logical_key=?",
                (instance_id, identity.key),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown execution instance: {instance_id}")
            if row["state"] != TaskState.RUNNING.value:
                raise ValueError(f"execution instance is immutable after completion: {instance_id}")
            self._db.execute(
                """UPDATE execution_instances SET state=?, execution_status=?, scientific_status=?,
                provider_end=?, provider_status=?, provider_reason_json=?, token_usage_json=?,
                agent_terminal_state=?, patch_commit=?, visible_eval_json=?, hidden_eval_json=?,
                score_components_json=?, artifact_hashes_json=?, safe_to_retry=?
                WHERE instance_id=?""",
                (state.value, "COMPLETED" if state == TaskState.COMPLETED else "FAILED",
                 scientific_status, provider_end or now, provider_status, self._json(reason),
                 self._json(token_usage), agent_terminal_state, patch_commit, self._json(visible_eval),
                 self._json(hidden_eval), self._json(score_components), self._json(artifact_hashes),
                 None if safe_to_retry is None else int(safe_to_retry), instance_id),
            )
            self._db.execute(
                "UPDATE logical_tasks SET state=?, scientific_status=?, latest_instance_id=?, task_metric_json=?, updated_at=? WHERE logical_key=?",
                (state.value, scientific_status, instance_id, self._json(task_metric), now, identity.key),
            )

    def complete_execution(self, identity: Any, instance_id: str, **payload: Any) -> None:
        self._finish(identity, instance_id, TaskState.COMPLETED, scientific_status="OBSERVED", **payload)

    def censor_execution(self, identity: Any, instance_id: str, evidence: dict[str, Any], **payload: Any) -> None:
        reason = classify_provider_censor(evidence)
        self._finish(identity, instance_id, TaskState.PROVIDER_CENSORED, scientific_status="CENSORED",
                     reason=reason, provider_status="PROVIDER_CENSORED",
                     safe_to_retry=reason["safe_to_retry"], **payload)

    def fail_execution(self, identity: Any, instance_id: str, state: TaskState, **payload: Any) -> None:
        if state not in {TaskState.TIMEOUT, TaskState.MODEL_FAILED, TaskState.INFRASTRUCTURE_FAILED}:
            raise ValueError("fail_execution accepts timeout, model, or infrastructure failure")
        self._finish(identity, instance_id, state, scientific_status=state.value, **payload)

    def resume_actions(self, *, provider_available: bool = False) -> dict[str, str]:
        actions: dict[str, str] = {}
        rows = self._db.execute("SELECT * FROM logical_tasks ORDER BY logical_key").fetchall()
        for row in rows:
            state = TaskState(row["state"])
            if state == TaskState.COMPLETED:
                action = "SKIP_COMPLETED"
            elif state == TaskState.PENDING:
                action = "EXECUTE"
            elif state == TaskState.PROVIDER_CENSORED:
                count = self._db.execute(
                    "SELECT COUNT(*) AS n FROM execution_instances WHERE logical_key=? AND state=?",
                    (row["logical_key"], TaskState.PROVIDER_CENSORED.value),
                ).fetchone()["n"]
                latest = self._db.execute(
                    "SELECT safe_to_retry FROM execution_instances WHERE logical_key=? ORDER BY ordinal DESC LIMIT 1",
                    (row["logical_key"],),
                ).fetchone()
                safe = latest is not None and latest["safe_to_retry"] == 1
                action = "RETRY_PROVIDER_CENSORED" if provider_available and safe and count <= self.max_provider_censor_retries else "STOP_PROVIDER_CENSORED"
            elif state == TaskState.MODEL_FAILED:
                action = "PRESERVE_MODEL_FAILURE"
            elif state == TaskState.TIMEOUT:
                action = "PRESERVE_TIMEOUT"
            else:
                action = "STOP_INFRASTRUCTURE_FAILURE" if state == TaskState.INFRASTRUCTURE_FAILED else "STOP_RUNNING"
            actions[row["logical_key"]] = action
        return actions

    def all_completed(self) -> bool:
        row = self._db.execute(
            "SELECT COUNT(*) AS total, SUM(state = ?) AS complete FROM logical_tasks",
            (TaskState.COMPLETED.value,),
        ).fetchone()
        return bool(row["total"]) and row["total"] == row["complete"]

    def campaign_score(self) -> dict[str, Any] | None:
        if not self.all_completed():
            return None
        rows = self._db.execute("SELECT task_metric_json FROM logical_tasks ORDER BY logical_key").fetchall()
        metrics = [json.loads(row["task_metric_json"]) for row in rows]
        return {"status": "AVAILABLE", "task_count": len(metrics), "metrics": metrics}


def classify_provider_censor(evidence: dict[str, Any]) -> dict[str, Any]:
    """Validate explicit provider evidence and derive retry eligibility."""
    if evidence.get("classification") != TaskState.PROVIDER_CENSORED.value:
        raise ValueError("provider censor evidence must declare PROVIDER_CENSORED")
    reason = evidence.get("provider_error_class")
    if reason not in PROVIDER_REASON_CLASSES:
        raise ValueError(f"unsupported or missing provider_error_class: {reason!r}")
    required = ("model_output_generated", "tool_execution_started", "repository_modified")
    if any(key not in evidence or not isinstance(evidence[key], bool) for key in required):
        raise ValueError("provider censor evidence requires explicit boolean side-effect fields")
    result = dict(evidence)
    result["safe_to_retry"] = not any(evidence[key] for key in required)
    return result
