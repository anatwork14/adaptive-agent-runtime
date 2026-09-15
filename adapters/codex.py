"""Codex CLI coding-agent adapter."""

import json
import shutil
import tempfile
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from adapters.cli_process import SubprocessCodingAgent
from runtime.codex_invocation_config import (
    CodexInvocationConfig,
    stage_invocation_home,
)
from runtime.environment import build_execution_environment


class CodexAgentAdapter(SubprocessCodingAgent):
    """Run Codex as a real workspace-editing CLI agent.

    Default command: ``codex exec --full-auto -``.
    Override with ``ARC_CODEX_COMMAND`` or the profile-local command override
    when your installed Codex CLI uses a different invocation. The adapter never
    fabricates a successful patch.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        command_override: str | None = None,
        env_allow: Iterable[str] = (),
        codex_home: str | None = None,
        codex_config_path: str | None = None,
        invocation_config: CodexInvocationConfig | None = None,
        auth_source: str | Path | None = None,
    ) -> None:
        command = ["codex", "exec", "--full-auto"]
        if model_name:
            command.extend(["--model", model_name])
        command.append("-")
        super().__init__(
            name="Codex",
            executable="codex",
            command=command,
            env_command_var="ARC_CODEX_COMMAND",
            provider="codex",
            command_override=command_override,
            env_allow=env_allow,
            environment_overrides={"CODEX_HOME": codex_home} if codex_home else None,
        )
        self.model_name = model_name
        self.codex_home = codex_home
        self.codex_config_path = codex_config_path
        self.invocation_config = invocation_config
        self.auth_source = Path(auth_source).expanduser().resolve() if auth_source else None
        self._active_invocation_home: str | None = None

    def execution_environment(self) -> dict[str, str]:
        """Use a disposable provider home for each real Codex turn."""
        codex_home = self._active_invocation_home or self.codex_home
        # An explicit Codex home is the ARC subscription-backed path. Keep its
        # child process isolated from host API credentials and endpoint
        # overrides; generic Codex profiles without a home retain the legacy
        # provider environment policy.
        environment_provider = "codex_subscription_home" if self.codex_home else self.provider
        return build_execution_environment(
            provider=environment_provider,
            extra_names=self.env_allow,
            overrides={"CODEX_HOME": codex_home} if codex_home else None,
        )

    @contextmanager
    def _invocation_home(self) -> Iterator[str]:
        """Materialize config/auth state into a disposable Codex home.

        Only the vendor-owned auth file and the frozen non-secret config are
        copied. The provider may mutate the disposable copy, but it can never
        rewrite the canonical config or fall back to the ambient Codex home.
        """
        if not self.codex_home:
            raise RuntimeError("Codex invocation isolation requires codex_home")
        if self.invocation_config is not None:
            auth_source = self.auth_source or (Path(self.codex_home) / "auth.json")
            with stage_invocation_home(
                self.invocation_config,
                auth_source=auth_source,
            ) as staged:
                yield str(staged.home)
            return
        source_home = Path(self.codex_home).expanduser().resolve()
        source_config = Path(self.codex_config_path or source_home / "config.toml").resolve()
        if not source_config.is_file():
            raise RuntimeError(f"Codex invocation config does not exist: {source_config}")

        with tempfile.TemporaryDirectory(prefix="arc-codex-v4-invocation-") as temp_home:
            target_home = Path(temp_home)
            target_home.chmod(0o700)
            shutil.copy2(source_config, target_home / "config.toml")
            auth_state = source_home / "auth.json"
            if auth_state.is_file():
                shutil.copy2(auth_state, target_home / "auth.json")
                (target_home / "auth.json").chmod(0o600)
            (target_home / "config.toml").chmod(0o600)
            yield str(target_home)

    async def run_prompt(self, **kwargs):
        """Run one turn from a fresh, disposable provider-home snapshot."""
        if not self.codex_home:
            return await super().run_prompt(**kwargs)
        with self._invocation_home() as invocation_home:
            self._active_invocation_home = invocation_home
            try:
                return await super().run_prompt(**kwargs)
            finally:
                self._active_invocation_home = None

    def parse_output_events(self, stream: str, text: str) -> list[str]:
        """Map documented ``codex exec --json`` JSONL events to safe boundaries.

        Unknown event types and malformed lines are intentionally ignored. ARC
        records only lifecycle names, never the provider event payload, because
        provider output may contain task or repository content.
        """
        if stream != "stdout":
            return []
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(event, dict):
            return []

        event_type = event.get("type")
        if event_type == "turn.started":
            return ["provider.request_started"]
        if event_type == "turn.completed":
            return ["provider.completed"]
        if event_type in {"error", "turn.failed"}:
            return ["provider.failed"]
        if event_type in {"item.started", "item.completed"}:
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") in {
                "agent_message",
                "assistant_message",
            }:
                return ["provider.response_started"]
        return []

    def structured_output_mode(self, command: Iterable[str]) -> bool:
        """Codex's ``--json`` mode requires documented JSONL turn boundaries."""
        return "--json" in command

    def parse_output_metadata(self, stream: str, text: str) -> dict[str, object]:
        if stream != "stdout":
            return {}
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(event, dict):
            return {}

        event_type = event.get("type")
        if event_type == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                mapped: dict[str, int] = {}
                for source, target in (
                    ("input_tokens", "prompt_tokens"),
                    ("output_tokens", "completion_tokens"),
                    ("cached_input_tokens", "cached_prompt_tokens"),
                    ("reasoning_output_tokens", "reasoning_tokens"),
                ):
                    value = usage.get(source)
                    if isinstance(value, (int, float)) and value >= 0:
                        mapped[target] = int(value)
                return {"token_usage": mapped} if mapped else {}
        if event_type in {"error", "turn.failed"}:
            diagnostic = False
            for key in ("message", "detail", "code", "error"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    diagnostic = True
                elif isinstance(value, dict) and any(
                    isinstance(value.get(nested), (str, int, float))
                    and str(value.get(nested)).strip()
                    for nested in ("message", "detail", "code")
                ):
                    diagnostic = True
            return {
                "structured_error_observed": True,
                "structured_error_diagnostic": diagnostic,
            }
        return {}
