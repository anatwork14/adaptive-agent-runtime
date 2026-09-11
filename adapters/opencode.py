"""OpenCode CLI coding-agent adapter."""

from adapters.cli_process import SubprocessCodingAgent


class OpenCodeAgentAdapter(SubprocessCodingAgent):
    """Run OpenCode as a real workspace-editing CLI agent.

    The default command is ``opencode run`` with the ARC prompt on stdin.
    Override it with ``ARC_OPENCODE_COMMAND`` if your installed version uses a
    different invocation.
    """

    def __init__(self, model_name: str | None = None) -> None:
        command = ["opencode", "run"]
        if model_name:
            command.extend(["--model", model_name])
        super().__init__(
            name="OpenCode",
            executable="opencode",
            command=command,
            env_command_var="ARC_OPENCODE_COMMAND",
        )
        self.model_name = model_name
