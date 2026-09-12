"""OpenCode CLI coding-agent adapter."""

from collections.abc import Iterable

from adapters.cli_process import SubprocessCodingAgent


class OpenCodeAgentAdapter(SubprocessCodingAgent):
    """Run OpenCode as a real workspace-editing CLI agent.

    The default command is ``opencode run`` with the ARC prompt on stdin.
    Override it with ``ARC_OPENCODE_COMMAND`` or the profile-local command
    override if your installed version uses a different invocation.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        command_override: str | None = None,
        env_allow: Iterable[str] = (),
    ) -> None:
        command = ["opencode", "run"]
        if model_name:
            command.extend(["--model", model_name])
        super().__init__(
            name="OpenCode",
            executable="opencode",
            command=command,
            env_command_var="ARC_OPENCODE_COMMAND",
            provider="opencode",
            command_override=command_override,
            env_allow=env_allow,
        )
        self.model_name = model_name
