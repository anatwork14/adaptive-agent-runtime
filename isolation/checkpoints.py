"""Task execution checkpoints for rollback and side-effect recovery."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Checkpoint(BaseModel):
    checkpoint_id: str
    task_id: str
    project_id: str
    state_version: int
    context_id: Optional[str] = None
    git_ref: str = "HEAD"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CheckpointManager:
    """Manages checkpoints stored in the .arc directory."""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir).resolve() / ".arc" / "checkpoints"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(
        self,
        *,
        task_id: str,
        project_id: str,
        state_version: int,
        context_id: Optional[str] = None,
        git_ref: str = "HEAD",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Checkpoint:
        cp_id = f"cp_{task_id}_{state_version}_{int(datetime.now(timezone.utc).timestamp())}"
        checkpoint = Checkpoint(
            checkpoint_id=cp_id,
            task_id=task_id,
            project_id=project_id,
            state_version=state_version,
            context_id=context_id,
            git_ref=git_ref,
            metadata=metadata or {},
        )
        file_path = self.base_dir / f"{cp_id}.json"
        file_path.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
        return checkpoint

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        file_path = self.base_dir / f"{checkpoint_id}.json"
        if not file_path.exists():
            return None
        return Checkpoint.model_validate_json(file_path.read_text(encoding="utf-8"))

    def list_checkpoints_for_task(self, task_id: str) -> List[Checkpoint]:
        results = []
        for file in sorted(self.base_dir.glob(f"cp_{task_id}_*.json")):
            try:
                results.append(Checkpoint.model_validate_json(file.read_text(encoding="utf-8")))
            except Exception:
                continue
        return sorted(results, key=lambda c: c.state_version)
