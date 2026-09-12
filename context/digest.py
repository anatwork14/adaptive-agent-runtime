"""Context digest generation using canonical JSON and SHA-256."""

from typing import Any, Dict

from state.hashing import compute_hash


def compute_context_digest(packet_data: Dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 digest over stable packet content.

    ``compiled_event`` is excluded because the event ID is allocated only after
    the context payload has been hashed and persisted. Including it would make
    the final immutable packet fail verification against the digest recorded in
    its own ``context.compiled`` event.
    """
    data = {
        key: value
        for key, value in packet_data.items()
        if key not in {"digest", "compiled_event"}
    }
    return f"sha256:{compute_hash(data)}"
