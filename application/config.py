"""Persistent ARC project configuration and named agent profiles."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

ProviderName = Literal["mock", "codex", "claude", "antigravity", "opencode", "openrouter"]

_PROVIDER_DEFAULT_CAPABILITIES: dict[str, list[str]] = {
    "mock": ["implementation", "test", "docs", "review", "research"],
    "codex": ["implementation", "test", "debug", "refactor"],
    "claude": ["implementation", "test", "review", "docs", "architecture"],
    "antigravity": ["implementation", "test", "docs", "research"],
    "opencode": ["implementation", "test", "debug", "refactor"],
    "openrouter": [],
}


class AgentProfile(BaseModel):
    """Named execution profile used consistently by CLI, TUI, and router."""

    name: str
    provider: ProviderName
    model: Optional[str] = None
    role: str = "implementation"
    enabled: bool = True
    command_override: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=1, ge=1, le=32)
    cost_weight: float = Field(default=1.0, ge=0.0)
    quality_weight: float = Field(default=1.0, ge=0.0)
    metadata: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def populate_default_capabilities(self) -> "AgentProfile":
        if not self.capabilities:
            self.capabilities = list(_PROVIDER_DEFAULT_CAPABILITIES.get(self.provider, []))
        return self


class ArcConfig(BaseModel):
    """Repository-local ARC configuration stored under .arc/config.yaml."""

    project_id: str = "default"
    default_agent: str = "mock"
    hard_task_usd: float = 5.0
    hard_project_usd: float = 500.0
    visible_test_cmd: List[str] = Field(default_factory=list)
    orchestration_max_parallel: int = Field(default=3, ge=1, le=32)
    routing_policy: Literal["balanced", "quality", "cost"] = "balanced"
    agents: Dict[str, AgentProfile] = Field(default_factory=dict)

    @classmethod
    def default(cls, project_id: str = "default") -> "ArcConfig":
        mock = AgentProfile(
            name="mock",
            provider="mock",
            role="implementation",
            max_concurrency=4,
            cost_weight=0.0,
            quality_weight=0.5,
        )
        return cls(project_id=project_id, default_agent="mock", agents={"mock": mock})


class ConfigStore:
    """Read/write repository-local ARC configuration."""

    def __init__(self, repo: str | Path) -> None:
        self.repo = Path(repo).resolve()
        self.arc_dir = self.repo / ".arc"
        self.path = self.arc_dir / "config.yaml"

    def load(self, project_id: str | None = None) -> ArcConfig:
        if not self.path.exists():
            return ArcConfig.default(project_id or "default")
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        config = ArcConfig.model_validate(raw)
        if project_id:
            config.project_id = project_id
        if "mock" not in config.agents:
            config.agents["mock"] = ArcConfig.default(config.project_id).agents["mock"]
        else:
            mock = config.agents["mock"]
            mock.max_concurrency = max(mock.max_concurrency, 4)
        return config

    def _ensure_runtime_ignored(self) -> None:
        """Keep `.arc/` local without mutating a user's committed .gitignore."""
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return
        exclude_path = Path(result.stdout.strip())
        if not exclude_path.is_absolute():
            exclude_path = self.repo / exclude_path
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        current = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        existing = {line.strip() for line in current.splitlines()}
        if ".arc/" in existing:
            return
        prefix = "" if not current or current.endswith("\n") else "\n"
        with exclude_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{prefix}# ARC local runtime state\n.arc/\n")

    def save(self, config: ArcConfig) -> Path:
        self._ensure_runtime_ignored()
        self.arc_dir.mkdir(parents=True, exist_ok=True)
        payload = config.model_dump(mode="json", exclude_none=True)
        self.path.write_text(
            yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        return self.path

    def add_agent(self, profile: AgentProfile, *, make_default: bool = False) -> ArcConfig:
        config = self.load()
        config.agents[profile.name] = profile
        if make_default:
            config.default_agent = profile.name
        self.save(config)
        return config

    def remove_agent(self, name: str) -> ArcConfig:
        if name == "mock":
            raise ValueError("The built-in mock profile cannot be removed")
        config = self.load()
        config.agents.pop(name, None)
        if config.default_agent == name:
            config.default_agent = "mock"
        self.save(config)
        return config
