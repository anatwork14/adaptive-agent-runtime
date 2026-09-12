"""Claude Code CLI coding-agent adapter."""

from collections.abc import Iterable

from adapters.cli_process import SubprocessCodingAgent


class ClaudeAgentAdapter(SubprocessCodingAgent):
    """Run Claude Code as a real workspace-editing CLI agent.

    Default command: ``claude -p`` reading the ARC prompt from stdin. Override
    with ``ARC_CLAUDE_COMMAND`` or the profile-local command override for local
    CLI variations. The adapter never returns a simulated success.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        command_override: str | None = None,
        env_allow: Iterable[str] = (),
    ) -> None:
        command = ["claude", "-p"]
        if model_name:
            command.extend(["--model", model_name])
        super().__init__(
            name="Claude Code",
            executable="claude",
            command=command,
            env_command_var="ARC_CLAUDE_COMMAND",
            provider="claude",
            command_override=command_override,
            env_allow=env_allow,
        )
        self.model_name = model_name
