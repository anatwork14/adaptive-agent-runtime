"""V12's production-path ledger, provider classifier, and resume controller.

The scientific campaign is unchanged from V12.  This module repairs the
operational boundary that V12 did not exercise: every provider request has a
durable execution instance, every terminal transition updates the authoritative
logical-task ledger and checkpoint in one SQLite transaction, and task-level
failures do not accidentally become a run-level fail-fast condition.
"""

from __future__ import annotations

import hashlib
import json
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

    def __init__(self, path: str | Path, *, campaign_id: str, attempt_id: str, expected_tasks: int, max_provider_censor_retries: int = 1) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.campaign_id = campaign_id
        self.attempt_id = attempt_id
        self.expected_tasks = expected_tasks
        self.max_provider_censor_retries = max_provider_censor_retries
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
                state TEXT NOT NULL, scientific_status TEXT NOT NULL,
                current_execution_instance TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
                retry_permitted INTEGER NOT NULL DEFAULT 0, visible_eval_status TEXT,
                hidden_eval_status TEXT, scientific_completion INTEGER NOT NULL DEFAULT 0,
                measurement_ref TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS execution_instances (
                instance_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                logical_key TEXT NOT NULL REFERENCES logical_tasks(logical_key),
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

    def register(self, identities: Iterable[TaskIdentity]) -> None:
        values = list(identities)
        now = time.time()
        with self._db:
            for identity in values:
                self._db.execute(
                    """INSERT OR IGNORE INTO logical_tasks
                    (logical_key, repository, repetition, baseline, task, state, scientific_status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (identity.key, identity.repository, identity.repetition, identity.baseline, identity.task, TaskState.PENDING.value, "UNOBSERVED", now, now),
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
        counts = {state.value: 0 for state in TaskState}
        for row in self._db.execute("SELECT state, COUNT(*) AS n FROM logical_tasks GROUP BY state").fetchall():
            counts[row["state"]] = row["n"]
        if sum(counts.values()) != self.expected_tasks:
            raise AssertionError("logical task completeness invariant violated")
        return counts

    def _next_schedulable(self) -> str | None:
        row = self._db.execute("SELECT logical_key FROM logical_tasks WHERE state=? ORDER BY logical_key LIMIT 1", (TaskState.PENDING.value,)).fetchone()
        return row["logical_key"] if row else None

    def _checkpoint(self, transition: str, identity: TaskIdentity | None) -> None:
        counts = self.counts()
        self._db.execute(
            """INSERT INTO checkpoints (checkpoint_id, campaign_id, attempt_id, ledger_identity, last_durable_transition, next_schedulable_task, counts_json, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(checkpoint_id) DO UPDATE SET campaign_id=excluded.campaign_id, attempt_id=excluded.attempt_id,
            ledger_identity=excluded.ledger_identity, last_durable_transition=excluded.last_durable_transition,
            next_schedulable_task=excluded.next_schedulable_task, counts_json=excluded.counts_json, updated_at=excluded.updated_at""",
            (self.campaign_id, self.attempt_id, self.ledger_identity, f"{transition}:{identity.key if identity else ''}", self._next_schedulable(), self._json(counts), time.time()),
        )

    def checkpoint(self) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM checkpoints WHERE checkpoint_id=1").fetchone()
        if row is None:
            return {"campaign_id": self.campaign_id, "attempt_id": self.attempt_id, "ledger_identity": self.ledger_identity, "last_durable_transition": None, "next_schedulable_task": self._next_schedulable(), "counts": self.counts()}
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
                (instance_id, request_id, logical_key, ordinal, state, execution_status, provider_start,
                 provider_request_started, provider_response_started, terminal_classification, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (instance_id, request_id, identity.key, ordinal, TaskState.RUNNING.value, "RUNNING", now, 1, 0, "RUNNING", now),
            )
            self._db.execute("UPDATE logical_tasks SET state=?, current_execution_instance=?, retry_count=?, retry_permitted=?, updated_at=? WHERE logical_key=?", (TaskState.RUNNING.value, instance_id, ordinal - 1, 0, now, identity.key))
            self._checkpoint("START", identity)
        return instance_id

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

    def campaign_score(self) -> dict[str, Any] | None:
        if not self.all_completed():
            return None
        refs = [row["measurement_ref"] for row in self._db.execute("SELECT measurement_ref FROM logical_tasks ORDER BY logical_key").fetchall()]
        if any(not ref for ref in refs):
            raise AssertionError("completed task is missing measurement export")
        return {"status": "AVAILABLE", "task_count": len(refs), "measurement_refs": refs}


class SimulatedInterruption(RuntimeError):
    pass


class ProductionCampaignRunner:
    """Provider-injected production controller used by V12's deterministic tests."""

    def __init__(self, ledger_path: str | Path, *, identities: list[TaskIdentity], evidence_dir: str | Path | None = None) -> None:
        self.identities = identities
        self.ledger = ProductionLedger(ledger_path, campaign_id="context-policy-multirepo-v12" if identities and identities[0].repository != "fixture" else "fixture", attempt_id="a001", expected_tasks=len(identities))
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
        if provider_request:
            self.provider_requests += 1
        instance = self.ledger.start_execution(identity, request_id=request_id, model="gpt-5.5", config_identity="frozen-v12")
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
