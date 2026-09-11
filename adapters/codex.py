"""Codex CLI coding-agent adapter."""

from adapters.cli_process import SubprocessCodingAgent


class CodexAgentAdapter(SubprocessCodingAgent):
    """Run Codex as a real workspace-editing CLI agent.

    Default command: ``codex exec --full-auto -``.
    Override with ``ARC_CODEX_COMMAND`` when your installed Codex CLI uses a
    different invocation. The adapter never fabricates a successful patch.
    """

    def __init__(self, model_name: str | None = None) -> None:
        command = ["codex", "exec", "--full-auto"]
        if model_name:
            command.extend(["--model", model_name])
        command.append("-")
        super().__init__(
            name="Codex",
            executable="codex",
            command=command,
            env_command_var="ARC_CODEX_COMMAND",
        )
        self.model_name = model_name
