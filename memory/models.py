"""Pydantic models for the Adaptive Memory Plane."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    FACT = "fact"
    DECISION = "decision"
    ASSUMPTION = "assumption"
    PROCEDURE = "procedure"
    FAILURE = "failure"
    TASK_SUMMARY = "task_summary"
    CODE_SURFACE = "code_surface"
    ARTIFACT = "artifact"
    EPISODE = "episode"
    CONSTRAINT = "constraint"


class MemoryRepresentation(str, Enum):
    RAW_EVENT_REFS = "RAW_EVENT_REFS"
    STRUCTURED_FACT = "STRUCTURED_FACT"
    SUMMARY = "SUMMARY"
    DECISION_RECORD = "DECISION_RECORD"
    PROCEDURE = "PROCEDURE"
    CODE_POINTER = "CODE_POINTER"
    GRAPH_RELATION = "GRAPH_RELATION"
    EMBEDDED_CHUNK = "EMBEDDED_CHUNK"
    ARTIFACT_POINTER = "ARTIFACT_POINTER"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    DELETED = "deleted"
    DISPUTED = "disputed"


class SourceRole(str, Enum):
    SUPPORTS = "supports"
    CAUSED_BY = "caused_by"
    SUMMARIZES = "summarizes"
    SUPERSEDES = "supersedes"
    DERIVED_FROM = "derived_from"
    VALIDATED_BY = "validated_by"


class RelationType(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    DEPENDS_ON = "depends_on"
    SUPERSEDES = "supersedes"
    IMPLEMENTS = "implements"
    CAUSED = "caused"
    RELATED_TO = "related_to"


class MemorySource(BaseModel):
    memory_id: str
    source_event_id: int
    source_role: SourceRole = SourceRole.DERIVED_FROM


class MemoryRelation(BaseModel):
    src_memory_id: str
    relation: RelationType
    dst_memory_id: str
    created_event: int


class Memory(BaseModel):
    """Derived, non-authoritative memory object with provenance and validity intervals."""
    memory_id: str
    project_id: str
    type: MemoryType
    representation: MemoryRepresentation

    content_json: Dict[str, Any] = Field(default_factory=dict)
    content_text: str = ""

    created_event: int
    valid_from_event: int
    valid_to_event: Optional[int] = None

    state_version_at_write: int
    status: MemoryStatus = MemoryStatus.ACTIVE
    superseded_by: Optional[str] = None

    confidence: float = 1.0
    importance: float = 0.5
    predicted_reuse: float = 0.5

    access_count: int = 0
    last_accessed_event: Optional[int] = None

    token_size: int = 0
    content_hash: str = ""

    producer_type: str = "deterministic"
    producer_model: Optional[str] = None
    producer_prompt_hash: Optional[str] = None

    source_events: List[int] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class MemoryFeedback(BaseModel):
    id: Optional[int] = None
    memory_id: str
    context_id: str
    task_id: str
    delivered: int = 1
    used: Optional[int] = None
    useful: Optional[int] = None
    stale: Optional[int] = None
    misleading: Optional[int] = None
    downstream_gate: Optional[str] = None
    event_id: int = 0
