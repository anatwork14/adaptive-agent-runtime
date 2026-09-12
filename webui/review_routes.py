"""FastAPI routes for ARC's external GitHub review loop."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class PublishReviewRequest(BaseModel):
    base: str = Field(default="main", min_length=1)
    remote: str = Field(default="origin", min_length=1)
    title: str | None = None


class SyncReviewRequest(BaseModel):
    apply: bool = False


class SuperviseReviewRequest(BaseModel):
    apply: bool = False


def register_review_routes(app: FastAPI, service: Any) -> None:
    """Attach review endpoints to an ARC Workspace app.

    `service` is intentionally duck-typed to avoid coupling this module to the
    workspace server implementation. It must expose `open()` and `session_locks`.
    """

    @app.get("/api/reviews/doctor")
    def review_doctor() -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.reviews.doctor()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/reviews/{session_id}")
    def review_status(session_id: str) -> dict[str, Any]:
        try:
            with service.open() as arc:
                return arc.reviews.status(session_id).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reviews/{session_id}/publish")
    async def publish_review(session_id: str, payload: PublishReviewRequest) -> dict[str, Any]:
        lock = service.session_locks[session_id]
        if lock.locked():
            raise HTTPException(status_code=409, detail="worker is already processing an action")
        async with lock:
            try:
                with service.open() as arc:
                    return arc.reviews.publish(
                        session_id,
                        base=payload.base,
                        remote=payload.remote,
                        title=payload.title,
                    ).model_dump(mode="json")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reviews/{session_id}/sync")
    async def sync_review(session_id: str, payload: SyncReviewRequest) -> dict[str, Any]:
        lock = service.session_locks[session_id]
        if lock.locked():
            raise HTTPException(status_code=409, detail="worker is already processing an action")
        async with lock:
            arc = service.open()
            try:
                result = await arc.reviews.sync(session_id, auto_apply=payload.apply)
                return result.model_dump(mode="json")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            finally:
                arc.close()

    @app.post("/api/reviews/{session_id}/apply")
    async def apply_review(session_id: str) -> dict[str, Any]:
        lock = service.session_locks[session_id]
        if lock.locked():
            raise HTTPException(status_code=409, detail="worker is already processing an action")
        async with lock:
            arc = service.open()
            try:
                applied = await arc.reviews.apply_latest(session_id)
                return {
                    "applied": applied,
                    "review": arc.reviews.status(session_id).model_dump(mode="json"),
                }
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            finally:
                arc.close()

    @app.post("/api/reviews/supervise")
    async def supervise_reviews(payload: SuperviseReviewRequest) -> list[dict[str, Any]]:
        arc = service.open()
        try:
            rows = await arc.reviews.supervise_once(auto_apply=payload.apply)
            return [row.model_dump(mode="json") for row in rows]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            arc.close()
