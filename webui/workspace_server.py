"""ARC Workspace — session-centric localhost UI and API.

The Workspace treats persistent workers as the primary UI object while keeping
tasks, events, candidate commits, and gates authoritative. External GitHub
review state is mounted as a non-authoritative integration surface.
"""

from __future__ import annotations

import asyncio
import webbrowser
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from application.session_app import SessionArcApplication
from webui.local_security import (
    LocalOriginGuardMiddleware,
    is_loopback_origin,
    require_loopback_bind,
)
from webui.review_routes import register_review_routes


class CreateTaskRequest(BaseModel):
    goal: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    risk: float = Field(default=0.5, ge=0.0, le=1.0)
    token_budget: int = Field(default=24000, ge=1000)


class MissionRequest(BaseModel):
    objective: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    risk: float = Field(default=0.5, ge=0.0, le=1.0)
    token_budget: int = Field(default=24000, ge=1000)
    max_tasks: int = Field(default=8, ge=1, le=32)


class OpenSessionRequest(BaseModel):
    agent: Optional[str] = None


class MessageRequest(BaseModel):
    content: str = Field(min_length=1)


class ReasonRequest(BaseModel):
    reason: str = "operator action"


class OrchestrateRequest(BaseModel):
    policy: Optional[str] = None
    max_parallel: Optional[int] = Field(default=None, ge=1, le=32)


class WorkspaceService:
    def __init__(self, repo: str | Path, project_id: Optional[str]) -> None:
        self.repo = Path(repo).resolve()
        self.project_id = project_id
        self.integration_lock = asyncio.Lock()
        self.session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def open(self) -> SessionArcApplication:
        return SessionArcApplication(self.repo, self.project_id)

    def snapshot(self) -> dict[str, Any]:
        with self.open() as arc:
            snap = arc.snapshot()
            doctors = {item.name: item for item in arc.doctor_agents()}
            sessions = arc.sessions.list()
            return {
                "project_id": snap["project_id"],
                "version": snap["version"],
                "project": snap["project"].model_dump(mode="json"),
                "budget": snap["budget"].model_dump(mode="json"),
                "leases": [lease.model_dump(mode="json") for lease in snap["leases"]],
                "tasks": [task.model_dump(mode="json") for task in snap["tasks"]],
                "sessions": [session.model_dump(mode="json") for session in sessions],
                "agents": [
                    {
                        **profile.model_dump(mode="json"),
                        "doctor": doctors[profile.name].__dict__,
                        "default": profile.name == arc.config.default_agent,
                    }
                    for profile in arc.list_agents()
                ],
                "memory_count": len(arc.memory.get_active_memories(arc.project_id)),
                "orchestration": snap["orchestration"],
            }


def create_workspace_app(
    *, repo: str | Path = ".", project_id: Optional[str] = None
) -> FastAPI:
    service = WorkspaceService(repo, project_id)
    static_dir = Path(__file__).parent / "static"
    app = FastAPI(
        title="ARC Workspace",
        version="0.8.1",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.arc_workspace = service
    app.add_middleware(LocalOriginGuardMiddleware)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(static_dir / "workspace.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            snap = service.snapshot()
            return {"ok": True, "project_id": snap["project_id"], "version": snap["version"]}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/snapshot")
    def snapshot() -> dict[str, Any]:
        try:
            return service.snapshot()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/events")
    def events(after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        try:
            with service.open() as arc:
                return [
                    event.model_dump(mode="json")
                    for event in arc.recent_events(after=after, limit=min(max(limit, 1), 500))
                ]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks", status_code=201)
    def create_task(payload: CreateTaskRequest) -> dict[str, Any]:
        try:
            with service.open() as arc:
                task = arc.create_task(
                    payload.goal,
                    dependencies=payload.dependencies,
                    files=payload.files,
                    acceptance=payload.acceptance,
                    risk=payload.risk,
                    token_budget=payload.token_budget,
                )
                return task.model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                item = arc.get_task(task_id)
                if not item:
                    raise HTTPException(status_code=404, detail="task not found")
                return {
                    "task": item.model_dump(mode="json"),
                    "events": [event.model_dump(mode="json") for event in arc.task_events(task_id)],
                    "session": (
                        arc.sessions.for_task(task_id).model_dump(mode="json")
                        if arc.sessions.for_task(task_id)
                        else None
                    ),
                }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/context")
    def task_context(task_id: str, agent: Optional[str] = None) -> dict[str, Any]:
        try:
            with service.open() as arc:
                session = arc.sessions.for_task(task_id)
                if session:
                    return arc.sessions.context_packet(session.session_id).model_dump(mode="json")
                return arc.compile_context(task_id, agent_name=agent).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/missions/plan", status_code=201)
    def plan(payload: MissionRequest) -> dict[str, Any]:
        try:
            with service.open() as arc:
                plan_obj, tasks = arc.plan_objective(
                    payload.objective,
                    files=payload.files,
                    acceptance=payload.acceptance,
                    risk=payload.risk,
                    token_budget=payload.token_budget,
                    max_tasks=payload.max_tasks,
                )
                return {
                    "objective": plan_obj.objective,
                    "planner": plan_obj.planner,
                    "tasks": [task.model_dump(mode="json") for task in tasks],
                }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/orchestration/run")
    async def orchestrate(payload: OrchestrateRequest) -> dict[str, Any]:
        if service.integration_lock.locked():
            raise HTTPException(status_code=409, detail="ARC integration is already active")
        async with service.integration_lock:
            arc = service.open()
            try:
                result = await arc.orchestrate(
                    policy=payload.policy,
                    max_parallel=payload.max_parallel,
                )
                return {
                    "run_id": result.run_id,
                    "accepted": result.accepted,
                    "rejected": result.rejected,
                    "failed": result.failed,
                    "deferred": sorted(set(result.deferred)),
                    "rounds": result.rounds,
                }
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            finally:
                arc.close()

    @app.get("/api/sessions")
    def sessions() -> list[dict[str, Any]]:
        try:
            with service.open() as arc:
                return [item.model_dump(mode="json") for item in arc.sessions.list()]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/sessions", status_code=201)
    def open_session(task_id: str, payload: OpenSessionRequest) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.sessions.create(task_id, agent_name=payload.agent).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}")
    def session_detail(session_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                session = arc.sessions.get(session_id)
                if not session:
                    raise HTTPException(status_code=404, detail="session not found")
                task = arc.get_task(session.task_id)
                return {
                    "session": session.model_dump(mode="json"),
                    "task": task.model_dump(mode="json") if task else None,
                    "files": arc.sessions.changed_files(session_id),
                    "diff": arc.sessions.diff(session_id),
                    "context": arc.sessions.context_packet(session_id).model_dump(mode="json"),
                    "events": [
                        event.model_dump(mode="json")
                        for event in arc.task_events(session.task_id, limit=120)
                    ],
                    "terminal_command": "arc attach " + session_id,
                    "review": arc.reviews.status(session_id).model_dump(mode="json"),
                }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/messages")
    async def send_message(session_id: str, payload: MessageRequest) -> dict[str, Any]:
        lock = service.session_locks[session_id]
        if lock.locked():
            raise HTTPException(status_code=409, detail="worker is already processing a turn")
        async with lock:
            arc = service.open()
            try:
                return (await arc.sessions.send(session_id, payload.content)).model_dump(mode="json")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            finally:
                arc.close()

    @app.post("/api/sessions/{session_id}/submit")
    async def submit_session(session_id: str) -> dict[str, Any]:
        if service.integration_lock.locked():
            raise HTTPException(status_code=409, detail="ARC integration is already active")
        lock = service.session_locks[session_id]
        if lock.locked():
            raise HTTPException(status_code=409, detail="worker is still processing a turn")
        async with service.integration_lock:
            arc = service.open()
            try:
                return (await arc.sessions.submit(session_id)).model_dump(mode="json")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            finally:
                arc.close()

    @app.post("/api/sessions/{session_id}/stop")
    def stop_session(session_id: str, payload: ReasonRequest) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.sessions.stop(session_id, reason=payload.reason).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/resume")
    def resume_session(session_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.sessions.resume(session_id).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/files")
    def session_files(session_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return {"files": arc.sessions.changed_files(session_id)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/diff")
    def session_diff(session_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return {"diff": arc.sessions.diff(session_id)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    register_review_routes(app, service)

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        if not is_loopback_origin(websocket.headers.get("origin")):
            await websocket.close(code=1008, reason="ARC local control plane rejected Origin")
            return
        await websocket.accept()
        cursor = 0
        raw = websocket.query_params.get("after")
        if raw:
            try:
                cursor = max(0, int(raw))
            except ValueError:
                cursor = 0
        try:
            arc = service.open()
            try:
                while True:
                    batch = arc.events.poll(cursor, limit=120)
                    if batch:
                        for event in batch:
                            cursor = event.id
                            await websocket.send_json(event.model_dump(mode="json"))
                    else:
                        await asyncio.sleep(0.35)
            finally:
                arc.close()
        except (WebSocketDisconnect, RuntimeError):
            return

    return app


def run_workspace(
    *,
    repo: str | Path = ".",
    project_id: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 8788,
    allow_remote: bool = False,
    open_browser: bool = False,
) -> None:
    # `allow_remote` remains in the pre-alpha API for compatibility, but it no
    # longer weakens the bind boundary. Authenticated remote mode is future work.
    require_loopback_bind(host, "ARC Workspace")
    app = create_workspace_app(repo=repo, project_id=project_id)
    url = f"http://{host}:{port}"
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="info")
