"""Contract tests for ARC's Agent Bridge P6 integration client."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from integrations.agent_bridge import (
    AgentBridgeClient,
    BridgeIntegrationError,
)
from state.events import EventStore


RUN_PROJECTION = {
    "schemaVersion": 1,
    "kind": "collaboration_dag_run",
    "id": "rrun_arc_1",
    "sessionId": "ses_bridge_1",
    "status": "running",
    "failurePolicy": "fail_fast",
    "maxParallelTurns": 2,
    "participantCount": 2,
    "nodeCount": 2,
    "createdAt": "2026-09-19T02:00:00.000Z",
    "startedAt": "2026-09-19T02:00:00.000Z",
    "correlation": {
        "arcProjectId": "arc-project",
        "arcTaskId": "T001",
        "arcSessionId": "S_001",
    },
    "nodes": [
        {
            "id": "architecture",
            "participantId": "part_arch",
            "roleId": "architect",
            "status": "completed",
            "declarationIndex": 0,
            "attempt": 1,
            "retryLimit": 1,
            "completedAt": "2026-09-19T02:00:01.000Z",
        },
        {
            "id": "review",
            "participantId": "part_review",
            "roleId": "reviewer",
            "status": "ready",
            "declarationIndex": 1,
            "attempt": 0,
            "retryLimit": 1,
        },
    ],
}

COMPLETED_PROJECTION = {
    **RUN_PROJECTION,
    "status": "completed",
    "completedAt": "2026-09-19T02:00:02.000Z",
    "nodes": [
        RUN_PROJECTION["nodes"][0],
        {
            **RUN_PROJECTION["nodes"][1],
            "status": "completed",
            "attempt": 1,
            "completedAt": "2026-09-19T02:00:02.000Z",
        },
    ],
}


class _BridgeFixtureHandler(BaseHTTPRequestHandler):
    server: "_BridgeFixtureServer"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == "Bearer runtime-secret"

    def _json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._send_json(
            401,
            {
                "error": {
                    "code": "authentication_required",
                    "message": "token required",
                    "retryable": False,
                }
            },
        )
        return False

    def do_GET(self) -> None:  # noqa: N802
        if not self._require_auth():
            return

        if self.path == "/bridge/v1/integrations/capabilities":
            self._send_json(
                200,
                {
                    "schemaVersion": 1,
                    "service": "agent-chatgpt-bridge",
                    "authority": {
                        "collaboration": "bridge",
                        "execution": "external",
                        "coordination": "external",
                    },
                    "capabilities": {
                        "dagRunProjection": True,
                        "dagRunCancellation": True,
                        "integrationEvents": True,
                        "dagRunSubmission": True,
                    },
                },
            )
            return

        if self.path == "/bridge/v1/integrations/dag-runs/rrun_arc_1":
            self._send_json(200, COMPLETED_PROJECTION)
            return

        if self.path.startswith("/bridge/v1/integrations/events?"):
            self.server.last_event_path = self.path
            first = {
                "schemaVersion": 1,
                "cursor": 11,
                "type": "bridge.integration.node.completed",
                "runId": "rrun_arc_1",
                "sessionId": "ses_bridge_1",
                "occurredAt": "2026-09-19T02:00:01.000Z",
                "correlation": {
                    "arcProjectId": "arc-project",
                    "arcTaskId": "T001",
                },
                "data": {
                    "nodeId": "architecture",
                    "participantId": "part_arch",
                    "roleId": "architect",
                    "attempt": 1,
                    "decisionType": "message",
                    "durationMs": 10,
                },
            }
            second = {
                "schemaVersion": 1,
                "cursor": 12,
                "type": "bridge.integration.dag_run.completed",
                "runId": "rrun_arc_1",
                "sessionId": "ses_bridge_1",
                "occurredAt": "2026-09-19T02:00:02.000Z",
                "correlation": {
                    "arcProjectId": "arc-project",
                    "arcTaskId": "T001",
                },
                "data": {
                    "nodeCount": 2,
                    "totalAttempts": 2,
                },
            }
            body = (
                f"id: 11\nevent: {first['type']}\ndata: {json.dumps(first)}\n\n"
                f"id: 12\nevent: {second['type']}\ndata: {json.dumps(second)}\n\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._send_json(
            404,
            {
                "error": {
                    "code": "run_not_found",
                    "message": "not found",
                    "retryable": False,
                }
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_auth():
            return

        if self.path == "/bridge/v1/integrations/dag-runs":
            key = self.headers.get("Idempotency-Key") or ""
            body = self._json_body()
            self.server.submission_requests.append((key, body))
            canonical = json.dumps(body, sort_keys=True)
            existing = self.server.idempotency.get(key)
            if existing and existing != canonical:
                self._send_json(
                    409,
                    {
                        "error": {
                            "code": "idempotency_conflict",
                            "message": "different request body",
                            "retryable": False,
                        }
                    },
                )
                return
            replayed = existing is not None
            self.server.idempotency[key] = canonical
            self._send_json(
                201,
                RUN_PROJECTION,
                headers={"Idempotency-Replayed": "true"} if replayed else None,
            )
            return

        if self.path == "/bridge/v1/integrations/dag-runs/rrun_arc_1/cancel":
            self.server.cancelled_run_ids.append("rrun_arc_1")
            self._json_body()
            self._send_json(
                200,
                {
                    "success": True,
                    "cancelled": True,
                    "run_id": "rrun_arc_1",
                },
            )
            return

        self._send_json(
            404,
            {
                "error": {
                    "code": "run_not_found",
                    "message": "not found",
                    "retryable": False,
                }
            },
        )


class _BridgeFixtureServer(ThreadingHTTPServer):
    submission_requests: list[tuple[str, dict[str, Any]]]
    idempotency: dict[str, str]
    cancelled_run_ids: list[str]
    last_event_path: str

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _BridgeFixtureHandler)
        self.submission_requests = []
        self.idempotency = {}
        self.cancelled_run_ids = []
        self.last_event_path = ""


@pytest.fixture
def bridge_server():
    server = _BridgeFixtureServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _client(server: _BridgeFixtureServer, *, token: str = "runtime-secret") -> AgentBridgeClient:
    host, port = server.server_address
    return AgentBridgeClient(
        base_url=f"http://{host}:{port}/bridge/v1",
        token=token,
        timeout_seconds=2,
    )


def _submission() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "sessionId": "ses_bridge_1",
        "objective": "Review the proposed ARC change",
        "participants": [
            {
                "roleId": "architect",
                "adapterType": "acp:claude",
                "permissionMode": "deny",
            },
            {
                "roleId": "reviewer",
                "adapterType": "acp:antigravity",
                "permissionMode": "allow_readonly",
            },
        ],
        "graph": {
            "version": 1,
            "nodes": [
                {
                    "id": "architecture",
                    "roleId": "architect",
                    "instruction": "Produce architecture evidence.",
                    "dependsOn": [],
                },
                {
                    "id": "review",
                    "roleId": "reviewer",
                    "instruction": "Review architecture evidence.",
                    "dependsOn": ["architecture"],
                    "terminal": True,
                },
            ],
        },
        "correlation": {
            "arcProjectId": "arc-project",
            "arcTaskId": "T001",
            "arcSessionId": "S_001",
        },
    }


def test_capabilities_and_authority_are_versioned(bridge_server: _BridgeFixtureServer) -> None:
    capabilities = _client(bridge_server).capabilities()

    assert capabilities.schema_version == 1
    assert capabilities.authority.collaboration == "bridge"
    assert capabilities.authority.execution == "external"
    assert capabilities.capabilities.dag_run_submission
    assert capabilities.capabilities.integration_events


def test_submission_is_explicitly_idempotent_and_returns_minimized_projection(
    bridge_server: _BridgeFixtureServer,
) -> None:
    client = _client(bridge_server)
    submission = _submission()

    first = client.submit_dag(submission, idempotency_key="arc:T001:bridge-collab")
    second = client.submit_dag(submission, idempotency_key="arc:T001:bridge-collab")

    assert first.id == second.id == "rrun_arc_1"
    assert first.correlation and first.correlation.arc_task_id == "T001"
    assert len(bridge_server.submission_requests) == 2

    serialized = first.model_dump_json(by_alias=True)
    assert "Review the proposed ARC change" not in serialized
    assert "Produce architecture evidence." not in serialized
    assert "Review architecture evidence." not in serialized


def test_idempotency_conflict_and_auth_failures_are_normalized(
    bridge_server: _BridgeFixtureServer,
) -> None:
    client = _client(bridge_server)
    client.submit_dag(_submission(), idempotency_key="arc:T001:bridge-collab")

    changed = _submission()
    changed["objective"] = "Different objective"
    with pytest.raises(BridgeIntegrationError) as conflict:
        client.submit_dag(changed, idempotency_key="arc:T001:bridge-collab")
    assert conflict.value.code == "idempotency_conflict"
    assert conflict.value.status_code == 409
    assert not conflict.value.retryable

    with pytest.raises(BridgeIntegrationError) as auth:
        _client(bridge_server, token="wrong").capabilities()
    assert auth.value.code == "authentication_required"
    assert auth.value.status_code == 401


def test_get_cancel_and_event_replay_preserve_exact_bridge_identity(
    bridge_server: _BridgeFixtureServer,
) -> None:
    client = _client(bridge_server)

    run = client.get_dag_run("rrun_arc_1")
    assert run.status == "completed"
    assert run.id == "rrun_arc_1"

    assert client.cancel_dag_run("rrun_arc_1")
    assert bridge_server.cancelled_run_ids == ["rrun_arc_1"]

    events = client.replay_events(after_id=10, run_id="rrun_arc_1")
    assert [event.cursor for event in events] == [11, 12]
    assert events[-1].type == "bridge.integration.dag_run.completed"
    assert events[-1].run_id == "rrun_arc_1"
    assert "once=true" in bridge_server.last_event_path
    assert "after_id=10" in bridge_server.last_event_path
    assert "run_id=rrun_arc_1" in bridge_server.last_event_path


def test_client_fails_closed_on_schema_version_drift(
    bridge_server: _BridgeFixtureServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RUN_PROJECTION["schemaVersion"]
    RUN_PROJECTION["schemaVersion"] = 2
    try:
        with pytest.raises(Exception):
            _client(bridge_server).submit_dag(
                _submission(),
                idempotency_key="arc:T001:schema-drift",
            )
    finally:
        RUN_PROJECTION["schemaVersion"] = original


def test_invalid_idempotency_key_is_rejected_before_network(
    bridge_server: _BridgeFixtureServer,
) -> None:
    with pytest.raises(ValueError):
        _client(bridge_server).submit_dag(
            _submission(),
            idempotency_key="contains spaces",
        )
    assert bridge_server.submission_requests == []


def test_completed_bridge_run_does_not_mutate_arc_authoritative_state(
    bridge_server: _BridgeFixtureServer,
    tmp_path,
) -> None:
    store = EventStore(tmp_path / "bridge_authority.db")
    store.append(
        actor="operator",
        kind="task.created",
        project_id="arc-project",
        task_id="T001",
        payload={"goal": "authoritative ARC task"},
    )
    version_before = store.current_version("arc-project")

    run = _client(bridge_server).get_dag_run("rrun_arc_1")

    assert run.status == "completed"
    assert store.current_version("arc-project") == version_before
    assert all(
        event.kind != "gate.accepted"
        for event in store.read_all(project_id="arc-project")
    )
    store.close()
