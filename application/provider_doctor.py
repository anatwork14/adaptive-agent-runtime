"""Passive provider diagnostics and an isolated, non-benchmark smoke probe."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adapters.base import AgentBudget, AgentRunResult, sanitize_failure_diagnostics
from adapters.cli_process import SubprocessCodingAgent
from application.agents import build_agent
from application.auth import auth_status
from application.config import AgentProfile
from runtime.environment import environment_key_manifest, redact_command

SMOKE_PROMPT = (
    "This is an ARC provider apparatus smoke probe, not a benchmark task. "
    "Do not inspect, read, or modify files. Reply with exactly "
    "ARC_PROVIDER_SMOKE_OK and nothing else."
)

_AUTH_EXECUTABLES = {"codex": "codex", "claude": "claude", "antigravity": "agy"}


@dataclass(frozen=True)
class PassiveProviderReport:
    profile: str
    provider: str
    model: str | None
    role: str
    executable: str | None
    executable_path: str | None
    version: str | None
    effective_argv: list[str]
    environment_keys: list[str]
    authentication_state: str
    authentication_detail: str
    status: str
    detail: str


def _version(executable: str, environment: dict[str, str]) -> str | None:
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout or result.stderr or "").strip().splitlines()
    return text[0][:280] if text else None


def passive_provider_doctor(profile: AgentProfile) -> PassiveProviderReport:
    """Inspect a profile without sending an inference request."""
    if not profile.enabled:
        return PassiveProviderReport(
            profile=profile.name,
            provider=profile.provider,
            model=profile.model,
            role=profile.role,
            executable=None,
            executable_path=None,
            version=None,
            effective_argv=[],
            environment_keys=[],
            authentication_state="NOT_CHECKED",
            authentication_detail="profile disabled",
            status="DISABLED",
            detail="provider profile is disabled",
        )

    try:
        adapter = build_agent(profile)
    except Exception as exc:
        return PassiveProviderReport(
            profile=profile.name,
            provider=profile.provider,
            model=profile.model,
            role=profile.role,
            executable=None,
            executable_path=None,
            version=None,
            effective_argv=[],
            environment_keys=[],
            authentication_state="UNKNOWN",
            authentication_detail=str(exc)[:280],
            status="CONFIGURATION_ERROR",
            detail=str(exc)[:280],
        )

    if not isinstance(adapter, SubprocessCodingAgent):
        return PassiveProviderReport(
            profile=profile.name,
            provider=profile.provider,
            model=profile.model,
            role=profile.role,
            executable=None,
            executable_path=None,
            version=None,
            effective_argv=[],
            environment_keys=[],
            authentication_state="NOT_CHECKED",
            authentication_detail="provider has no filesystem subprocess adapter",
            status="UNSUPPORTED",
            detail="provider diagnostic path requires a subprocess-backed filesystem executor",
        )

    command = adapter.build_command()
    environment = adapter.execution_environment()
    executable = command[0] if command else None
    resolved = shutil.which(executable) if executable else None
    if not resolved:
        return PassiveProviderReport(
            profile=profile.name,
            provider=profile.provider,
            model=profile.model,
            role=profile.role,
            executable=executable,
            executable_path=None,
            version=None,
            effective_argv=redact_command(command),
            environment_keys=environment_key_manifest(environment),
            authentication_state="NOT_CHECKED",
            authentication_detail="provider authentication was not probed because the executable is missing",
            status="MISSING",
            detail=f"executable {executable!r} not found on PATH",
        )

    version = _version(resolved, environment)
    auth_state = "NOT_CHECKED"
    auth_detail = "command override is active; authentication is provider-command-specific"
    uses_native_cli = executable == _AUTH_EXECUTABLES.get(profile.provider)
    if profile.provider in _AUTH_EXECUTABLES and uses_native_cli:
        auth = auth_status(profile.provider)
        auth_state = auth.state
        auth_detail = auth.detail
        status = "READY" if auth.authenticated else "AUTH_REQUIRED"
        detail = auth.detail
    else:
        status = "READY"
        detail = resolved

    return PassiveProviderReport(
        profile=profile.name,
        provider=profile.provider,
        model=profile.model,
        role=profile.role,
        executable=executable,
        executable_path=resolved,
        version=version,
        effective_argv=redact_command(command),
        environment_keys=environment_key_manifest(environment),
        authentication_state=auth_state,
        authentication_detail=auth_detail,
        status=status,
        detail=detail,
    )


def _git_probe_workspace(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "arc-probe@example.test"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "ARC Provider Probe"],
        check=True,
        capture_output=True,
        text=True,
    )


def _active_payload(result: AgentRunResult, *, marker_seen: bool) -> dict[str, Any]:
    diagnostics = sanitize_failure_diagnostics(result)
    provider_tokens = result.token_usage.get("prompt_tokens", 0) + result.token_usage.get(
        "completion_tokens", 0
    )
    diagnostics.update(
        {
            "success": result.status == "completed" and marker_seen,
            "marker_seen": marker_seen,
            "status": result.status,
            "provider_tokens": provider_tokens if provider_tokens > 0 else None,
            "token_usage_observed": provider_tokens > 0,
        }
    )
    return diagnostics


def run_provider_probe(
    profile: AgentProfile,
    *,
    output_path: Path | None = None,
    timeout_seconds: int = 45,
) -> dict[str, Any]:
    """Run one isolated active probe and persist its non-benchmark result."""
    if timeout_seconds < 1:
        raise ValueError("provider probe timeout_seconds must be positive")
    started_at = datetime.now(timezone.utc).isoformat()
    passive = passive_provider_doctor(profile)
    active: dict[str, Any]

    if passive.status != "READY":
        active = {
            "status": "not_run",
            "success": False,
            "reason": f"passive doctor status={passive.status}",
        }
    else:
        try:
            adapter = build_agent(profile)
            if not isinstance(adapter, SubprocessCodingAgent):
                raise RuntimeError("provider has no subprocess-backed active probe adapter")
            with tempfile.TemporaryDirectory(prefix="arc-provider-probe-") as raw_workspace:
                workspace = Path(raw_workspace)
                _git_probe_workspace(workspace)
                result = asyncio.run(
                    adapter.run_prompt(
                        prompt=SMOKE_PROMPT,
                        workspace=workspace,
                        budget=AgentBudget(
                            max_usd=0.25,
                            max_tokens=1000,
                            timeout_seconds=timeout_seconds,
                        ),
                    )
                )
                marker_seen = "ARC_PROVIDER_SMOKE_OK" in (result.stdout_tail + result.summary)
                active = _active_payload(result, marker_seen=marker_seen)
                active["workspace_disposable"] = True
        except Exception as exc:
            active = {
                "status": "probe_error",
                "success": False,
                "reason": str(exc)[:280],
                "workspace_disposable": True,
            }

    report: dict[str, Any] = {
        "schema": "arc-provider-probe-v1",
        "timestamp_utc": started_at,
        "profile": profile.name,
        "provider": profile.provider,
        "model": profile.model,
        "role": profile.role,
        "passive": asdict(passive),
        "active": active,
        "active_probe": True,
        "configured_timeout_seconds": timeout_seconds,
        "benchmark_context": False,
        "scientific_evidence": False,
        "result_directory_policy": "outside benchmark result directories",
    }
    if output_path is not None:
        output_path = output_path.resolve()
        if output_path.exists():
            raise FileExistsError(f"refusing to overwrite existing provider probe: {output_path}")
        report["output_path"] = str(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report
