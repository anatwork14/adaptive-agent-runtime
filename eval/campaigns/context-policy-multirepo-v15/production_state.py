"""V15's production-path ledger, provider classifier, and resume controller.

The scientific campaign is unchanged from V14.  This module preserves the
operational boundary repair and is paired with V15's profile staging: every provider request has a
durable execution instance, every terminal transition updates the authoritative
logical-task ledger and checkpoint in one SQLite transaction, and task-level
failures do not accidentally become a run-level fail-fast condition.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
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


TERMINAL_STATES = {
    TaskState.COMPLETED,
    TaskState.PROVIDER_CENSORED,
    TaskState.TIMEOUT,
    TaskState.MODEL_FAILED,
    TaskState.INFRASTRUCTURE_FAILED,
}
PROVIDER_CLASSES = {
    "USAGE_LIMIT",
    "QUOTA_EXCEEDED",
    "RATE_LIMIT",
    "PROVIDER_5XX",
    "SERVICE_UNAVAILABLE",
    "AUTHENTICATION_SERVICE",
    "SESSION_SERVICE",
    "TRANSPORT_BEFORE_OUTPUT",
}


class AttemptInitializationError(RuntimeError):
    """The production attempt could not be made ready before provider use."""


@dataclass(frozen=True)
class TaskIdentity:
    repository: str
    repetition: int
    baseline: str
    task: str

    @property
    def key(self) -> str:
        return f"{self.repository}/r{self.repetition}/{self.baseline}/{self.task}"


def build_campaign_identities() -> list[TaskIdentity]:
    return [
        TaskIdentity(repository, repetition, baseline, task)
        for repository in ("click", "httpx", "python-dotenv")
        for repetition in range(1, 7)
        for baseline in ("B3", "B5", "B7")
        for task in ("T001", "T002", "T003")
    ]


def build_fixture_identities(count: int) -> list[TaskIdentity]:
    if count < 1:
        raise ValueError("fixture count must be positive")
    return [TaskIdentity("fixture", 1, "B3", f"T{i:03d}") for i in range(1, count + 1)]


def _event_text(events: Iterable[Any]) -> str:
    values: list[str] = []
    for event in events:
        if isinstance(event, dict):
            values.extend(str(event.get(key, "")) for key in ("type", "message", "error", "detail"))
        else:
            values.append(str(event))
    return " ".join(values).lower()


def _provider_class(text: str) -> str | None:
    if "usage limit" in text or "usage_limit" in text or "tokens exhausted" in text:
        return "USAGE_LIMIT"
    if "quota" in text or "credit limit" in text:
        return "QUOTA_EXCEEDED"
    if "rate limit" in text or "too many requests" in text or "http 429" in text or " 429" in text:
        return "RATE_LIMIT"
    if "authentication" in text or "unauthorized" in text or " http 401" in text or " http 403" in text:
        return "AUTHENTICATION_SERVICE"
    if "session" in text and ("expired" in text or "invalid" in text or "closed" in text):
        return "SESSION_SERVICE"
    if any(marker in text for marker in ("service unavailable", "bad gateway", "gateway timeout", "http 5", " 500", " 502", " 503", " 504")):
        return "PROVIDER_5XX"
    if any(marker in text for marker in ("connection reset", "connection refused", "transport error", "network error")):
        return "TRANSPORT_BEFORE_OUTPUT"
    return None


def classify_provider_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Classify structured provider evidence with provider-first precedence.

    A nonzero CLI status is only a process outcome.  It cannot establish a
    provider failure without an explicit provider lifecycle/error signal.
    """
    events = evidence.get("provider_events", [])
    text = _event_text(events)
    explicit = str(evidence.get("provider_error_class", "")).upper() or None
    provider_class = explicit if explicit in PROVIDER_CLASSES else _provider_class(text)
    provider_started = bool(evidence.get("provider_request_started"))
    response_started = bool(evidence.get("provider_response_started"))
    model_output = bool(evidence.get("model_output_generated")) or any(
        isinstance(event, dict)
        and event.get("type") == "agent_message"
        and event.get("status") in {"completed", "started"}
        for event in events
    )
    tool_execution = bool(evidence.get("tool_execution_started")) or any(
        isinstance(event, dict) and event.get("type") in {"command_execution", "tool_call", "file_change"}
        for event in events
    )
    repository_modified = bool(evidence.get("repository_modified")) or any(
        isinstance(event, dict)
        and event.get("type") == "file_change"
        and bool(event.get("changes", True))
        for event in events
    )
    infrastructure = bool(evidence.get("infrastructure_failure"))
    timed_out = bool(evidence.get("timed_out"))
    if provider_class is not None and (provider_started or response_started or events):
        terminal = TaskState.PROVIDER_CENSORED.value
        provider_failure = True
    elif infrastructure:
        terminal = TaskState.INFRASTRUCTURE_FAILED.value
        provider_failure = False
    elif timed_out:
        terminal = TaskState.TIMEOUT.value
        provider_failure = False
    else:
        terminal = TaskState.MODEL_FAILED.value
        provider_failure = False
    return {
        "provider_failure": provider_failure,
        "provider_error_class": provider_class,
        "terminal_state": terminal,
        "safe_to_retry": not (model_output or tool_execution or repository_modified),
        "model_output_generated": model_output,
        "tool_execution_started": tool_execution,
        "repository_modified": repository_modified,
        "provider_request_started": provider_started,
        "provider_response_started": response_started,
        "cli_exit_code": evidence.get("provider_exit_code"),
        "raw_evidence": evidence,
    }


class ProductionLedger:
    """Authoritative append-only execution ledger and integrated checkpoint."""

    def __init__(
        self,
        path: str | Path,
        *,
        campaign_id: str,
        attempt_id: str,
        expected_tasks: int,
        max_provider_censor_retries: int = 1,
        checkpoint_path: str | Path | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.campaign_id = campaign_id
        self.attempt_id = attempt_id
        self.expected_tasks = expected_tasks
        self.max_provider_censor_retries = max_provider_censor_retries
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else None
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaign_meta (
                campaign_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL,
                expected_tasks INTEGER NOT NULL, ledger_identity TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS logical_tasks (
                logical_key TEXT PRIMARY KEY, repository TEXT NOT NULL,
                repetition INTEGER NOT NULL, baseline TEXT NOT NULL, task TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                state TEXT NOT NULL, scientific_status TEXT NOT NULL,
                current_execution_instance TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
                retry_permitted INTEGER NOT NULL DEFAULT 0, visible_eval_status TEXT,
                hidden_eval_status TEXT, scientific_completion INTEGER NOT NULL DEFAULT 0,
                measurement_ref TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS execution_instances (
                instance_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                logical_key TEXT NOT NULL REFERENCES logical_tasks(logical_key),
                model TEXT NOT NULL, config_identity TEXT NOT NULL,
                ordinal INTEGER NOT NULL, state TEXT NOT NULL, execution_status TEXT NOT NULL,
                provider_start REAL, provider_end REAL, provider_request_started INTEGER NOT NULL,
                provider_response_started INTEGER NOT NULL, provider_failure_class TEXT,
                cli_exit_code INTEGER, usable_output INTEGER NOT NULL DEFAULT 0,
                tool_execution_started INTEGER NOT NULL DEFAULT 0,
                workspace_mutation INTEGER NOT NULL DEFAULT 0, retry_safe INTEGER,
                token_usage_json TEXT, terminal_classification TEXT NOT NULL,
                raw_evidence_ref TEXT, measurement_ref TEXT, created_at REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS execution_identity_ordinal
                ON execution_instances(logical_key, ordinal);
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id INTEGER PRIMARY KEY CHECK (checkpoint_id = 1),
                campaign_id TEXT NOT NULL, attempt_id TEXT NOT NULL,
                ledger_identity TEXT NOT NULL, last_durable_transition TEXT,
                next_schedulable_task TEXT, counts_json TEXT NOT NULL, updated_at REAL NOT NULL
            );
            """
        )
        identity = hashlib.sha256(f"{self.campaign_id}:{self.attempt_id}:{self.path}".encode()).hexdigest()
        row = self._db.execute("SELECT * FROM campaign_meta").fetchone()
        if row is None:
            self._db.execute("INSERT INTO campaign_meta VALUES (?, ?, ?, ?, ?)", (campaign_id, attempt_id, expected_tasks, identity, time.time()))
            self._db.commit()
        elif (row["campaign_id"], row["attempt_id"], row["expected_tasks"]) != (campaign_id, attempt_id, expected_tasks):
            self._db.close()
            raise ValueError("ledger identity mismatch")
        self.ledger_identity = row["ledger_identity"] if row else identity
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "ProductionLedger":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _json(value: Any) -> str | None:
        return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"))

    def register(
        self,
        identities: Iterable[TaskIdentity],
        *,
        metadata_by_key: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        values = list(identities)
        keys = [identity.key for identity in values]
        if len(values) != self.expected_tasks:
            raise ValueError(
                f"logical task registration count mismatch: {len(values)} != {self.expected_tasks}"
            )
        if len(set(keys)) != len(keys):
            raise ValueError("logical task registration contains duplicate identities")
        now = time.time()
        with self._db:
            existing = {
                row["logical_key"]
                for row in self._db.execute("SELECT logical_key FROM logical_tasks").fetchall()
            }
            if existing and existing != set(keys):
                raise ValueError("logical task registration identity mismatch")
            for identity in values:
                metadata = (metadata_by_key or {}).get(identity.key, {})
                if existing:
                    row = self._db.execute(
                        "SELECT metadata_json FROM logical_tasks WHERE logical_key=?",
                        (identity.key,),
                    ).fetchone()
                    if row is None or json.loads(row["metadata_json"]) != metadata:
                        raise ValueError(f"logical task metadata mismatch: {identity.key}")
                    continue
                self._db.execute(
                    """INSERT INTO logical_tasks
                    (logical_key, repository, repetition, baseline, task, metadata_json, state, scientific_status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (identity.key, identity.repository, identity.repetition, identity.baseline, identity.task, self._json(metadata) or "{}", TaskState.PENDING.value, "UNOBSERVED", now, now),
                )
            count = self._db.execute("SELECT COUNT(*) AS n FROM logical_tasks").fetchone()["n"]
            if count != self.expected_tasks:
                raise ValueError(f"logical task registration incomplete: {count} != {self.expected_tasks}")
            self._checkpoint("REGISTER", None)

    def _row(self, identity: TaskIdentity) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM logical_tasks WHERE logical_key = ?", (identity.key,)).fetchone()
        if row is None:
            raise KeyError(f"unregistered logical task: {identity.key}")
        return row

    def state(self, identity: TaskIdentity) -> TaskState:
        return TaskState(self._row(identity)["state"])

    def instances(self, identity: TaskIdentity) -> list[dict[str, Any]]:
        return [dict(row) for row in self._db.execute("SELECT * FROM execution_instances WHERE logical_key=? ORDER BY ordinal", (identity.key,)).fetchall()]

    def counts(self) -> dict[str, int]:
        counts = self._state_counts()
        if sum(counts.values()) != self.expected_tasks:
            raise AssertionError("logical task completeness invariant violated")
        return counts

    def _state_counts(self) -> dict[str, int]:
        counts = {state.value: 0 for state in TaskState}
        for row in self._db.execute("SELECT state, COUNT(*) AS n FROM logical_tasks GROUP BY state").fetchall():
            counts[row["state"]] = row["n"]
        return counts

    def logical_task_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) AS n FROM logical_tasks").fetchone()["n"])

    def execution_instance_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) AS n FROM execution_instances").fetchone()["n"])

    def provider_request_count(self) -> int:
        return int(
            self._db.execute(
                "SELECT COUNT(*) AS n FROM execution_instances WHERE provider_request_started=1"
            ).fetchone()["n"]
        )

    def execution_boundary_snapshot(
        self,
        *,
        manifest_path: str | Path,
        checkpoint_path: str | Path,
    ) -> dict[str, Any]:
        """Return fail-closed readiness evidence immediately before a provider call."""
        logical_tasks = self.logical_task_count()
        execution_instances = self.execution_instance_count()
        counts = self._state_counts()
        state_total = sum(counts.values())
        checkpoint = Path(checkpoint_path).is_file() and self.checkpoint() is not None
        manifest = Path(manifest_path).is_file()
        provider_requests = self.provider_request_count()
        reason: str | None = None
        if logical_tasks != self.expected_tasks:
            reason = "logical task ledger is not materialized"
        elif state_total != self.expected_tasks:
            reason = "logical task state total is invalid"
        elif execution_instances != 0:
            reason = "execution instances already exist"
        elif not checkpoint:
            reason = "checkpoint is not initialized"
        elif not manifest:
            reason = "pre-execution manifest is not persisted"
        elif provider_requests != 0:
            reason = "provider request already exists before boundary"
        return {
            "ready": reason is None,
            "logical_tasks": logical_tasks,
            "execution_instances": execution_instances,
            "state_total": state_total,
            "checkpoint": checkpoint,
            "pre_execution_manifest": manifest,
            "provider_requests": provider_requests,
            "blocking_reason": reason,
        }

    def _next_schedulable(self) -> str | None:
        row = self._db.execute("SELECT logical_key FROM logical_tasks WHERE state=? ORDER BY logical_key LIMIT 1", (TaskState.PENDING.value,)).fetchone()
        return row["logical_key"] if row else None

    def _checkpoint(self, transition: str, identity: TaskIdentity | None) -> None:
        counts = self.counts()
        payload = {
            "campaign_id": self.campaign_id,
            "attempt_id": self.attempt_id,
            "ledger_identity": self.ledger_identity,
            "last_durable_transition": f"{transition}:{identity.key if identity else ''}",
            "next_schedulable_task": self._next_schedulable(),
            "counts": counts,
        }
        self._db.execute(
            """INSERT INTO checkpoints (checkpoint_id, campaign_id, attempt_id, ledger_identity, last_durable_transition, next_schedulable_task, counts_json, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(checkpoint_id) DO UPDATE SET campaign_id=excluded.campaign_id, attempt_id=excluded.attempt_id,
            ledger_identity=excluded.ledger_identity, last_durable_transition=excluded.last_durable_transition,
            next_schedulable_task=excluded.next_schedulable_task, counts_json=excluded.counts_json, updated_at=excluded.updated_at""",
            (self.campaign_id, self.attempt_id, self.ledger_identity, payload["last_durable_transition"], payload["next_schedulable_task"], self._json(counts), time.time()),
        )
        if self.checkpoint_path is not None:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.checkpoint_path.with_name(self.checkpoint_path.name + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with tmp.open("r+") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(self.checkpoint_path)

    def checkpoint(self) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM checkpoints WHERE checkpoint_id=1").fetchone()
        if row is None:
            return {"campaign_id": self.campaign_id, "attempt_id": self.attempt_id, "ledger_identity": self.ledger_identity, "last_durable_transition": None, "next_schedulable_task": self._next_schedulable(), "counts": self._state_counts()}
        return {"campaign_id": row["campaign_id"], "attempt_id": row["attempt_id"], "ledger_identity": row["ledger_identity"], "last_durable_transition": row["last_durable_transition"], "next_schedulable_task": row["next_schedulable_task"], "counts": json.loads(row["counts_json"])}

    def start_execution(self, identity: TaskIdentity, *, request_id: str, model: str, config_identity: str) -> str:
        now = time.time()
        with self._db:
            row = self._row(identity)
            current = TaskState(row["state"])
            history = self.instances(identity)
            if current in {TaskState.COMPLETED, TaskState.MODEL_FAILED, TaskState.TIMEOUT, TaskState.INFRASTRUCTURE_FAILED}:
                raise ValueError(f"terminal task cannot be rerun: {identity.key}")
            if current == TaskState.RUNNING:
                raise ValueError(f"task already running: {identity.key}")
            if current == TaskState.PROVIDER_CENSORED:
                if not history or history[-1]["retry_safe"] != 1:
                    raise ValueError(f"provider-censored task is not safe for automatic retry: {identity.key}")
                censor_count = sum(item["state"] == TaskState.PROVIDER_CENSORED.value for item in history)
                if censor_count > self.max_provider_censor_retries:
                    raise ValueError(f"provider-censor retry bound exceeded: {identity.key}")
            ordinal = len(history) + 1
            instance_id = f"{identity.key}:e{ordinal:03d}"
            self._db.execute(
                """INSERT INTO execution_instances
                (instance_id, request_id, logical_key, model, config_identity, ordinal, state, execution_status, provider_start,
                 provider_request_started, provider_response_started, terminal_classification, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (instance_id, request_id, identity.key, model, config_identity, ordinal, TaskState.RUNNING.value, "RUNNING", None, 0, 0, "RUNNING", now),
            )
            self._db.execute("UPDATE logical_tasks SET state=?, current_execution_instance=?, retry_count=?, retry_permitted=?, updated_at=? WHERE logical_key=?", (TaskState.RUNNING.value, instance_id, ordinal - 1, 0, now, identity.key))
            self._checkpoint("START", identity)
        return instance_id

    def mark_provider_started(self, instance_id: str, *, identity: TaskIdentity) -> None:
        """Durably mark the provider boundary after the execution instance exists."""
        now = time.time()
        with self._db:
            row = self._db.execute(
                "SELECT state, provider_request_started FROM execution_instances WHERE instance_id=? AND logical_key=?",
                (instance_id, identity.key),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown execution instance: {instance_id}")
            if row["state"] != TaskState.RUNNING.value or row["provider_request_started"]:
                raise ValueError(f"execution instance cannot cross provider boundary: {instance_id}")
            self._db.execute(
                "UPDATE execution_instances SET provider_start=?, provider_request_started=1 WHERE instance_id=?",
                (now, instance_id),
            )
            self._checkpoint("PROVIDER_START", identity)

    def identity_metadata(self, identity: TaskIdentity) -> dict[str, Any]:
        row = self._row(identity)
        return json.loads(row["metadata_json"])

    def _finish(self, identity: TaskIdentity, instance_id: str, state: TaskState, *, classification: str, provider_response_started: bool = False, provider_failure_class: str | None = None, cli_exit_code: int | None = None, usable_output: bool = False, tool_execution_started: bool = False, workspace_mutation: bool = False, retry_safe: bool | None = None, token_usage: dict[str, Any] | None = None, raw_evidence_ref: str | None = None, measurement_ref: str | None = None, visible_eval_status: str | None = None, hidden_eval_status: str | None = None) -> None:
        if state not in TERMINAL_STATES:
            raise ValueError("terminal state required")
        if state == TaskState.COMPLETED and not measurement_ref:
            raise ValueError("completed task requires durable measurement export/reference")
        now = time.time()
        with self._db:
            current = self._db.execute("SELECT state FROM execution_instances WHERE instance_id=? AND logical_key=?", (instance_id, identity.key)).fetchone()
            if current is None:
                raise KeyError(f"unknown execution instance: {instance_id}")
            if current["state"] != TaskState.RUNNING.value:
                raise ValueError(f"execution instance is immutable after completion: {instance_id}")
            self._db.execute(
                """UPDATE execution_instances SET state=?, execution_status=?, provider_end=?, provider_response_started=?, provider_failure_class=?, cli_exit_code=?, usable_output=?, tool_execution_started=?, workspace_mutation=?, retry_safe=?, token_usage_json=?, terminal_classification=?, raw_evidence_ref=?, measurement_ref=? WHERE instance_id=?""",
                (state.value, "COMPLETED" if state == TaskState.COMPLETED else "FAILED", now, int(provider_response_started), provider_failure_class, cli_exit_code, int(usable_output), int(tool_execution_started), int(workspace_mutation), None if retry_safe is None else int(retry_safe), self._json(token_usage), classification, raw_evidence_ref, measurement_ref, instance_id),
            )
            self._db.execute(
                """UPDATE logical_tasks SET state=?, scientific_status=?, current_execution_instance=?, retry_count=?, retry_permitted=?, visible_eval_status=?, hidden_eval_status=?, scientific_completion=?, measurement_ref=?, updated_at=? WHERE logical_key=?""",
                (state.value, "OBSERVED" if state == TaskState.COMPLETED else ("CENSORED" if state == TaskState.PROVIDER_CENSORED else state.value), instance_id, int(state == TaskState.PROVIDER_CENSORED), int(state == TaskState.PROVIDER_CENSORED and bool(retry_safe)), visible_eval_status, hidden_eval_status, int(state == TaskState.COMPLETED), measurement_ref, now, identity.key),
            )
            self._checkpoint("FINISH_" + state.value, identity)

    def complete_execution(self, identity: TaskIdentity, instance_id: str, *, measurement_ref: str, visible_eval_status: str = "PASS", hidden_eval_status: str = "PASS", token_usage: dict[str, Any] | None = None, raw_evidence_ref: str | None = None) -> None:
        self._finish(identity, instance_id, TaskState.COMPLETED, classification="COMPLETED", provider_response_started=True, cli_exit_code=0, usable_output=True, token_usage=token_usage, raw_evidence_ref=raw_evidence_ref, measurement_ref=measurement_ref, visible_eval_status=visible_eval_status, hidden_eval_status=hidden_eval_status)

    def censor_execution(self, identity: TaskIdentity, instance_id: str, evidence: dict[str, Any], *, raw_evidence_ref: str | None = None) -> None:
        result = classify_provider_evidence(evidence)
        if result["terminal_state"] != TaskState.PROVIDER_CENSORED.value:
            raise ValueError("censor_execution requires explicit provider evidence")
        self._finish(identity, instance_id, TaskState.PROVIDER_CENSORED, classification=TaskState.PROVIDER_CENSORED.value, provider_response_started=result["provider_response_started"], provider_failure_class=result["provider_error_class"], cli_exit_code=result["cli_exit_code"], usable_output=result["model_output_generated"], tool_execution_started=result["tool_execution_started"], workspace_mutation=result["repository_modified"], retry_safe=result["safe_to_retry"], token_usage=evidence.get("token_usage"), raw_evidence_ref=raw_evidence_ref)

    def fail_execution(self, identity: TaskIdentity, instance_id: str, state: TaskState, *, cli_exit_code: int | None = None, raw_evidence_ref: str | None = None) -> None:
        if state not in {TaskState.MODEL_FAILED, TaskState.TIMEOUT, TaskState.INFRASTRUCTURE_FAILED}:
            raise ValueError("fail_execution accepts model, timeout, or infrastructure failure")
        self._finish(identity, instance_id, state, classification=state.value, cli_exit_code=cli_exit_code, raw_evidence_ref=raw_evidence_ref)

    def resume_actions(self, *, provider_available: bool = False) -> dict[str, str]:
        actions: dict[str, str] = {}
        for row in self._db.execute("SELECT * FROM logical_tasks ORDER BY logical_key").fetchall():
            state = TaskState(row["state"])
            if state == TaskState.COMPLETED:
                action = "SKIP_COMPLETED"
            elif state == TaskState.PENDING:
                action = "EXECUTE"
            elif state == TaskState.MODEL_FAILED:
                action = "PRESERVE_MODEL_FAILURE"
            elif state == TaskState.TIMEOUT:
                action = "PRESERVE_TIMEOUT"
            elif state == TaskState.PROVIDER_CENSORED:
                latest = self._db.execute("SELECT retry_safe FROM execution_instances WHERE logical_key=? ORDER BY ordinal DESC LIMIT 1", (row["logical_key"],)).fetchone()
                safe = latest is not None and latest["retry_safe"] == 1
                count = self._db.execute("SELECT COUNT(*) AS n FROM execution_instances WHERE logical_key=? AND state=?", (row["logical_key"], TaskState.PROVIDER_CENSORED.value)).fetchone()["n"]
                action = "RETRY_PROVIDER_CENSORED" if provider_available and safe and count <= self.max_provider_censor_retries else "STOP_PROVIDER_CENSORED"
            else:
                action = "STOP_INFRASTRUCTURE_FAILURE" if state == TaskState.INFRASTRUCTURE_FAILED else "STOP_RUNNING"
            actions[row["logical_key"]] = action
        return actions

    def request_instance_count(self) -> int:
        requests = self._db.execute("SELECT COUNT(DISTINCT request_id) AS n FROM execution_instances").fetchone()["n"]
        instances = self._db.execute("SELECT COUNT(*) AS n FROM execution_instances").fetchone()["n"]
        if requests != instances:
            raise AssertionError("provider request to execution-instance invariant violated")
        return instances

    def all_completed(self) -> bool:
        return self.counts()[TaskState.COMPLETED.value] == self.expected_tasks

    def recover_running(self) -> dict[str, str]:
        """Expose ambiguous post-boundary work without fabricating a retry."""
        actions: dict[str, str] = {}
        for row in self._db.execute(
            "SELECT logical_tasks.logical_key, execution_instances.provider_request_started "
            "FROM logical_tasks JOIN execution_instances USING (logical_key) "
            "WHERE logical_tasks.state=?",
            (TaskState.RUNNING.value,),
        ).fetchall():
            actions[row["logical_key"]] = (
                "PRESERVE_AMBIGUOUS_PROVIDER_START"
                if row["provider_request_started"]
                else "RECONCILE_PRE_PROVIDER_CRASH"
            )
        return actions

    def campaign_score(self) -> dict[str, Any] | None:
        if not self.all_completed():
            return None
        refs = [row["measurement_ref"] for row in self._db.execute("SELECT measurement_ref FROM logical_tasks ORDER BY logical_key").fetchall()]
        if any(not ref for ref in refs):
            raise AssertionError("completed task is missing measurement export")
        return {"status": "AVAILABLE", "task_count": len(refs), "measurement_refs": refs}


def initialize_production_attempt(
    *,
    ledger_path: str | Path,
    manifest_path: str | Path,
    checkpoint_path: str | Path,
    identities: Iterable[TaskIdentity],
    campaign_id: str,
    attempt_id: str,
    expected_tasks: int,
    manifest: dict[str, Any],
    metadata_by_key: dict[str, dict[str, Any]] | None = None,
    fail_component: str | None = None,
) -> ProductionLedger:
    """Atomically prepare the non-provider portion of one production attempt."""
    paths = [Path(ledger_path), Path(manifest_path), Path(checkpoint_path)]
    if any(path.exists() for path in paths):
        raise AttemptInitializationError("production attempt paths must be new")
    if fail_component == "ledger":
        raise AttemptInitializationError("production ledger initialization failed")
    ledger: ProductionLedger | None = None
    try:
        ledger = ProductionLedger(
            ledger_path,
            campaign_id=campaign_id,
            attempt_id=attempt_id,
            expected_tasks=expected_tasks,
            checkpoint_path=checkpoint_path,
        )
        values = list(identities)
        if fail_component == "parity":
            values = values[:-1]
        ledger.register(values, metadata_by_key=metadata_by_key)
        if fail_component == "checkpoint":
            raise AttemptInitializationError("checkpoint initialization failed")
        if fail_component == "manifest":
            raise AttemptInitializationError("pre-execution manifest initialization failed")
        path = Path(manifest_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with tmp.open("r+") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
        snapshot = ledger.execution_boundary_snapshot(
            manifest_path=path,
            checkpoint_path=checkpoint_path,
        )
        if not snapshot["ready"]:
            raise AttemptInitializationError(snapshot["blocking_reason"] or "boundary is not ready")
        return ledger
    except AttemptInitializationError:
        if ledger is not None:
            ledger.close()
        for path in paths + [Path(str(ledger_path) + "-wal"), Path(str(ledger_path) + "-shm")]:
            path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if ledger is not None:
            ledger.close()
        for path in paths + [Path(str(ledger_path) + "-wal"), Path(str(ledger_path) + "-shm")]:
            path.unlink(missing_ok=True)
        raise AttemptInitializationError(str(exc)) from exc


class ProductionTaskObserver:
    """Adapter between the real task runner and the authoritative ledger."""

    def __init__(
        self,
        ledger: ProductionLedger,
        *,
        repository: str,
        repetition: int,
        baseline: str,
        plan_digest: str,
        hidden_test_digest: str,
        measurement_dir: str | Path,
        provider_model: str,
        config_identity: str,
        execution_mode: str = "sequence",
        timeout_seconds: int = 600,
    ) -> None:
        self.ledger = ledger
        self.repository = repository
        self.repetition = repetition
        self.baseline = baseline
        self.plan_digest = plan_digest
        self.hidden_test_digest = hidden_test_digest
        self.measurement_dir = Path(measurement_dir)
        self.provider_model = provider_model
        self.config_identity = config_identity
        self.execution_mode = execution_mode
        self.timeout_seconds = timeout_seconds
        self._tickets: dict[str, tuple[TaskIdentity, str]] = {}

    def _identity(self, task_id: str) -> TaskIdentity:
        identity = TaskIdentity(self.repository, self.repetition, self.baseline, task_id)
        metadata = self.ledger.identity_metadata(identity)
        expected = {
            "plan_digest": self.plan_digest,
            "hidden_test_digest": self.hidden_test_digest,
            "provider": "codex",
            "model": self.provider_model,
            "execution_mode": self.execution_mode,
            "timeout_seconds": self.timeout_seconds,
            "baseline_order_index": ("B3", "B5", "B7").index(self.baseline),
            "task_order_index": int(task_id.removeprefix("T")) - 1,
        }
        if metadata != expected:
            raise ValueError(f"frozen logical-task metadata mismatch: {identity.key}")
        return identity

    def begin_task(self, task_id: str) -> tuple[TaskIdentity, str]:
        identity = self._identity(task_id)
        request_id = hashlib.sha256(
            f"{self.ledger.campaign_id}:{self.ledger.attempt_id}:{identity.key}".encode()
        ).hexdigest()
        instance_id = self.ledger.start_execution(
            identity,
            request_id=request_id,
            model=self.provider_model,
            config_identity=self.config_identity,
        )
        ticket = (identity, instance_id)
        self._tickets[task_id] = ticket
        return ticket

    def before_provider(self, ticket: tuple[TaskIdentity, str]) -> None:
        identity, instance_id = ticket
        self.ledger.mark_provider_started(instance_id, identity=identity)

    def _evidence(self, result: Any) -> dict[str, Any]:
        events = [
            {"type": item.get("event", ""), "message": item.get("message", "")}
            for item in getattr(result, "provider_events", [])
            if isinstance(item, dict)
        ]
        lifecycle = getattr(result, "provider_lifecycle", {}) or {}
        tool_trace = getattr(result, "tool_trace", []) or []
        return {
            "provider_request_started": lifecycle.get("request_started") == "observed",
            "provider_response_started": lifecycle.get("response_started") == "observed",
            "provider_error_class": getattr(result, "failure_classification", None),
            "provider_exit_code": getattr(result, "provider_returncode", None),
            "provider_events": events,
            "model_output_generated": lifecycle.get("response_started") == "observed",
            "tool_execution_started": any(
                isinstance(item, dict) and item.get("action") not in {None, "cli_run"}
                for item in tool_trace
            ),
            "repository_modified": bool(getattr(result, "patch_ref", ""))
            and getattr(result, "patch_ref", "") != "",
            "timed_out": getattr(result, "provider_outcome", None) == "timeout",
            "token_usage": getattr(result, "token_usage", {}) or {},
        }

    def finish(
        self,
        ticket: tuple[TaskIdentity, str],
        *,
        result: Any,
        completed: bool,
        measurement: dict[str, Any] | None = None,
    ) -> None:
        identity, instance_id = ticket
        if completed:
            if measurement is None:
                raise ValueError("completed production task requires a measurement")
            self.measurement_dir.mkdir(parents=True, exist_ok=True)
            path = self.measurement_dir / f"{identity.key.replace('/', '__')}.json"
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(measurement, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            with tmp.open("r+") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(path)
            self.ledger.complete_execution(
                identity,
                instance_id,
                measurement_ref=str(path),
                token_usage=getattr(result, "token_usage", {}) or {},
            )
            return
        evidence = self._evidence(result)
        classified = classify_provider_evidence(evidence)
        if classified["terminal_state"] == TaskState.PROVIDER_CENSORED.value:
            self.ledger.censor_execution(identity, instance_id, evidence)
        elif classified["terminal_state"] == TaskState.TIMEOUT.value:
            self.ledger.fail_execution(identity, instance_id, TaskState.TIMEOUT)
        else:
            self.ledger.fail_execution(identity, instance_id, TaskState.MODEL_FAILED)

    def fail_unexpected(self, ticket: tuple[TaskIdentity, str]) -> None:
        identity, instance_id = ticket
        self.ledger.fail_execution(identity, instance_id, TaskState.INFRASTRUCTURE_FAILED)


class SimulatedInterruption(RuntimeError):
    pass


class ProductionCampaignRunner:
    """Provider-injected production controller used by V15's deterministic tests."""

    def __init__(self, ledger_path: str | Path, *, identities: list[TaskIdentity], evidence_dir: str | Path | None = None) -> None:
        self.identities = identities
        self.ledger = ProductionLedger(ledger_path, campaign_id="context-policy-multirepo-v15" if identities and identities[0].repository != "fixture" else "fixture", attempt_id="a001", expected_tasks=len(identities))
        if not self.ledger._db.execute("SELECT 1 FROM logical_tasks LIMIT 1").fetchone():
            self.ledger.register(identities)
        self.evidence_dir = Path(evidence_dir) if evidence_dir else Path(ledger_path).parent / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.provider_requests = 0
        self.legacy_fail_fast_triggered = False

    def __enter__(self) -> "ProductionCampaignRunner":
        return self

    def __exit__(self, *_: object) -> None:
        self.ledger.close()

    def _save_evidence(self, request_id: str, outcome: dict[str, Any]) -> Path:
        path = self.evidence_dir / f"{request_id}.json"
        path.write_text(json.dumps(outcome, sort_keys=True), encoding="utf-8")
        return path

    def _process(self, identity: TaskIdentity, outcome: dict[str, Any], *, provider_request: bool = True) -> None:
        request_id = str(outcome.get("request_id") or f"req-{self.ledger.request_instance_count() + 1:04d}")
        raw_ref = str(self._save_evidence(request_id, outcome))
        instance = self.ledger.start_execution(identity, request_id=request_id, model="gpt-5.5", config_identity="frozen-v15")
        if provider_request:
            self.ledger.mark_provider_started(instance, identity=identity)
            self.provider_requests += 1
        status = outcome.get("status")
        if status == "completed":
            self.ledger.complete_execution(identity, instance, measurement_ref=str(outcome["measurement_ref"]), raw_evidence_ref=raw_ref)
        elif status == "provider_censored":
            self.ledger.censor_execution(identity, instance, dict(outcome["evidence"]), raw_evidence_ref=raw_ref)
        elif status == "timeout":
            self.ledger.fail_execution(identity, instance, TaskState.TIMEOUT, cli_exit_code=outcome.get("exit_code"), raw_evidence_ref=raw_ref)
        else:
            self.ledger.fail_execution(identity, instance, TaskState.MODEL_FAILED, cli_exit_code=outcome.get("exit_code"), raw_evidence_ref=raw_ref)

    def run(self, outcomes: list[dict[str, Any]], *, interrupt_after: int | None = None, crash_before_persist: bool = False) -> None:
        if len(outcomes) != len(self.identities):
            raise ValueError("fixture outcomes must match logical task registration")
        for index, (identity, outcome) in enumerate(zip(self.identities, outcomes, strict=True), start=1):
            if self.ledger.state(identity) in TERMINAL_STATES:
                continue
            if crash_before_persist and index == 1:
                request_id = f"req-{self.provider_requests + 1:04d}"
                self._save_evidence(request_id, {**outcome, "request_id": request_id})
                raise SimulatedInterruption("crash before ledger persistence")
            self._process(identity, outcome)
            if interrupt_after == index:
                raise SimulatedInterruption("crash after durable transition")

    def resume(self, outcomes: list[dict[str, Any]], *, provider_available: bool = False) -> None:
        if len(outcomes) != len(self.identities):
            raise ValueError("fixture outcomes must match logical task registration")
        actions = self.ledger.resume_actions(provider_available=provider_available)
        for identity, outcome in zip(self.identities, outcomes, strict=True):
            action = actions[identity.key]
            if action != "EXECUTE":
                continue
            self._process(identity, outcome)

    def recover_pending(self, outcomes: list[dict[str, Any]]) -> None:
        pending = sorted(self.evidence_dir.glob("req-*.json"))
        for identity, outcome, path in zip(self.identities, outcomes, pending, strict=False):
            if self.ledger.state(identity) == TaskState.PENDING:
                recovered = json.loads(path.read_text(encoding="utf-8"))
                recovered.update(outcome)
                recovered["request_id"] = recovered.get("request_id") or path.stem
                self._process(identity, recovered, provider_request=False)
