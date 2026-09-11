"""Context digest generation using canonical JSON and SHA-256."""

from typing import Any, Dict
from state.hashing import compute_hash


def compute_context_digest(packet_data: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 digest over canonical JSON of context packet."""
    # Exclude digest field itself if present
    data = {k: v for k, v in packet_data.items() if k != "digest"}
    return f"sha256:{compute_hash(data)}"
