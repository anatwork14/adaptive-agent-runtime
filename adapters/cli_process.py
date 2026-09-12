"""Shared subprocess substrate for real coding-agent CLIs."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

from adapters.base import AgentBudget, AgentRunResult
from context.compiler import ContextPacket
from runtime.environment import (
    build_execution_environment,
    environment_key_manifest,
    redact_command,
)


class AgentAdapterUnavailable(RuntimeError):
    """Raised when a requested real agent CLI is not installed/configured."""


def render_context_prompt(context: ContextPacket) -> str:
    """Render an immutable ContextPacket into a provider-neutral work prompt."""
    payload = context.model_dump(mode="json")
    return (
        "You are an ARC coding worker operating inside an isolated git worktree.\n"
        "Implement the task directly in the current workspace. Do not merely describe a patch.\n"
        "Do not commit changes; ARC will create the immutable candidate commit after you exit.\n"
        "Respect the supplied project decisions, constraints, and acceptance criteria.\n"
        "If context is insufficient, inspect the repository using your normal tools.\n\n"
        "ARC_CONTEXT_JSON:\n"
        + json.dumps(payload, indent=2, sort_keys=True)
    )


class SubprocessCodingAgent:
    """Run a real CLI coding agent in a task worktree.

    ``command`` must point to a provider CLI that reads the task prompt from
    stdin and performs repository edits in its current working directory.
    Provider wrappers may override ``build_command`` when their CLI expects the
    prompt as an argument instead.

    ARC passes an explicit least-privilege environment to the child process.
    Provider-specific auth variables and operator-approved extra variable names
    are copied at execution time; unrelated host secrets are not inherited.
    """

    def __init__(
        self,
        *,
        name: str,
        executable: str,
        command: Optional[List[str]] = None,
        env_command_var: Optional[str] = None,
        provider: str | None = None,
        command_override: str | None = None,
        env_allow: Optional[Iterable[str]] = None,
    ) -> None:
        self.name = name
        self.executable = executable
        self._command = command
        self.env_command_var = env_command_var
        self.provider = provider
        self.command_override = command_override
        self.env_allow = list(env_allow or [])

    def build_command(self) -> List[str]:
        if self.command_override:
            return shlex.split(self.command_override)
        if self.env_command_var:
            override = os.environ.get(self.env_command_var)
            if override:
                return shlex.split(override)
        if self._command:
            return list(self._command)
        return [self.executable]

    def execution_environment(self) -> dict[str, str]:
        return build_execution_environment(
            provider=self.provider,
            extra_names=self.env_allow,
        )

    def ensure_available(self, command: Iterable[str]) -> None:
        command = list(command)
        if not command:
            raise AgentAdapterUnavailable(f"{self.name}: empty CLI command")
        if shutil.which(command[0]) is None:
            hint = f" or set {self.env_command_var}" if self.env_command_var else ""
            raise AgentAdapterUnavailable(
                f"{self.name} CLI executable '{command[0]}' was not found{hint}. "
                "ARC real adapters never silently fall back to a mock."
            )

    async def run_prompt(
        self,
        *,
        prompt: str,
        workspace: Path,
        budget: AgentBudget,
        memory_references: Optional[list[str]] = None,
    ) -> AgentRunResult:
        """Run one provider turn with an explicit prompt in an existing workspace.

        Persistent worker sessions use this method to continue editing the same
        worktree across multiple operator instructions. Provider processes may be
        re-launched per turn; the durable state is the worktree + ARC event log.
        """
        command = self.build_command()
        self.ensure_available(command)
        environment = self.execution_environment()
        trace_command = redact_command(command)
        trace_env = environment_key_manifest(environment)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")),
                timeout=budget.timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return AgentRunResult(
                status="failed",
                summary=f"{self.name} timed out after {budget.timeout_seconds}s",
                memory_references=list(memory_references or []),
                tool_trace=[
                    {
                        "action": "cli_timeout",
                        "command": trace_command,
                        "environment_keys": trace_env,
                    }
                ],
            )

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        if process.returncode != 0:
            return AgentRunResult(
                status="failed",
                summary=f"{self.name} exited with code {process.returncode}: {err[-4000:]}",
                memory_references=list(memory_references or []),
                tool_trace=[
                    {
                        "action": "cli_run",
                        "command": trace_command,
                        "environment_keys": trace_env,
                        "returncode": process.returncode,
                    }
                ],
            )

        return AgentRunResult(
            status="completed",
            patch_ref="WORKTREE",
            diff="",
            summary=out[-8000:] or f"{self.name} completed without textual output",
            memory_references=list(memory_references or []),
            tool_trace=[
                {
                    "action": "cli_run",
                    "command": trace_command,
                    "environment_keys": trace_env,
                    "returncode": process.returncode,
                }
            ],
            token_usage={},
            cost_usd=0.0,
        )

    async def run(
        self,
        *,
        context: ContextPacket,
        workspace: Path,
        budget: AgentBudget,
    ) -> AgentRunResult:
        return await self.run_prompt(
            prompt=render_context_prompt(context),
            workspace=workspace,
            budget=budget,
            memory_references=list(context.memory_ids),
        )
