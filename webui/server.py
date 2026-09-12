"""FastAPI control plane for ARC's localhost Web Mission Control."""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from application.app import ArcApplication
from application.config import AgentProfile
from application.version import arc_version
from webui.local_security import (
    LocalOriginGuardMiddleware,
    is_loopback_origin,
    require_loopback_bind,
)


class CreateTaskRequest(BaseModel):
    goal: str = Field(min_length=1)
    task_id: Optional[str] = None
    task_type: str = "code"
    required_capabilities: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    risk: float = Field(default=0.5, ge=0.0, le=1.0)
    token_budget: int = Field(default=24000, ge=1000)


class RunTaskRequest(BaseModel):
    agent: Optional[str] = None


class ReasonRequest(BaseModel):
    reason: str = "operator action"


class CreateAgentRequest(BaseModel):
    name: str = Field(min_length=1)
    provider: str
    model: Optional[str] = None
    role: str = "implementation"
    command_override: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=1, ge=1, le=32)
    cost_weight: float = Field(default=1.0, ge=0.0)
    quality_weight: float = Field(default=1.0, ge=0.0)
    make_default: bool = False


class MissionPlanRequest(BaseModel):
    objective: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    risk: float = Field(default=0.5, ge=0.0, le=1.0)
    token_budget: int = Field(default=24000, ge=1000)
    max_tasks: int = Field(default=8, ge=1, le=32)


class OrchestrateRequest(BaseModel):
    policy: Optional[str] = None
    max_parallel: Optional[int] = Field(default=None, ge=1, le=32)
    max_rounds: int = Field(default=100, ge=1, le=1000)


class MissionControlServer:
    """Serialize web-triggered runs while allowing one run to fan out internally."""

    def __init__(self, repo: str | Path, project_id: Optional[str]) -> None:
        self.repo = Path(repo).resolve()
        self.project_id = project_id
        self.execution_lock = asyncio.Lock()

    def open(self) -> ArcApplication:
        return ArcApplication(self.repo, self.project_id)

    @staticmethod
    def _task(task) -> dict[str, Any]:
        return task.model_dump(mode="json")

    def snapshot(self) -> dict[str, Any]:
        with self.open() as arc:
            snap = arc.snapshot()
            doctors = {item.name: item for item in arc.doctor_agents()}
            return {
                "project_id": snap["project_id"],
                "version": snap["version"],
                "project": snap["project"].model_dump(mode="json"),
                "budget": snap["budget"].model_dump(mode="json"),
                "leases": [lease.model_dump(mode="json") for lease in snap["leases"]],
                "tasks": [self._task(task) for task in snap["tasks"]],
                "agents": [
                    {
                        **profile.model_dump(mode="json"),
                        "doctor": doctors[profile.name].__dict__,
                        "default": profile.name == arc.config.default_agent,
                    }
                    for profile in arc.list_agents()
                ],
                "orchestration": snap["orchestration"],
                "memory_count": len(arc.memory.get_active_memories(arc.project_id)),
            }


def _orchestration_payload(result) -> dict[str, Any]:
    return {
        "run_id": result.run_id,
        "policy": result.policy,
        "rounds": result.rounds,
        "accepted": result.accepted,
        "rejected": result.rejected,
        "failed": result.failed,
        "deferred": sorted(set(result.deferred)),
        "successful": result.successful,
        "routed": [
            {
                "task_id": item.task_id,
                "agent_name": item.agent_name,
                "score": item.score,
                "policy": item.policy,
                "reasons": list(item.reasons),
            }
            for item in result.routed
        ],
    }


def create_web_app(
    *, repo: str | Path = ".", project_id: Optional[str] = None
) -> FastAPI:
    """Create a localhost-oriented FastAPI application around ArcApplication."""
    service = MissionControlServer(repo, project_id)
    static_dir = Path(__file__).parent / "static"
    app = FastAPI(
        title="ARC Mission Control",
        version=arc_version(),
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.arc_service = service
    app.add_middleware(LocalOriginGuardMiddleware)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(static_dir / "index.html")

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
    def events(after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        try:
            with service.open() as arc:
                return [
                    event.model_dump(mode="json")
                    for event in arc.recent_events(after=after, limit=min(max(limit, 1), 500))
                ]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                task = arc.get_task(task_id)
                if not task:
                    raise HTTPException(status_code=404, detail="task not found")
                return {
                    "task": task.model_dump(mode="json"),
                    "events": [event.model_dump(mode="json") for event in arc.task_events(task_id)],
                }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks", status_code=201)
    def create_task(payload: CreateTaskRequest) -> dict[str, Any]:
        try:
            with service.open() as arc:
                task = arc.create_task(
                    payload.goal,
                    task_id=payload.task_id,
                    task_type=payload.task_type,
                    required_capabilities=payload.required_capabilities,
                    dependencies=payload.dependencies,
                    files=payload.files,
                    symbols=payload.symbols,
                    acceptance=payload.acceptance,
                    risk=payload.risk,
                    token_budget=payload.token_budget,
                )
                return task.model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/route")
    def route_task(task_id: str, policy: Optional[str] = None) -> dict[str, Any]:
        try:
            with service.open() as arc:
                decision = arc.route_task(task_id, policy=policy)
                return {
                    "task_id": decision.task_id,
                    "agent_name": decision.agent_name,
                    "score": decision.score,
                    "policy": decision.policy,
                    "reasons": list(decision.reasons),
                }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/run")
    async def run_task(task_id: str, payload: RunTaskRequest) -> dict[str, Any]:
        if service.execution_lock.locked():
            raise HTTPException(status_code=409, detail="another ARC web execution is active")
        async with service.execution_lock:
            arc = service.open()
            try:
                result = await arc.run_task(task_id, agent_name=payload.agent)
                return result.model_dump(mode="json")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            finally:
                arc.close()

    @app.post("/api/missions/plan", status_code=201)
    def plan_mission(payload: MissionPlanRequest) -> dict[str, Any]:
        try:
            with service.open() as arc:
                plan, tasks = arc.plan_objective(
                    payload.objective,
                    files=payload.files,
                    acceptance=payload.acceptance,
                    risk=payload.risk,
                    token_budget=payload.token_budget,
                    max_tasks=payload.max_tasks,
                )
                return {
                    "objective": plan.objective,
                    "planner": plan.planner,
                    "tasks": [task.model_dump(mode="json") for task in tasks],
                }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/orchestration/run")
    async def orchestrate(payload: OrchestrateRequest) -> dict[str, Any]:
        if service.execution_lock.locked():
            raise HTTPException(status_code=409, detail="another ARC web execution is active")
        async with service.execution_lock:
            arc = service.open()
            try:
                result = await arc.orchestrate(
                    policy=payload.policy,
                    max_parallel=payload.max_parallel,
                    max_rounds=payload.max_rounds,
                )
                return _orchestration_payload(result)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            finally:
                arc.close()

    @app.post("/api/tasks/{task_id}/retry")
    def retry_task(task_id: str, payload: ReasonRequest) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.retry_task(task_id, reason=payload.reason).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str, payload: ReasonRequest) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.cancel_task(task_id, reason=payload.reason).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tasks/{task_id}/context")
    def task_context(task_id: str, agent: Optional[str] = None) -> dict[str, Any]:
        try:
            with service.open() as arc:
                packet = arc.compile_context(task_id, agent_name=agent)
                return packet.model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agents", status_code=201)
    def create_agent(payload: CreateAgentRequest) -> dict[str, Any]:
        try:
            with service.open() as arc:
                profile = AgentProfile(
                    name=payload.name,
                    provider=payload.provider,
                    model=payload.model,
                    role=payload.role,
                    command_override=payload.command_override,
                    capabilities=payload.capabilities,
                    max_concurrency=payload.max_concurrency,
                    cost_weight=payload.cost_weight,
                    quality_weight=payload.quality_weight,
                )
                arc.add_agent(profile, make_default=payload.make_default)
                return profile.model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/agents/doctor")
    def doctor_agents() -> list[dict[str, Any]]:
        try:
            with service.open() as arc:
                return [item.__dict__ for item in arc.doctor_agents()]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        if not is_loopback_origin(websocket.headers.get("origin")):
            await websocket.close(code=1008, reason="ARC local control plane rejected Origin")
            return
        await websocket.accept()
        cursor = 0
        try:
            raw = websocket.query_params.get("after")
            if raw:
                cursor = max(0, int(raw))
            arc = service.open()
            try:
                while True:
                    batch = arc.events.poll(cursor, limit=100)
                    if batch:
                        for event in batch:
                            cursor = event.id
                            await websocket.send_json(event.model_dump(mode="json"))
                    else:
                        await asyncio.sleep(0.4)
            finally:
                arc.close()
        except (WebSocketDisconnect, RuntimeError):
            return

    return app


def run_web(
    *,
    repo: str | Path = ".",
    project_id: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 8787,
    allow_remote: bool = False,
    open_browser: bool = False,
) -> None:
    """Run Mission Control as an unauthenticated loopback-only control plane."""
    # Keep `allow_remote` in the pre-alpha call surface for compatibility, but
    # never let it weaken the security boundary before authenticated remote mode.
    require_loopback_bind(host, "ARC Web Mission Control")

    app = create_web_app(repo=repo, project_id=project_id)
    url = f"http://{host}:{port}"
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="info")
