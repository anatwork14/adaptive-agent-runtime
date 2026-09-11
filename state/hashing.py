"""Canonical JSON serialization and SHA-256 hashing."""

import hashlib
import json
from typing import Any


def canonical_json(data: Any) -> str:
    """Serialize data into a deterministic, canonical JSON string.
    
    Keys are sorted, whitespace is minimized, and non-ASCII characters
    are preserved as valid UTF-8.
    """
    def _default_encoder(obj: Any) -> Any:
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        if hasattr(obj, "dict"):
            return obj.dict()
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if isinstance(obj, (set, frozenset)):
            return sorted(list(obj))
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=_default_encoder,
    )


def compute_hash(data: Any) -> str:
    """Compute standard SHA-256 hex digest for canonical JSON representation of data."""
    encoded = canonical_json(data).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_content_hash(
    *,
    actor: str,
    kind: str,
    project_id: str,
    payload: dict,
    task_id: str | None = None,
    causation_id: int | None = None,
    correlation_id: str | None = None,
    fencing_token: int | None = None,
) -> str:
    """Compute deterministic SHA-256 content hash for an event."""
    envelope = {
        "actor": actor,
        "causation_id": causation_id,
        "correlation_id": correlation_id,
        "fencing_token": fencing_token,
        "kind": kind,
        "payload": payload,
        "project_id": project_id,
        "task_id": task_id,
    }
    return compute_hash(envelope)
