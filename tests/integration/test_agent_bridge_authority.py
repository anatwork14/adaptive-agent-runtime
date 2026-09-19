"""Cross-system authority smoke for ARC <-> Agent Bridge P6."""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from application.app import ArcApplication
from application.bridge_collaboration import BridgeCollaborationObserver
from integrations.agent_bridge import AgentBridgeClient
from state.models import TaskStatus


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "arc@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ARC Test"], check=True)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
    return repo


def _projection(status: str = "completed") -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "kind": "collaboration_dag_run",
        "id": "rrun_arc_authority",
        "sessionId": "ses_bridge_authority",
        "status": status,
        "failurePolicy": "fail_fast",
        "maxParallelTurns": 2,
        "participantCount": 2,
        "nodeCount": 2,
        "createdAt": "2026-09-19T03:00:00.000Z",
        "startedAt": "2026-09-19T03:00:00.000Z",
        "completedAt": "2026-09-19T03:00:02.000Z" if status == "completed" else None,
        "correlation": {
            "arcProjectId": "demo",
            "arcTaskId": "T001",
            "arcSessionId": "S_authority",
        },
        "nodes": [
            {
                "id": "architect",
                "participantId": "part_arch",
                "roleId": "architect",
                "status": "completed",
                "declarationIndex": 0,
                "attempt": 1,
                "retryLimit": 1,
                "completedAt": "2026-09-19T03:00:01.000Z",
            },
            {
                "id": "review",
                "participantId": "part_review",
                "roleId": "reviewer",
                "status": status,
                "declarationIndex": 1,
                "attempt": 1,
                "retryLimit": 1,
                "completedAt": "2026-09-19T03:00:02.000Z",
            },
        ],
    }


class _BridgeHandler(BaseHTTPRequestHandler):
    server: "_BridgeServer"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _auth(self) -> bool:
        return self.headers.get("Authorization") == "Bearer runtime-secret"

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth():
            self._json(
                401,
                {
                    "error": {
                        "code": "authentication_required",
                        "message": "token required",
                        "retryable": False,
                    }
                },
            )
            return

        if self.path == "/bridge/v1/integrations/dag-runs":
            assert self.headers.get("Idempotency-Key") == "arc:demo:T001:bridge"
            length = int(self.headers.get("Content-Length") or "0")
            self.server.submission = json.loads(self.rfile.read(length).decode("utf-8"))
            self._json(201, _projection())
            return

        if self.path == "/bridge/v1/integrations/dag-runs/rrun_arc_authority/cancel":
            self._json(
                200,
                {
                    "success": True,
                    "cancelled": True,
                    "run_id": "rrun_arc_authority",
                },
            )
            return

        self._json(
            404,
            {"error": {"code": "run_not_found", "message": "not found", "retryable": False}},
        )

    def do_GET(self) -> None:  # noqa: N802
        if not self._auth():
            self._json(
                401,
                {
                    "error": {
                        "code": "authentication_required",
                        "message": "token required",
                        "retryable": False,
                    }
                },
            )
            return

        if self.path == "/bridge/v1/integrations/dag-runs/rrun_arc_authority":
            self._json(200, _projection())
            return

        if self.path.startswith("/bridge/v1/integrations/events?"):
            event = {
                "schemaVersion": 1,
                "cursor": 7,
                "type": "bridge.integration.dag_run.completed",
                "runId": "rrun_arc_authority",
                "sessionId": "ses_bridge_authority",
                "occurredAt": "2026-09-19T03:00:02.000Z",
                "correlation": {
                    "arcProjectId": "demo",
                    "arcTaskId": "T001",
                    "arcSessionId": "S_authority",
                },
                "data": {
                    "nodeCount": 2,
                    "totalAttempts": 2,
                },
            }
            body = (
                f"id: 7\n"
                f"event: {event['type']}\n"
                f"data: {json.dumps(event)}\n\n"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._json(
            404,
            {"error": {"code": "run_not_found", "message": "not found", "retryable": False}},
        )


class _BridgeServer(ThreadingHTTPServer):
    submission: dict[str, Any] | None = None


def test_bridge_completion_is_observational_and_cannot_bypass_integration_gate(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    server = _BridgeServer(("127.0.0.1", 0), _BridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with ArcApplication(repo, "demo") as arc:
            arc.initialize()
            task = arc.create_task(
                "Use external collaboration as planning evidence",
                task_id="T001",
                acceptance=["Only ARC IntegrationGate may complete this task"],
            )
            assert task.status == TaskStatus.READY

            client = AgentBridgeClient(
                base_url=f"http://127.0.0.1:{server.server_port}/bridge/v1",
                token="runtime-secret",
            )
            observer = BridgeCollaborationObserver(
                client=client,
                event_store=arc.event_store,
                project_id=arc.project_id,
            )

            submission = {
                "schemaVersion": 1,
                "sessionId": "ses_bridge_authority",
                "objective": "SECRET COLLABORATION OBJECTIVE",
                "participants": [
                    {
                        "roleId": "architect",
                        "adapterType": "acp:claude",
                        "permissionMode": "deny",
                    },
                    {
                        "roleId": "reviewer",
                        "adapterType": "acp:claude",
                        "permissionMode": "deny",
                    },
                ],
                "graph": {
                    "version": 1,
                    "nodes": [
                        {
                            "id": "architect",
                            "roleId": "architect",
                            "instruction": "SECRET ARCHITECT INSTRUCTION",
                            "dependsOn": [],
                        },
                        {
                            "id": "review",
                            "roleId": "reviewer",
                            "instruction": "SECRET REVIEW INSTRUCTION",
                            "dependsOn": ["architect"],
                            "terminal": True,
                        },
                    ],
                },
                "correlation": {
                    "arcProjectId": "demo",
                    "arcTaskId": "T001",
                    "arcSessionId": "S_authority",
                },
            }

            observed = observer.submit_for_task(
                task_id="T001",
                submission=submission,
                idempotency_key="arc:demo:T001:bridge",
            )
            assert observed.status == "completed"
            assert observed.bridge_run_id == "rrun_arc_authority"

            replayed = observer.replay(
                task_id="T001",
                bridge_run_id=observed.bridge_run_id,
                after_id=0,
            )
            assert [event.cursor for event in replayed] == [7]

            refreshed = observer.refresh(
                task_id="T001",
                bridge_run_id=observed.bridge_run_id,
            )
            assert refreshed.status == "completed"

            assert observer.cancel(
                task_id="T001",
                bridge_run_id=observed.bridge_run_id,
            )

            # Bridge completion/cancellation is operational evidence only.
            current = arc.get_task("T001")
            assert current is not None
            assert current.status == TaskStatus.READY

            events = arc.task_events("T001")
            kinds = [event.kind for event in events]
            assert "bridge.collaboration_submitted" in kinds
            assert "bridge.collaboration_event_observed" in kinds
            assert "bridge.collaboration_observed" in kinds
            assert "bridge.collaboration_cancel_requested" in kinds
            assert "gate.accepted" not in kinds
            assert "task.completed" not in kinds

            serialized = json.dumps(
                [
                    {
                        "kind": event.kind,
                        "payload": event.payload,
                    }
                    for event in events
                ],
                sort_keys=True,
            )
            for forbidden in [
                "runtime-secret",
                "SECRET COLLABORATION OBJECTIVE",
                "SECRET ARCHITECT INSTRUCTION",
                "SECRET REVIEW INSTRUCTION",
            ]:
                assert forbidden not in serialized

            assert server.submission is not None
            assert server.submission["correlation"]["arcProjectId"] == "demo"
            assert server.submission["correlation"]["arcTaskId"] == "T001"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
