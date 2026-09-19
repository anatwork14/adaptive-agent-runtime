"""Versioned Agent Bridge P6 integration client.

This module is deliberately an external-system adapter, not an ARC execution
adapter. Bridge owns collaboration runs; ARC continues to own task state,
worktrees, Git candidates, and IntegrationGate acceptance.

The bearer token is runtime-only client state and is never serialized into an
ARC model, config, or event by this module.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BridgeIntegrationError(RuntimeError):
    """Safe normalized failure returned by the Agent Bridge integration."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class BridgeAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collaboration: Literal["bridge"]
    execution: Literal["external"]
    coordination: Literal["external"]


class BridgeCapabilities(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    dag_run_projection: bool = Field(alias="dagRunProjection")
    dag_run_cancellation: bool = Field(alias="dagRunCancellation")
    integration_events: bool = Field(alias="integrationEvents")
    dag_run_submission: bool = Field(alias="dagRunSubmission")


class BridgeIntegrationCapabilities(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal[1] = Field(alias="schemaVersion")
    service: Literal["agent-chatgpt-bridge"]
    authority: BridgeAuthority
    capabilities: BridgeCapabilities


class BridgeCorrelation(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    arc_project_id: str | None = Field(default=None, alias="arcProjectId")
    arc_task_id: str | None = Field(default=None, alias="arcTaskId")
    arc_session_id: str | None = Field(default=None, alias="arcSessionId")
    company_workflow_id: str | None = Field(default=None, alias="companyWorkflowId")
    company_step_id: str | None = Field(default=None, alias="companyStepId")
    company_run_id: str | None = Field(default=None, alias="companyRunId")
    external_trace_id: str | None = Field(default=None, alias="externalTraceId")


class BridgeNodeError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    retryable: bool


class BridgeDagNodeProjection(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    participant_id: str = Field(alias="participantId")
    role_id: str = Field(alias="roleId")
    status: str
    declaration_index: int = Field(alias="declarationIndex")
    attempt: int
    retry_limit: int = Field(alias="retryLimit")
    started_at: str | None = Field(default=None, alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    error: BridgeNodeError | None = None


class BridgeDagRunProjection(BaseModel):
    """Minimized Bridge-owned collaboration state.

    Deliberately absent: objective, node instructions, transcript/model output,
    final summary, commands, cwd, credentials, and provider error text.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal[1] = Field(alias="schemaVersion")
    kind: Literal["collaboration_dag_run"]
    id: str
    session_id: str = Field(alias="sessionId")
    status: str
    failure_policy: Literal["fail_fast", "skip_dependents"] = Field(alias="failurePolicy")
    max_parallel_turns: int = Field(alias="maxParallelTurns")
    participant_count: int = Field(alias="participantCount")
    node_count: int = Field(alias="nodeCount")
    created_at: str = Field(alias="createdAt")
    started_at: str | None = Field(default=None, alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    correlation: BridgeCorrelation | None = None
    nodes: list[BridgeDagNodeProjection] = Field(default_factory=list)


class BridgeIntegrationEvent(BaseModel):
    """Replayable minimized Bridge lifecycle event."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal[1] = Field(alias="schemaVersion")
    cursor: int
    type: str
    run_id: str = Field(alias="runId")
    session_id: str = Field(alias="sessionId")
    occurred_at: str = Field(alias="occurredAt")
    correlation: BridgeCorrelation | None = None
    data: dict[str, str | int | bool] = Field(default_factory=dict)


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


class AgentBridgeClient:
    """Thin authenticated HTTP client for Agent Bridge P6 integration routes."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        if not normalized_url:
            raise ValueError("base_url is required")
        if not token:
            raise ValueError("token is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.base_url = normalized_url
        self._token = token
        self.timeout_seconds = timeout_seconds

    def capabilities(self) -> BridgeIntegrationCapabilities:
        payload, _headers = self._request_json("GET", "/integrations/capabilities")
        return BridgeIntegrationCapabilities.model_validate(payload)

    def submit_dag(
        self,
        submission: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> BridgeDagRunProjection:
        if not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise ValueError(
                "idempotency_key must be 1-200 characters using "
                "letters, digits, dot, underscore, colon, or hyphen"
            )
        payload, _headers = self._request_json(
            "POST",
            "/integrations/dag-runs",
            body=submission,
            headers={"Idempotency-Key": idempotency_key},
        )
        return BridgeDagRunProjection.model_validate(payload)

    def get_dag_run(self, run_id: str) -> BridgeDagRunProjection:
        payload, _headers = self._request_json(
            "GET",
            f"/integrations/dag-runs/{urllib.parse.quote(run_id, safe='')}",
        )
        return BridgeDagRunProjection.model_validate(payload)

    def cancel_dag_run(self, run_id: str) -> bool:
        payload, _headers = self._request_json(
            "POST",
            f"/integrations/dag-runs/{urllib.parse.quote(run_id, safe='')}/cancel",
            body={},
        )
        if not isinstance(payload, dict) or payload.get("run_id") != run_id:
            raise BridgeIntegrationError(
                "invalid_response",
                "Bridge cancellation response did not match the requested run",
            )
        return bool(payload.get("cancelled"))

    def replay_events(
        self,
        *,
        after_id: int = 0,
        run_id: str | None = None,
    ) -> list[BridgeIntegrationEvent]:
        if after_id < 0:
            raise ValueError("after_id must be non-negative")
        query: dict[str, str] = {
            "once": "true",
            "after_id": str(after_id),
        }
        if run_id:
            query["run_id"] = run_id
        text = self._request_text(
            "GET",
            f"/integrations/events?{urllib.parse.urlencode(query)}",
        )
        return self._parse_sse(text)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        if extra:
            headers.update(extra)
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        encoded: bytes | None = None
        request_headers = self._headers(headers)
        if body is not None:
            encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=encoded,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                response_headers = dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except urllib.error.URLError as exc:
            raise BridgeIntegrationError(
                "transport_error",
                f"Agent Bridge request failed: {exc.reason}",
                retryable=True,
            ) from exc

        try:
            return json.loads(raw.decode("utf-8")), response_headers
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeIntegrationError(
                "invalid_response",
                "Agent Bridge returned invalid JSON",
            ) from exc

    def _request_text(self, method: str, path: str) -> str:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers=self._headers({"Accept": "text/event-stream"}),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except urllib.error.URLError as exc:
            raise BridgeIntegrationError(
                "transport_error",
                f"Agent Bridge event request failed: {exc.reason}",
                retryable=True,
            ) from exc
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BridgeIntegrationError(
                "invalid_response",
                "Agent Bridge returned non-UTF-8 SSE",
            ) from exc

    @staticmethod
    def _raise_http_error(exc: urllib.error.HTTPError) -> None:
        raw = exc.read()
        code = "http_error"
        message = f"Agent Bridge returned HTTP {exc.code}"
        retryable = exc.code >= 500
        try:
            payload = json.loads(raw.decode("utf-8"))
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                code = str(error.get("code") or code)
                message = str(error.get("message") or message)
                retryable = bool(error.get("retryable", retryable))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        raise BridgeIntegrationError(
            code,
            message,
            retryable=retryable,
            status_code=exc.code,
        ) from exc

    @staticmethod
    def _parse_sse(payload: str) -> list[BridgeIntegrationEvent]:
        events: list[BridgeIntegrationEvent] = []
        event_id: int | None = None
        data_lines: list[str] = []

        def flush() -> None:
            nonlocal event_id, data_lines
            if not data_lines:
                event_id = None
                return
            try:
                raw = json.loads("\n".join(data_lines))
            except json.JSONDecodeError as exc:
                raise BridgeIntegrationError(
                    "invalid_response",
                    "Agent Bridge returned invalid SSE JSON",
                ) from exc
            event = BridgeIntegrationEvent.model_validate(raw)
            if event_id is not None and event.cursor != event_id:
                raise BridgeIntegrationError(
                    "invalid_response",
                    "Agent Bridge SSE id did not match payload cursor",
                )
            events.append(event)
            event_id = None
            data_lines = []

        for line in payload.splitlines():
            if line == "":
                flush()
                continue
            if line.startswith(":"):
                continue
            if line.startswith("id:"):
                value = line[3:].strip()
                try:
                    event_id = int(value)
                except ValueError as exc:
                    raise BridgeIntegrationError(
                        "invalid_response",
                        "Agent Bridge SSE id is not an integer cursor",
                    ) from exc
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        flush()
        return events
