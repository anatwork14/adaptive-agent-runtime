"""Shared subprocess substrate for real coding-agent CLIs."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import signal
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import List, Optional

from adapters.base import AgentBudget, AgentRunResult
from context.compiler import ContextPacket
from runtime.environment import (
    build_execution_environment,
    environment_key_manifest,
    redact_command,
    redact_text_secrets,
)


class AgentAdapterUnavailable(RuntimeError):
    """Raised when a requested real agent CLI is not installed/configured."""


StreamCallback = Callable[[str, str], Awaitable[None] | None]


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


async def _emit_stream(callback: StreamCallback | None, stream: str, text: str) -> None:
    if callback is None or not text:
        return
    result = callback(stream, text)
    if result is not None:
        await result


def _process_spawn_kwargs() -> dict[str, object]:
    """Create an isolated process group for one disposable provider turn.

    Provider CLIs routinely spawn shell/tool subprocesses. On POSIX a new session
    makes the provider PID the process-group leader so cancellation can stop the
    whole supervised turn instead of only its top-level CLI process.
    """
    if os.name == "posix":
        return {"start_new_session": True}
    return {}


def _posix_process_group_exists(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _wait_posix_process_group_gone(group_id: int, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(timeout, 0.0)
    while _posix_process_group_exists(group_id):
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.05)
    return True


async def _terminate_process(
    process: asyncio.subprocess.Process,
    *,
    grace_seconds: float = 2.0,
) -> None:
    """Terminate the supervised provider process tree and escalate if needed."""
    if os.name == "posix":
        group_id = process.pid
        loop = asyncio.get_running_loop()
        deadline = loop.time() + grace_seconds
        try:
            os.killpg(group_id, signal.SIGTERM)
        except ProcessLookupError:
            if process.returncode is None:
                await process.wait()
            return

        if process.returncode is None:
            remaining = max(0.0, deadline - loop.time())
            try:
                await asyncio.wait_for(process.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                pass

        remaining = max(0.0, deadline - loop.time())
        if await _wait_posix_process_group_gone(group_id, remaining):
            if process.returncode is None:
                await process.wait()
            return

        try:
            os.killpg(group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if process.returncode is None:
            await process.wait()
        await _wait_posix_process_group_gone(group_id, 0.5)
        return

    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_seconds)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


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
        output_callback: StreamCallback | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AgentRunResult:
        """Run one provider turn with streaming output and cooperative cancellation.

        The provider process remains disposable operational state. Durable worker
        continuity still comes from the isolated worktree plus ARC's event log.
        ``output_callback`` receives redacted decoded stdout/stderr lines as they
        arrive. ``cancel_event`` lets a supervisor terminate the live provider
        without treating cancellation as a successful patch or provider failure.
        """
        command = self.build_command()
        self.ensure_available(command)
        environment = self.execution_environment()
        trace_command = redact_command(command)
        trace_env = environment_key_manifest(environment)

        if cancel_event is not None and cancel_event.is_set():
            return AgentRunResult(
                status="cancelled",
                summary=f"{self.name} turn cancelled before launch",
                memory_references=list(memory_references or []),
                tool_trace=[
                    {
                        "action": "cli_cancelled",
                        "command": trace_command,
                        "environment_keys": trace_env,
                        "phase": "pre_launch",
                    }
                ],
            )

        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            limit=1024 * 1024,
            **_process_spawn_kwargs(),
        )
        stdout_tail = ""
        stderr_tail = ""

        async def pump(
            reader: asyncio.StreamReader | None,
            stream: str,
            *,
            tail_limit: int,
        ) -> None:
            nonlocal stdout_tail, stderr_tail
            if reader is None:
                return
            # Provider CLIs are predominantly line-oriented. Buffering one full
            # line before persistence prevents an environment credential split
            # across OS read chunks from leaking as two individually harmless
            # fragments. The subprocess stream limit is raised for long lines.
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                text = raw.decode("utf-8", errors="replace")
                safe_text = redact_text_secrets(text, environment)
                if stream == "stdout":
                    stdout_tail = (stdout_tail + safe_text)[-tail_limit:]
                else:
                    stderr_tail = (stderr_tail + safe_text)[-tail_limit:]
                await _emit_stream(output_callback, stream, safe_text)

        stdout_task = asyncio.create_task(pump(process.stdout, "stdout", tail_limit=8000))
        stderr_task = asyncio.create_task(pump(process.stderr, "stderr", tail_limit=4000))
        wait_task = asyncio.create_task(process.wait())
        cancel_task = (
            asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
        )

        try:
            if process.stdin is not None:
                try:
                    process.stdin.write(prompt.encode("utf-8"))
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    # A provider may reject its invocation or exit before ARC
                    # finishes writing the prompt. Classification still comes
                    # from the process return code/stderr below; a closed stdin
                    # pipe is not itself a reason to abandon process cleanup.
                    pass
                finally:
                    process.stdin.close()
                    try:
                        await process.stdin.wait_closed()
                    except (AttributeError, BrokenPipeError, ConnectionResetError):
                        pass

            waiters = {wait_task}
            if cancel_task is not None:
                waiters.add(cancel_task)
            done, _ = await asyncio.wait(
                waiters,
                timeout=budget.timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )

            outcome = "completed"
            if wait_task in done:
                await wait_task
            elif cancel_task is not None and cancel_task in done:
                outcome = "cancelled"
                await _terminate_process(process)
            else:
                outcome = "timeout"
                await _terminate_process(process)

            await asyncio.gather(stdout_task, stderr_task)

            if outcome == "cancelled":
                return AgentRunResult(
                    status="cancelled",
                    summary=f"{self.name} turn cancelled by operator",
                    memory_references=list(memory_references or []),
                    tool_trace=[
                        {
                            "action": "cli_cancelled",
                            "command": trace_command,
                            "environment_keys": trace_env,
                            "returncode": process.returncode,
                        }
                    ],
                )
            if outcome == "timeout":
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

            if process.returncode != 0:
                return AgentRunResult(
                    status="failed",
                    summary=f"{self.name} exited with code {process.returncode}: {stderr_tail[-4000:]}",
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
                summary=stdout_tail[-8000:] or f"{self.name} completed without textual output",
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
        except asyncio.CancelledError:
            await _terminate_process(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        finally:
            if cancel_task is not None and not cancel_task.done():
                cancel_task.cancel()
            if not wait_task.done() and process.returncode is not None:
                await wait_task

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
