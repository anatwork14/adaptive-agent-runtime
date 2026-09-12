"""Codex CLI coding-agent adapter."""

import json
from collections.abc import Iterable

from adapters.cli_process import SubprocessCodingAgent


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
        )
        self.model_name = model_name

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
