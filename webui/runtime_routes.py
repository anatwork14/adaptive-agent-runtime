"""FastAPI routes for persistent worker terminals and localhost previews."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class PreviewStartRequest(BaseModel):
    command: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    host: str = "127.0.0.1"


def register_runtime_routes(app: FastAPI, service: Any) -> None:
    @app.get("/api/runtime/doctor")
    def runtime_doctor() -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.worker_runtime.doctor()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/runtime")
    def runtime_status(session_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return {
                    "terminal": arc.worker_runtime.status(session_id, "terminal").model_dump(mode="json"),
                    "preview": arc.worker_runtime.status(session_id, "preview").model_dump(mode="json"),
                }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/terminal/start")
    def terminal_start(session_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                doctor = arc.worker_runtime.doctor()
                if doctor["status"] != "READY":
                    raise RuntimeError(
                        f"Persistent runtime is {doctor['status']}: {doctor['detail']}"
                    )
                return arc.worker_runtime.start_terminal(session_id).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/terminal/stop")
    def terminal_stop(session_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.worker_runtime.stop_terminal(session_id).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/preview/start")
    def preview_start(session_id: str, payload: PreviewStartRequest) -> dict[str, Any]:
        lock = service.session_locks[session_id]
        if lock.locked():
            raise HTTPException(status_code=409, detail="worker is already processing an action")
        try:
            with service.open() as arc:
                doctor = arc.worker_runtime.doctor()
                if doctor["status"] != "READY":
                    raise RuntimeError(
                        f"Persistent runtime is {doctor['status']}: {doctor['detail']}"
                    )
                return arc.worker_runtime.start_preview(
                    session_id,
                    command_template=payload.command,
                    port=payload.port,
                    host=payload.host,
                ).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/preview/stop")
    def preview_stop(session_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.worker_runtime.stop_preview(session_id).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
