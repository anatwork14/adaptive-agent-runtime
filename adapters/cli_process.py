"""Shared subprocess substrate for real coding-agent CLIs."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import signal
from collections.abc import Awaitable, Callable, Iterable, Mapping
from pathlib import Path
from typing import List, Optional

from adapters.base import AgentBudget, AgentRunResult, classify_provider_failure
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
        "ARC_CONTEXT_JSON:\n" + json.dumps(payload, indent=2, sort_keys=True)
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
        environment_overrides: Mapping[str, str] | None = None,
    ) -> None:
        self.name = name
        self.executable = executable
        self._command = command
        self.env_command_var = env_command_var
        self.provider = provider
        self.command_override = command_override
        self.env_allow = list(env_allow or [])
        self.environment_overrides = dict(environment_overrides or {})

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
            overrides=self.environment_overrides,
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

    def parse_output_events(self, stream: str, text: str) -> list[str]:
        """Return observable provider lifecycle events from one output line.

        Plain-text CLIs do not expose a reliable response boundary, so the base
        implementation deliberately observes nothing. Provider adapters may
        override this for a documented machine-readable mode.
        """
        return []

    def parse_output_metadata(self, stream: str, text: str) -> dict[str, object]:
        """Return bounded, provider-specific metadata from one output line."""
        return {}

    def structured_output_mode(self, command: Iterable[str]) -> bool:
        """Whether this invocation promises machine-readable lifecycle events."""
        return False

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
        loop = asyncio.get_running_loop()
        started_monotonic = loop.time()

        def build_result(**kwargs: object) -> AgentRunResult:
            kwargs.setdefault("configured_timeout_seconds", budget.timeout_seconds)
            kwargs.setdefault("elapsed_seconds", max(0.0, loop.time() - started_monotonic))
            return AgentRunResult(**kwargs)

        command = self.build_command()
        trace_command = redact_command(command)
        structured_output = self.structured_output_mode(command)
        lifecycle = {
            "process_started": "unknown",
            "prompt_written": "unknown",
            "request_started": "unknown",
            "response_started": "unknown",
            "completed": "unknown",
            "failed": "unknown",
        }
        provider_events: list[dict[str, object]] = []

        def record_event(name: str) -> None:
            if any(item.get("event") == name for item in provider_events):
                return
            provider_events.append({"event": name, "observed": True})
            if name == "cli.prompt_written":
                lifecycle["prompt_written"] = "observed"
            elif name.startswith("provider."):
                lifecycle[name.removeprefix("provider.")] = "observed"

        try:
            self.ensure_available(command)
        except AgentAdapterUnavailable as exc:
            detail = redact_text_secrets(str(exc))
            record_event("provider.failed")
            return build_result(
                status="failed",
                summary=detail,
                failure_classification="CLI_NOT_FOUND",
                provider_outcome="not_found",
                stderr_tail=detail[-4000:],
                tool_trace=[
                    {
                        "action": "cli_spawn_failed",
                        "command": trace_command,
                        "environment_keys": [],
                        "error": detail,
                    }
                ],
                provider_lifecycle=lifecycle,
                provider_events=provider_events,
                memory_references=list(memory_references or []),
            )

        environment = self.execution_environment()
        trace_env = environment_key_manifest(environment)

        if cancel_event is not None and cancel_event.is_set():
            record_event("provider.failed")
            return build_result(
                status="cancelled",
                summary=f"{self.name} turn cancelled before launch",
                failure_classification="CLI_CANCELLED",
                provider_outcome="cancelled",
                memory_references=list(memory_references or []),
                tool_trace=[
                    {
                        "action": "cli_cancelled",
                        "command": trace_command,
                        "environment_keys": trace_env,
                        "phase": "pre_launch",
                    }
                ],
                provider_lifecycle=lifecycle,
                provider_events=provider_events,
            )

        try:
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
        except FileNotFoundError as exc:
            detail = redact_text_secrets(str(exc))
            record_event("provider.failed")
            return build_result(
                status="failed",
                summary=f"{self.name} could not be launched: {detail}",
                failure_classification="CLI_NOT_FOUND",
                provider_outcome="not_found",
                stderr_tail=detail[-4000:],
                tool_trace=[
                    {
                        "action": "cli_spawn_failed",
                        "command": trace_command,
                        "environment_keys": trace_env,
                        "error": detail,
                    }
                ],
                provider_lifecycle=lifecycle,
                provider_events=provider_events,
                memory_references=list(memory_references or []),
            )
        except OSError as exc:
            detail = redact_text_secrets(str(exc))
            record_event("provider.failed")
            return build_result(
                status="failed",
                summary=f"{self.name} could not be launched: {detail}",
                failure_classification="UNKNOWN_PROVIDER_FAILURE",
                provider_outcome="launch_error",
                stderr_tail=detail[-4000:],
                tool_trace=[
                    {
                        "action": "cli_spawn_failed",
                        "command": trace_command,
                        "environment_keys": trace_env,
                        "error": detail,
                    }
                ],
                provider_lifecycle=lifecycle,
                provider_events=provider_events,
                memory_references=list(memory_references or []),
            )
        record_event("provider.process_started")
        stdout_tail = ""
        stderr_tail = ""
        token_usage: dict[str, int] = {}
        structured_error_observed = False
        structured_error_diagnostic = False

        async def pump(
            reader: asyncio.StreamReader | None,
            stream: str,
            *,
            tail_limit: int,
        ) -> None:
            nonlocal \
                stdout_tail, \
                stderr_tail, \
                structured_error_observed, \
                structured_error_diagnostic
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
                for event_name in self.parse_output_events(stream, safe_text):
                    record_event(event_name)
                metadata = self.parse_output_metadata(stream, safe_text)
                usage = metadata.get("token_usage")
                if not token_usage and isinstance(usage, dict):
                    token_usage.update(
                        {
                            str(key): int(value)
                            for key, value in usage.items()
                            if isinstance(value, int)
                        }
                    )
                if metadata.get("structured_error_observed"):
                    structured_error_observed = True
                    structured_error_diagnostic = structured_error_diagnostic or bool(
                        metadata.get("structured_error_diagnostic")
                    )
                await _emit_stream(output_callback, stream, safe_text)

        stdout_task = asyncio.create_task(pump(process.stdout, "stdout", tail_limit=8000))
        stderr_task = asyncio.create_task(pump(process.stderr, "stderr", tail_limit=4000))
        wait_task = asyncio.create_task(process.wait())
        cancel_task = asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None

        try:
            if process.stdin is not None:
                try:
                    process.stdin.write(prompt.encode("utf-8"))
                    await process.stdin.drain()
                    record_event("cli.prompt_written")
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
                record_event("provider.failed")
                return build_result(
                    status="cancelled",
                    summary=f"{self.name} turn cancelled by operator",
                    failure_classification="CLI_CANCELLED",
                    provider_returncode=process.returncode,
                    provider_outcome="cancelled",
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                    memory_references=list(memory_references or []),
                    tool_trace=[
                        {
                            "action": "cli_cancelled",
                            "command": trace_command,
                            "environment_keys": trace_env,
                            "returncode": process.returncode,
                        }
                    ],
                    provider_lifecycle=lifecycle,
                    provider_events=provider_events,
                    token_usage=token_usage,
                )
            if outcome == "timeout":
                record_event("provider.failed")
                return build_result(
                    status="failed",
                    summary=f"{self.name} timed out after {budget.timeout_seconds}s",
                    failure_classification="CLI_TIMEOUT",
                    provider_returncode=process.returncode,
                    provider_outcome="timeout",
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                    memory_references=list(memory_references or []),
                    tool_trace=[
                        {
                            "action": "cli_timeout",
                            "command": trace_command,
                            "environment_keys": trace_env,
                            "returncode": process.returncode,
                        }
                    ],
                    provider_lifecycle=lifecycle,
                    provider_events=provider_events,
                    token_usage=token_usage,
                )

            if process.returncode != 0:
                record_event("provider.failed")
                if structured_error_observed and not structured_error_diagnostic:
                    classification = "UNKNOWN_PROVIDER_FAILURE"
                else:
                    classification = classify_provider_failure(
                        status="failed",
                        outcome="failed",
                        returncode=process.returncode,
                        summary=stderr_tail[-4000:],
                        stdout_tail=stdout_tail,
                        stderr_tail=stderr_tail,
                    )
                return build_result(
                    status="failed",
                    summary=f"{self.name} exited with code {process.returncode}: {stderr_tail[-4000:]}",
                    failure_classification=classification,
                    provider_returncode=process.returncode,
                    provider_outcome="failed",
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                    memory_references=list(memory_references or []),
                    tool_trace=[
                        {
                            "action": "cli_run",
                            "command": trace_command,
                            "environment_keys": trace_env,
                            "returncode": process.returncode,
                        }
                    ],
                    provider_lifecycle=lifecycle,
                    provider_events=provider_events,
                    token_usage=token_usage,
                )

            if any(item.get("event") == "provider.failed" for item in provider_events):
                classification = (
                    "UNKNOWN_PROVIDER_FAILURE"
                    if structured_error_observed and not structured_error_diagnostic
                    else classify_provider_failure(
                        status="failed",
                        outcome="failed",
                        returncode=None,
                        summary=stdout_tail,
                        stderr_tail=stderr_tail,
                    )
                )
                return build_result(
                    status="failed",
                    summary=f"{self.name} emitted a provider error event",
                    failure_classification=classification,
                    provider_returncode=process.returncode,
                    provider_outcome="failed",
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                    memory_references=list(memory_references or []),
                    tool_trace=[
                        {
                            "action": "cli_run",
                            "command": trace_command,
                            "environment_keys": trace_env,
                            "returncode": process.returncode,
                        }
                    ],
                    provider_lifecycle=lifecycle,
                    provider_events=provider_events,
                    token_usage=token_usage,
                )

            if structured_output and not any(
                item.get("event") == "provider.completed" for item in provider_events
            ):
                record_event("provider.failed")
                return build_result(
                    status="failed",
                    summary=(
                        f"{self.name} exited without a documented structured provider "
                        "completion or failure event"
                    ),
                    failure_classification="UNKNOWN_PROVIDER_FAILURE",
                    provider_returncode=process.returncode,
                    provider_outcome="incomplete_structured_turn",
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                    memory_references=list(memory_references or []),
                    tool_trace=[
                        {
                            "action": "cli_run",
                            "command": trace_command,
                            "environment_keys": trace_env,
                            "returncode": process.returncode,
                        }
                    ],
                    token_usage=token_usage,
                    provider_lifecycle=lifecycle,
                    provider_events=provider_events,
                )

            record_event("provider.completed")
            return build_result(
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
                token_usage=token_usage,
                cost_usd=0.0,
                provider_returncode=process.returncode,
                provider_outcome="completed",
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                provider_lifecycle=lifecycle,
                provider_events=provider_events,
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
