"""Codex CLI coding-agent adapter."""

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
